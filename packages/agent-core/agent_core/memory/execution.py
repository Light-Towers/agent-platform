# -*- coding: utf-8 -*-
"""执行记忆协议（内核契约，ADR-0005）。

本模块下沉「执行记忆」的统一协议到 ``agent-core``，使 ``agent-runtime`` 的实现
（``PgEpisodicStore`` / ``PgProceduralStore``）与未来 ``agent_federation`` 的执行记忆路径
共享同一契约——消除 F5/F6（内核只覆盖语义记忆、runtime 自建执行记忆）导致的
「双份真相源」生长土壤。

范式：协议下沉内核（零依赖签名）+ 实现留宿主（薄适配器）+ 开关灰度。
与 ADR-0004（类型化语义记忆下沉）同构。

§1.3 命名互斥（重要，切勿踩坑）：
- 本协议的 ``Episode`` 概念指**一次执行的完整轨迹**的持久化形式（落 ``episodic_memories``）；
- ``agent_core.memory.typed.MemoryType.episodic`` 指 ``memories`` 表内一条**情节型语义事实**
  （如「用户上周问过 X」）。二者同名不同义，靠物理隔离（不同表、不同包）区分。

数据模型归属（刻意选择，避免重复造真相源）：
``Episode`` / ``ProceduralEntry`` dataclass 由宿主 ``agent-runtime`` 定义并拥有（已是事实真相源）；
内核**只下沉协议接口**，方法签名中的实体类型由宿主实现提供（structural typing 不约束具体类型）。
在内核再定义一份 dataclass 会重现双份真相源，与 ADR-0005 目标相悖，故不重复定义。

租户隔离语义约束（与 ``MemoryStore`` 一致）：所有方法**必须显式带 ``tenant_id``**；
漏传经 ``_tenant_gate.resolve_tenant`` fail-fast，绝不静默落共享 ``default`` 桶——
归属不明的记忆宁可暂不可见，也不跨租户可见（ADR-0006 安全边界）。

§3 内核护栏：本模块仅 import stdlib + ``agent_core.memory._tenant_gate``（同为内核内部），
不反向依赖 ``agent-runtime``，遵守 agent-core 零依赖铁律。
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from agent_core.memory._tenant_gate import _TENANT_UNSET


@runtime_checkable
class EpisodicStoreProtocol(Protocol):
    """Episodic Memory 持久化协议（执行轨迹）。

    方法集对齐 ``agent_runtime.episodic_memory.EpisodicStore`` 抽象契约。
    ``runtime_checkable`` 下 ``isinstance(PgEpisodicStore(pool), EpisodicStoreProtocol)``
    仅校验方法存在性（structural typing），不要求改 runtime 基类即可满足。
    """

    async def save(self, episode: Any, *, tenant_id: str = _TENANT_UNSET) -> None:
        """保存 Episode（按 tenant 归属）。"""
        ...

    async def recall(
        self, query: str, top_k: int = 10, *, tenant_id: str = _TENANT_UNSET
    ) -> list[Any]:
        """按查询召回本租户相关 Episode。"""
        ...

    async def get(self, episode_id: str, *, tenant_id: str = _TENANT_UNSET) -> Any:
        """按 ID 读取（租户内）。"""
        ...

    async def list_by_execution(
        self, execution_id: str, *, tenant_id: str = _TENANT_UNSET
    ) -> list[Any]:
        """列出某 execution 的所有 Episode（租户内）。"""
        ...

    async def list_all(
        self, limit: int = 10000, *, tenant_id: str = _TENANT_UNSET
    ) -> list[Any]:
        """列出本租户所有 Episode（供 ProceduralExtractor 挖掘）。"""
        ...

    async def delete(self, episode_id: str, *, tenant_id: str = _TENANT_UNSET) -> bool:
        """删除本租户 Episode。"""
        ...


@runtime_checkable
class ProceduralStoreProtocol(Protocol):
    """Procedural Memory 持久化协议（Skill 定义）。

    方法集对齐 ``agent_runtime.procedural_memory.ProceduralStore`` 抽象契约。
    """

    async def save(self, entry: Any, *, tenant_id: str = _TENANT_UNSET) -> None:
        """保存 Skill 定义（同租户内 name + version 覆盖）。"""
        ...

    async def load(
        self, name: str, version: str | None = None, *, tenant_id: str = _TENANT_UNSET
    ) -> Any:
        """加载本租户 Skill 定义；version=None 时返回最新 stable 版本。"""
        ...

    async def list_all(self, *, tenant_id: str = _TENANT_UNSET) -> list[Any]:
        """列出本租户所有 Skill 定义。"""
        ...

    async def list_by_name(self, name: str, *, tenant_id: str = _TENANT_UNSET) -> list[Any]:
        """列出本租户某 Skill 的所有版本。"""
        ...

    async def delete(
        self, name: str, version: str, *, tenant_id: str = _TENANT_UNSET
    ) -> bool:
        """删除本租户 Skill 定义。"""
        ...


__all__ = ["EpisodicStoreProtocol", "ProceduralStoreProtocol"]
