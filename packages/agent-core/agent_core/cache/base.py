# -*- coding: utf-8 -*-
"""语义缓存统一契约：``SemanticCacheBackend`` Protocol、健康态与 key 构造单一真相。

零依赖（仅 stdlib）。生产与开发/测试使用同一实现（Valkey），PG 语义缓存已退役；
本模块只定义契约与 key 构造，调用点不得自行拼 key 或绕过隔离谓词。

参考：``docs/adr/0013-semantic-cache-single-track.md``（Accepted C）。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable


@dataclass(frozen=True, slots=True)
class CacheHealth:
    """缓存健康态（只报运行真值，不回显任何连接串/凭据）。"""

    backend: str
    ready: bool
    degraded_reason: str | None = None
    index: str | None = None


@dataclass(frozen=True, slots=True)
class CacheHit:
    """命中结果。``layer`` 为 ``l1`` / ``l2`` / ``null``。

    ``null`` 表示已知空结果（负缓存），调用方应短路昂贵查询；是否把空答案
    直接返回由调用方决定（agent_server 不写负缓存，federation 用于防穿透）。
    """

    value: dict[str, Any]
    layer: str
    distance: float | None = None
    similarity: float | None = None


@runtime_checkable
class SemanticCacheBackend(Protocol):
    """可执行语义缓存契约（async）。

    实现方必须保证：租户为空 fail-closed；后端异常 fail-open（按未命中处理）；
    ``scope`` 由装配期注入，不由请求体控制。
    """

    enabled: bool

    async def get(
        self,
        *,
        tenant_id: str,
        intent: str,
        rewritten_query: str,
        kb_versions: Mapping[str, str] | None = None,
        gray_pct: float = 0.0,
        embedding: Sequence[float] | None = None,
    ) -> CacheHit | None:
        """查询缓存；未命中或任何后端异常返回 None。"""
        ...

    async def set(
        self,
        *,
        tenant_id: str,
        intent: str,
        rewritten_query: str,
        value: Mapping[str, Any],
        kb_versions: Mapping[str, str] | None = None,
        gray_pct: float = 0.0,
        embedding: Sequence[float] | None = None,
        ttl_seconds: int | None = None,
    ) -> None:
        """写入正向缓存（有界队列；队列满时丢弃并计数，不阻塞调用方）。

        写侧 PII 门禁：``rewritten_query`` 或 ``value`` 检出 PII 时跳过写入并计数
        （``skipped_pii``）——缓存是另一套系统里的持久副本，而命中路径直接返回答案、
        不再跑应用的输出护栏。
        """
        ...

    async def set_negative(
        self,
        *,
        tenant_id: str,
        intent: str,
        rewritten_query: str,
        kb_versions: Mapping[str, str] | None = None,
        gray_pct: float = 0.0,
    ) -> None:
        """写入负缓存（短 TTL），并清掉同 key 的正向条目。"""
        ...

    async def invalidate(
        self,
        *,
        tenant_id: str,
        intent: str,
        rewritten_query: str,
        kb_versions: Mapping[str, str] | None = None,
        gray_pct: float = 0.0,
    ) -> None:
        """精确失效单个逻辑 key（L1/L2/负缓存）。"""
        ...

    async def invalidate_namespace(self, *, tenant_id: str) -> None:
        """失效某租户在本 scope 下的全部缓存（epoch 递增，旧 key 不可达）。"""
        ...

    async def flush(self) -> None:
        """等待写队列排空（测试与优雅退出用）。"""
        ...

    async def health(self) -> CacheHealth:
        """返回健康态；探针路径不得触发 embedder 加载。"""
        ...

    async def aclose(self) -> None:
        """关闭连接与后台任务。"""
        ...

    def get_stats(self) -> dict[str, Any]:
        """返回命中率与运行计数快照。

        **计数器键集合是契约的一部分**：消费方把这份 dict 用 `**get_stats()` 摊进监控事件与
        `/health`，少一个键不会报错，只会按后端不同给出另一种事件形状。任何实现都必须给出
        `error / skipped_no_tenant / skipped_unsafe_tag / skipped_pii / dropped_writes /
        embedding_error / l2_unavailable / index_missing` 全套计数（不计数的那一类填 0），
        `backend` 与 `scope` 两个标识键同理。反证用例：
        `test_disabled_backend_reports_every_valkey_runtime_counter`。
        """
        ...

    def reset_stats(self) -> None:
        """重置统计。"""
        ...


def build_cache_key(
    intent: str,
    rewritten_query: str,
    kb_versions: Mapping[str, str] | None = None,
    tenant_id: str = "",
    gray_pct: float = 0.0,
    *,
    scope: str = "",
    embedding_model: str = "",
    dim: int = 0,
) -> str:
    """构造语义缓存 key（单一真相，纯函数）。

    默认形态保持历史公式不变：
    ``sha256(intent|rewritten_query|kb_versions_json|tenant_id|gray_pct)``。
    仅当传入 scope/embedding_model/dim 时追加 ``|scope|model|dim``，因此旧
    key 不会因契约扩展而失效；新实现（Valkey）恒传入三者，保证换模型/换维度
    即换命名空间。

    :param intent: 意图标签
    :param rewritten_query: 改写后的 query
    :param kb_versions: 各子服务 KB 版本（影响 key，版本变更自动失效旧缓存）
    :param tenant_id: 租户隔离
    :param gray_pct: 灰度比例（影响 key，避免灰度/正式缓存串味）
    :param scope: 流水线分区常量（agent_server / federation），不是隔离维度
    :param embedding_model: embedding 模型标识（索引与 key 的命名空间组成）
    :param dim: embedding 维度
    :return: 64 位十六进制 sha256
    """
    kb_str = json.dumps(dict(kb_versions or {}), sort_keys=True)
    raw = f"{intent}|{rewritten_query}|{kb_str}|{tenant_id}|{gray_pct}"
    if scope or embedding_model or dim:
        raw += f"|{scope}|{embedding_model}|{dim}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


__all__ = ["CacheHealth", "CacheHit", "SemanticCacheBackend", "build_cache_key"]
