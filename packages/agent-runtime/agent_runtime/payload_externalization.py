"""Large Payload Externalization（V3-6 Layer B）。

.. note::
   **STATUS: WIRED（2026-10-15，默认关）** – 接线点是 ``PgCheckpointStore``：``save()``
   落库前 ``externalize_completed()``、``load()`` 读回后 ``internalize_completed()``
   （**先 internalize 再 schema migrate**，否则迁移函数会拿到 reference 而非真实 payload）。
   由 ``PAYLOAD_EXTERNALIZATION_ENABLED`` 门控，**默认 False**；开启还须给
   ``PAYLOAD_EXTERNALIZATION_DIR``，否则 agent_server 启动即 RuntimeError（不静默退回"没开"）。
   边界：① 只接 PG 后端——缺口原文是「大 payload 塞 checkpoint **JSONB**」，进程内
   checkpoint 再套一层进程内 blob store 是自我矛盾，刻意不接；② 联邦 planner 侧未接；
   ③ **retention/GC 已补（2026-10-19，缺口 7 残留）**：``PayloadExternalizer.sweep``
   age-based 保守删除（默认 7 天下限，留年轻/删年老，单 key 异常不中断），由
   ``SchedulerReaper(sweep_callbacks=...)`` 周期触发；**#121 同批补引用检查**——
   sweep 接受 ``referenced_keys``（PG checkpoint 仍引用的 blob key，见
   ``PgCheckpointStore.collect_externalized_keys``），在途引用（含挂起超 7 天的
   awaitable resume）不再被误删；``gc_min_age_hours`` 已 env 化
   （``PAYLOAD_EXTERNALIZATION_GC_MIN_AGE_HOURS``）。**仍未修**：与 PG 非同事务
   （fence 拒绝 ⇒ 泄漏单体）——正解是 blob 索引表（需迁移），属独立项；age  sweep
   把泄漏面压平（不再无界）但不清零单体。
   **启用门槛**（2026-10-19 #121 文档化）：① blob 目录须在**持久卷**上（临时目录
   = 重启即静默数据损坏，而 load 路径对缺失 blob 只降级不抛）；② ``gc_min_age_hours``
   必须大于**最长合法挂起时长**（awaitable resume 的天数上限），否则引用检查也救不了
   设计上就该删的引用；③ 删除候选的引用扫描是全表 ``jsonb_each``，调用方须"先候选
   后扫描"（见 agent_server 的 GC 接线）。
   （此前状态为 NOT WIRED，P1-7 审计披露 2026-09-24）

现状（v3 之前）：工具返回 50MB JSON 直接塞 checkpoint JSONB，影响 compaction /
retention / 查询性能。

本模块补上：
- ``PayloadStore``：blob 存储契约（InMemory + 文件系统适配器）；
- ``PayloadExternalizer``：超阈值时外部化到 blob store，checkpoint 只保存 reference；
- ``externalize`` / ``internalize``：双向转换。

不自建对象存储（Part C 红线），用现有 S3/MinIO/本地 blob。

reference 格式：
```
{"__external__": true, "store": "blob", "key": "payload/xxx", "size": 12345, "checksum": "sha256:..."}
```

checkpoint completed 中的大 payload 被替换为 reference，load 时自动 internalize 还原。
"""

from __future__ import annotations

import abc
import hashlib
import json
import uuid
from collections.abc import Collection
from dataclasses import dataclass
from typing import Any


@dataclass
class ExternalizationConfig:
    """外部化配置。"""

    threshold_bytes: int = 1024 * 1024  # 1MB：超此阈值外部化
    store_name: str = "blob"  # blob store 名称（reference 中记录）
    # GC：age-based sweep 的年龄下限（小时）。只删年龄 ≥ 此值的 blob——在途
    # checkpoint 的引用不会被打扫误伤（age 下限即安全边际；load 路径对缺失
    # blob 本就优雅降级：返回 reference + 告警）。默认 7 天。
    # #121：已 env 化（PAYLOAD_EXTERNALIZATION_GC_MIN_AGE_HOURS）；**必须大于
    # 最长合法挂起时长**（awaitable resume 天数上限），否则引用检查也救不了
    # 设计上就该删的引用。
    gc_min_age_hours: int = 168


