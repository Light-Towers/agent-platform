"""Large Payload Externalization（V3-6 Layer B）。

.. note::
   **STATUS: WIRED（2026-10-15，默认关）** – 接线点是 ``PgCheckpointStore``：``save()``
   落库前 ``externalize_completed()``、``load()`` 读回后 ``internalize_completed()``
   （**先 internalize 再 schema migrate**，否则迁移函数会拿到 reference 而非真实 payload）。
   由 ``PAYLOAD_EXTERNALIZATION_ENABLED`` 门控，**默认 False**；开启还须给
   ``PAYLOAD_EXTERNALIZATION_DIR``，否则 agent_server 启动即 RuntimeError（不静默退回"没开"）。
   边界：① 只接 PG 后端——缺口原文是「大 payload 塞 checkpoint **JSONB**」，进程内
   checkpoint 再套一层进程内 blob store 是自我矛盾，刻意不接；② 联邦 planner 侧未接；
   ③ blob 无 retention/GC、且与 PG 非同事务（详见方案 §6.4）。
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
from dataclasses import dataclass
from typing import Any


@dataclass
class ExternalizationConfig:
    """外部化配置。"""

    threshold_bytes: int = 1024 * 1024  # 1MB：超此阈值外部化
    store_name: str = "blob"  # blob store 名称（reference 中记录）


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


class InMemoryPayloadStore(PayloadStore):
    """进程内 blob 存储（测试 / 单进程默认）。"""

    def __init__(self) -> None:
        self._store: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes) -> None:
        self._store[key] = data

    async def get(self, key: str) -> bytes | None:
        return self._store.get(key)

    async def delete(self, key: str) -> bool:
        return self._store.pop(key, None) is not None


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


__all__ = [
    "ExternalizationConfig",
    "PayloadStore",
    "InMemoryPayloadStore",
    "FileSystemPayloadStore",
    "PayloadExternalizer",
    "is_reference",
]
