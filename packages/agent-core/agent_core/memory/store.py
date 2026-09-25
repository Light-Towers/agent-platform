# -*- coding: utf-8 -*-
"""统一记忆存储门面（WS-1：三栈收敛的单一契约）。

背景：此前语义记忆存在三条并行栈——``semantic`` 门面（Milvus/pg 向量后端）、
``typed`` 模块（宿主 psycopg 池 + 类型化加权）、``mongo`` 会话历史——契约与
embedding 来源互不相通。本模块定义 ``MemoryStore`` 统一协议，把「召回 / 沉淀 /
巩固 / 遗忘 / 能力探测」收敛为五个动词，后端实现作为可插拔适配器：

- ``PgMemoryStore``：包装 ``typed`` 模块（宿主 psycopg 池，遵守 ADR-0003 单一
  连接源），支持全部五动词，**pg 为唯一权威后端**（阶段 1 决策）；
- ``VectorMemoryStore``：包装 ``MemoryBackend``（Milvus 默认 / PgVector 备选），
  仅 recall / remember；consolidate / forget 不支持（无类型列）。

``CapabilityReport`` 供宿主 ``/health`` 暴露记忆能力状态，消除「开关配错 →
静默无记忆且无从排查」的问题：``probe()`` 永不抛异常。

§3 内核护栏：仅 stdlib；embedder / pool 均由构造注入，内核不反向依赖宿主。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Protocol, runtime_checkable

from agent_core.logging import get_logger
from agent_core.memory._tenant_gate import _TENANT_UNSET, resolve_tenant

logger = get_logger(__name__)


# --- 能力探测 ---------------------------------------------------------------

@dataclass
class CapabilityReport:
    """记忆能力探测报告（宿主 /health 可直接序列化）。

    - ``enabled``：该 store 当前是否可用；
    - ``backend``：后端标识（pg-typed / milvus / pgvector / ...）；
    - ``embedder_source``：embedding 来源描述（injected / backend-internal / none）；
    - ``supports_consolidate`` / ``supports_forget``：生命周期动词支持性；
    - ``supports_tenant_isolation``：``tenant_id`` 是否真正参与数据隔离过滤
      （False = 仅为协议兼容位被忽略，调用方不可误以为已获得租户隔离）；
    - ``reason``：enabled=False 时的原因（缺依赖 / 未配置 / 初始化失败）。
    """

    enabled: bool
    backend: str
    embedder_source: str = "none"
    supports_consolidate: bool = False
    supports_forget: bool = False
    supports_tenant_isolation: bool = False
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "backend": self.backend,
            "embedder_source": self.embedder_source,
            "supports_consolidate": self.supports_consolidate,
            "supports_forget": self.supports_forget,
            "supports_tenant_isolation": self.supports_tenant_isolation,
            "reason": self.reason,
        }


# --- 统一协议 ---------------------------------------------------------------

@runtime_checkable
class MemoryStore(Protocol):
    """统一记忆存储协议（五动词：recall / remember / consolidate / forget / probe）。

    ``user_id`` 语义由宿主决定（平台侧为 workspace_id，联邦侧为 user_id），
    契约层不解释。``tenant_id`` 为租户隔离键：宿主必须从请求上下文显式传入，
    漏传会静默落共享 ``default`` 桶（pg-typed 路径按 tenant 过滤；向量后端无
    tenant 列，不支持隔离，见 ``VectorMemoryStore``）。所有方法失败时应降级
    （返回空 / False / 0）并记日志，绝不向主链路抛异常——记忆是增强不是正确性依赖。
    """

    async def recall(
        self, user_id: str, question: str, k: int = 3, *, tenant_id: str= _TENANT_UNSET
    ) -> list[str]:
        """召回与 question 相关的记忆文本（未启用/失败返回 []）。"""
        ...

    async def remember(
        self, user_id: str, content: str, *, tenant_id: str= _TENANT_UNSET
    ) -> None:
        """沉淀一条记忆（非阻塞语义：实现可 fire-and-forget）。"""
        ...

    async def consolidate(
        self, user_id: str, *, tenant_id: str= _TENANT_UNSET, **kwargs: Any
    ) -> int:
        """巩固 + 遗忘低价值记忆，返回删除条数（不支持时返回 0）。"""
        ...

    async def forget(
        self, user_id: str, memory_id: Any, *, tenant_id: str= _TENANT_UNSET
    ) -> bool:
        """显式遗忘单条记忆（不支持时返回 False）。"""
        ...

    def probe(self) -> CapabilityReport:
        """能力探测（同步、永不抛异常）。"""
        ...


# --- 实现一：pg typed 路径（权威后端）----------------------------------------

class PgMemoryStore:
    """``typed`` 模块的 MemoryStore 适配器（宿主 psycopg 池 + 宿主 embedder）。

    embedding 统一由构造注入的 ``embed_fn`` 提供（``text -> list[float]`` 同步
    或异步均可），消除「semantic 门面内部 embedder / typed 要求宿主传 embedding」
    双契约并存的问题。pool 同样构造注入，遵守 ADR-0003 单一连接源。
    """

    def __init__(
        self,
        pool: Any,
        embed_fn: Any,
        *,
        weights: Iterable[tuple[str, float]] | None = None,
    ) -> None:
        self._pool = pool
        self._embed_fn = embed_fn
        self._weights = weights

    async def _embed(self, text: str) -> list[float]:
        import inspect

        result = self._embed_fn(text)
        if inspect.isawaitable(result):
            result = await result
        return list(result)

    async def recall(
        self, user_id: str, question: str, k: int = 3, *, tenant_id: str= _TENANT_UNSET
    ) -> list[str]:
        tenant_id = resolve_tenant(tenant_id)
        if not user_id or not question or self._pool is None:
            return []
        try:
            from agent_core.memory.typed import recall_typed

            embedding = await self._embed(question)
            memories = await recall_typed(
                self._pool,
                user_id=user_id,
                question=question,
                k=k,
                weights=self._weights,
                embedding=embedding,
                tenant_id=tenant_id,
            )
            return [m.content for m in memories]
        except Exception as e:
            logger.warning("PgMemoryStore.recall 失败，降级为空: %s", e)
            return []

    async def remember(
        self,
        user_id: str,
        content: str,
        *,
        memory_type: str = "semantic",
        importance: float = 0.5,
        tenant_id: str= _TENANT_UNSET,
    ) -> None:
        tenant_id = resolve_tenant(tenant_id)
        if not user_id or not content or self._pool is None:
            return
        try:
            from agent_core.memory.typed import remember_typed

            embedding = await self._embed(content)
            await remember_typed(
                self._pool,
                user_id=user_id,
                fact=content,
                memory_type=memory_type,
                importance=importance,
                embedding=embedding,
                tenant_id=tenant_id,
            )
        except Exception as e:
            logger.warning("PgMemoryStore.remember 失败，静默降级: %s", e)

    async def consolidate(
        self,
        user_id: str,
        *,
        forget_threshold: float | None = None,
        age_days: int | None = None,
        tenant_id: str= _TENANT_UNSET,
    ) -> int:
        tenant_id = resolve_tenant(tenant_id)
        if not user_id or self._pool is None:
            return 0
        try:
            from agent_core.memory.typed import consolidate

            return await consolidate(
                user_id,
                self._pool,
                forget_threshold=forget_threshold,
                age_days=age_days,
                tenant_id=tenant_id,
            )
        except Exception as e:
            logger.warning("PgMemoryStore.consolidate 失败: %s", e)
            return 0

    async def forget(self, user_id: str, memory_id: Any, *, tenant_id: str= _TENANT_UNSET) -> bool:
        tenant_id = resolve_tenant(tenant_id)
        if not user_id or self._pool is None:
            return False
        try:
            from agent_core.memory.typed import forget

            return await forget(user_id, self._pool, memory_id, tenant_id=tenant_id)
        except Exception as e:
            logger.warning("PgMemoryStore.forget 失败: %s", e)
            return False

    def probe(self) -> CapabilityReport:
        if self._pool is None:
            return CapabilityReport(
                enabled=False, backend="pg-typed", reason="pool 未注入（宿主未配置数据库）"
            )
        if self._embed_fn is None:
            return CapabilityReport(
                enabled=False, backend="pg-typed", reason="embed_fn 未注入"
            )
        return CapabilityReport(
            enabled=True,
            backend="pg-typed",
            embedder_source="injected",
            supports_consolidate=True,
            supports_forget=True,
            supports_tenant_isolation=True,  # typed SQL 按 tenant_id 精确过滤
        )


# --- 实现二：向量后端包装（Milvus / PgVector，可选实现）-----------------------

class VectorMemoryStore:
    """``MemoryBackend``（Milvus 默认 / PgVector 备选）的 MemoryStore 适配器。

    仅支持 recall / remember（后端无类型列）；consolidate / forget 返回
    0 / False 并在 probe 中如实声明。embedding 由被包装后端内部管理
    （``backend-internal``），本适配器不重复嵌入。

    租户隔离限制：Milvus/PgVector 后端无 tenant 列，``tenant_id`` 仅为协议
    兼容位（被忽略）——需要租户隔离的宿主应使用 ``PgMemoryStore``。
    """

    def __init__(self, backend: Any, pool: Any = None) -> None:
        self._backend = backend
        self._pool = pool

    async def recall(
        self, user_id: str, question: str, k: int = 3, *, tenant_id: str= _TENANT_UNSET
    ) -> list[str]:
        tenant_id = resolve_tenant(tenant_id)
        if not user_id or not question or self._backend is None:
            return []
        try:
            return await self._backend.recall(self._pool, user_id, question, k=k)
        except Exception as e:
            logger.warning("VectorMemoryStore.recall 失败，降级为空: %s", e)
            return []

    async def remember(
        self, user_id: str, content: str, *, tenant_id: str= _TENANT_UNSET
    ) -> None:
        tenant_id = resolve_tenant(tenant_id)
        if not user_id or not content or self._backend is None:
            return
        try:
            self._backend.remember(self._pool, user_id, content)
        except Exception as e:
            logger.warning("VectorMemoryStore.remember 调度失败: %s", e)

    async def consolidate(self, user_id: str, *, tenant_id: str= _TENANT_UNSET, **kwargs: Any) -> int:
        return 0  # 向量后端无类型/重要性列，不支持巩固遗忘

    async def forget(
        self, user_id: str, memory_id: Any, *, tenant_id: str= _TENANT_UNSET
    ) -> bool:
        return False  # 同上

    def probe(self) -> CapabilityReport:
        if self._backend is None:
            return CapabilityReport(
                enabled=False, backend="vector", reason="后端未初始化"
            )
        name = type(self._backend).__name__
        return CapabilityReport(
            enabled=True,
            backend=name,
            embedder_source="backend-internal",
            supports_consolidate=False,
            supports_forget=False,
            supports_tenant_isolation=False,  # 后端无 tenant 列，tenant_id 被忽略
        )


__all__ = [
    "CapabilityReport",
    "MemoryStore",
    "PgMemoryStore",
    "VectorMemoryStore",
]