class PayloadStore(abc.ABC):
    """blob 存储契约。"""

    @abc.abstractmethod
    async def put(self, key: str, data: bytes) -> None:
        """存储 payload。"""

    @abc.abstractmethod
    async def get(self, key: str) -> bytes | None:
        """读取 payload。"""

    @abc.abstractmethod
    async def delete(self, key: str) -> bool:
        """删除 payload。返回是否存在且已删。"""

    @abc.abstractmethod
    async def list_keys(self) -> list[str]:
        """列出全部 key（sweep 用；InMemory=插入序，FS=目录遍历序）。"""

    @abc.abstractmethod
    async def key_age_s(self, key: str) -> float | None:
        """key 的年龄（秒，wall-clock）；不存在返回 None。

        InMemory 记 put 时刻；FileSystem 用 mtime。二者同口径（time.time()），
        sweep 的 age 判据跨实现一致。
        """


class InMemoryPayloadStore(PayloadStore):
    """进程内 blob 存储（测试 / 单进程默认）。"""

    def __init__(self) -> None:
        self._store: dict[str, bytes] = {}
        self._put_at: dict[str, float] = {}

    async def put(self, key: str, data: bytes) -> None:
        import time

        self._store[key] = data
        self._put_at[key] = time.time()

    async def get(self, key: str) -> bytes | None:
        return self._store.get(key)

    async def delete(self, key: str) -> bool:
        self._put_at.pop(key, None)
        return self._store.pop(key, None) is not None

    async def list_keys(self) -> list[str]:
        return list(self._store)

    async def key_age_s(self, key: str) -> float | None:
        import time

        put_at = self._put_at.get(key)
        return None if put_at is None else max(0.0, time.time() - put_at)


class FileSystemPayloadStore(PayloadStore):
    """文件系统 blob 存储。

    生产环境可替换为 S3/MinIO 适配器（同一 PayloadStore 契约）。
    """

    def __init__(self, base_dir: str) -> None:
        import os
        self._base = base_dir
        os.makedirs(base_dir, exist_ok=True)

    async def put(self, key: str, data: bytes) -> None:
        import os
        path = os.path.join(self._base, key.replace("/", os.sep))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)

    async def get(self, key: str) -> bytes | None:
        import os
        path = os.path.join(self._base, key.replace("/", os.sep))
        if not os.path.exists(path):
            return None
        with open(path, "rb") as f:
            return f.read()

    async def delete(self, key: str) -> bool:
        import os
        path = os.path.join(self._base, key.replace("/", os.sep))
        if os.path.exists(path):
            os.remove(path)
            return True
        return False

    async def list_keys(self) -> list[str]:
        import os

        keys: list[str] = []
        for root, _dirs, files in os.walk(self._base):
            for name in files:
                abs_path = os.path.join(root, name)
                rel = os.path.relpath(abs_path, self._base).replace(os.sep, "/")
                keys.append(rel)
        return keys

    async def key_age_s(self, key: str) -> float | None:
        import os
        import time

        path = os.path.join(self._base, key.replace("/", os.sep))
        if not os.path.exists(path):
            return None
        return max(0.0, time.time() - os.path.getmtime(path))


def is_reference(value: Any) -> bool:
    """判断是否为外部化 reference（公开：接线层需要识别"没还原成功"的残值）。"""
    return (
        isinstance(value, dict)
        and value.get("__external__") is True
        and "key" in value
    )


def _make_reference(key: str, size: int, checksum: str, store_name: str) -> dict[str, Any]:
    return {
        "__external__": True,
        "store": store_name,
        "key": key,
        "size": size,
        "checksum": checksum,
    }


class PayloadExternalizer:
    """大 payload 外部化 / 内部化。"""

    def __init__(
        self,
        store: PayloadStore,
        config: ExternalizationConfig | None = None,
    ) -> None:
        self._store = store
        self._config = config or ExternalizationConfig()

    async def externalize(self, value: Any) -> Any:
        """外部化单个值：超阈值 → blob store + reference；否则原样返回。"""
        if not self._should_externalize(value):
            return value

        data = json.dumps(value, ensure_ascii=False).encode("utf-8")
        key = f"payload/{uuid.uuid4().hex}"
        checksum = f"sha256:{hashlib.sha256(data).hexdigest()}"
        await self._store.put(key, data)
        return _make_reference(key, len(data), checksum, self._config.store_name)

    async def internalize(self, value: Any) -> Any:
        """内部化单个值：reference → 从 blob store 读取还原；否则原样返回。"""
        if not is_reference(value):
            return value

        data = await self._store.get(value["key"])
        if data is None:
            return value  # blob 不存在，返回 reference 供调用方处理
        return json.loads(data.decode("utf-8"))
    async def externalize_completed(
        self, completed: dict[str, Any]
    ) -> dict[str, Any]:
        """外部化 checkpoint.completed 中所有大 payload。"""
        result = {}
        for node_id, node_result in completed.items():
            result[node_id] = await self.externalize(node_result)
        return result

    async def internalize_completed(
        self, completed: dict[str, Any]
    ) -> dict[str, Any]:
        """内部化 checkpoint.completed 中所有 reference。"""
        result = {}
        for node_id, node_result in completed.items():
            result[node_id] = await self.internalize(node_result)
        return result

    def _should_externalize(self, value: Any) -> bool:
        """判断是否需要外部化。"""
        if is_reference(value):
            return False  # 已是 reference
        try:
            size = len(json.dumps(value, ensure_ascii=False).encode("utf-8"))
        except (TypeError, ValueError):
            return False
        return size > self._config.threshold_bytes

    async def list_gc_candidates(self, min_age_seconds: float | None = None) -> list[str]:
        """列出年龄 ≥ 下限的 blob key（**不删**）。

        两段式 GC 的第一段（#121）：调用方先问"有没有该删的"，再决定是否付出
        引用扫描成本（全表 jsonb_each）。稳态（无候选）时零 PG 开销。store
        列举/取年龄失败一律返回空——保守口径：问不出该删什么就不删。
        """
        min_age = (
            min_age_seconds
            if min_age_seconds is not None
            else self._config.gc_min_age_hours * 3600
        )
        try:
            keys = await self._store.list_keys()
        except OSError:
            return []
        aged: list[str] = []
        for key in keys:
            try:
                age = await self._store.key_age_s(key)
            except OSError:
                continue  # 单 key 取年龄失败：不当候选（不删）
            if age is not None and age >= min_age:
                aged.append(key)
        return aged

    async def sweep(
        self,
        min_age_seconds: float | None = None,
        *,
        referenced_keys: Collection[str] | None = None,
    ) -> dict[str, int]:
        """age-based GC（2026-10-19，缺口 7 残留；#121 引用检查）。

        删除年龄 ≥ 下限**且不在 referenced_keys** 的 blob。返回报告
        ``{scanned, deleted, skipped_young, skipped_referenced, errors}``：
        - ``scanned``：store 内 key 总数；
        - ``deleted``：实际删除数；
        - ``skipped_young``：年龄 < 下限被跳过的（在途 checkpoint 引用的安全边际）；
        - ``skipped_referenced``（#121 新增）：够老但**仍被引用**而保留的——
          删了 in-flight 引用，load 路径 internalize 就静默返回 reference（数据损坏）；
        - ``errors``：单 key 删除/取年龄异常数（不中断扫描）。

        **引用检查的正确性依赖**（#121）：``referenced_keys`` 由调用方从 PG
        checkpoint 收集（``PgCheckpointStore.collect_externalized_keys``），且须
        在删除前收集完（两段式：先 ``list_gc_candidates`` 有候选再扫描，避免
        稳态每周期全表扫）。age 判据本身不查引用（成本不当）⇒ 不传
        ``referenced_keys`` 时行为与 #121 前一致（纯 age），仅用于无 PG 引用
        源的场景。
        """
        referenced = set(referenced_keys or ())
        min_age = (
            min_age_seconds
            if min_age_seconds is not None
            else self._config.gc_min_age_hours * 3600
        )
        report = {
            "scanned": 0,
            "deleted": 0,
            "skipped_young": 0,
            "skipped_referenced": 0,
            "errors": 0,
        }
        try:
            keys = await self._store.list_keys()
        except OSError:
            # store 列举失败（FS 层 IO）：整轮跳过而非崩——上报一次错误即可
            report["errors"] += 1
            return report
        for key in keys:
            report["scanned"] += 1
            try:
                age = await self._store.key_age_s(key)
                if age is None or age < min_age:
                    report["skipped_young"] += 1
                    continue
                if key in referenced:
                    # #121：仍在途的引用（含挂起超 min_age 的 awaitable resume）——
                    # 删了 internalize 就静默返回 reference ⇒ 数据损坏
                    report["skipped_referenced"] += 1
                    continue
                if await self._store.delete(key):
                    report["deleted"] += 1
            except OSError:
                # 单 key 的 IO 故障（取年龄/删除）：计入 errors 不中断扫描
                # （D7 ratchet：只容 IO 类，其他异常属编程错误应暴露）
                report["errors"] += 1
        return report


__all__ = [
    "ExternalizationConfig",
    "PayloadStore",
    "InMemoryPayloadStore",
    "FileSystemPayloadStore",
    "PayloadExternalizer",
    "is_reference",
]
