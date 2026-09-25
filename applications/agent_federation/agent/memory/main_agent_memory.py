"""main_agent 推理流程接入类型化记忆的接线辅助（ADR-0004 阶段2 收尾）。

独立成模块以隔离 agent.main_agent 的重依赖（langgraph / llm），便于单测不触发模型配置。
所有调用均带「零行为变更」降级：无池 / 开关关闭 / 异常 → 不注入、不落库、不抛错。

隔离策略（与全局一致）：类型化记忆以 ``(tenant_id, workspace_id)`` 为复合隔离键——
``workspace_id`` 是宿主侧隔离主键，``tenant_id`` 取自请求链路 ContextVar（Phase 6
多租户，缺省 default）。agent_federation 单进程单池，一个 ``thread_id`` 即代表一个
workspace 工作空间，故调用处将 ``thread_id`` 作为 ``workspace_id`` 透传进来。

注意（跨层命名澄清，TD-E）：下游内核 ``agent_core.memory`` 的 ``recall_typed`` /
``remember_fact`` 形参与 PG/Milvus 列名仍叫 ``user_id``，这是内核通用的共享契约，
本模块调用时**所传的 ``workspace_id`` 即落在内核的 ``user_id`` 形参位上**，
二者语义等价 —— ``workspace_id`` 是 agent_federation 侧的隔离主键名，``user_id`` 是内核
存储层的通用字段名，请勿据此误以为存在双重隔离或错位落库。
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _current_tenant_id() -> str:
    """取当前请求链路的租户 ID（Phase 6 ContextVar）；不在请求上下文则回退 default。

    typed 记忆与 agent_server 共用 memories 表且按 (tenant_id, user_id) 过滤，
    不透传 tenant 会读写共享 default 桶，造成跨租户可见。
    """
    try:
        from api.context import get_tenant_context

        return get_tenant_context() or "default"
    except ImportError:  # 非 server 环境（单测直接调本模块）降级不阻断
        return "default"


async def recall_typed_context(workspace_id: str, query: str) -> str:
    """召回与当前 query 相关的类型化记忆，返回拼接进 user message 的上下文串。

    无池 / 开关关闭 / 异常 → 返回空串。隔离单位为 ``(tenant_id, workspace_id)``。
    """
    try:
        from agent.db import get_pool
        from agent.memory.semantic_memory import recall_typed

        pool = get_pool()
        if pool is None:
            return ""
        memories = await recall_typed(
            pool, workspace_id, query, tenant_id=_current_tenant_id()
        )
        if not memories:
            return ""
        lines = [f"  - [{m.memory_type.value}] {m.content}" for m in memories]
        return (
            "\n\n【相关历史记忆（仅供参考，请勿复述此标签）】\n"
            + "\n".join(lines)
        )
    except Exception as e:
        logger.warning("类型化记忆召回失败（非致命，跳过）: %s", e)
        return ""


async def remember_episodic(workspace_id: str, query: str, answer: str) -> None:
    """把本轮 (query, answer) 作为一条 episodic 记忆落库（旁路，失败不抛）。

    阶段2 收尾先以「整轮对话」直接沉淀，保证 typed 写入路径真实生效；
    LLM 结构化事实抽取（app 的 extract_memory_facts）可留待后续阶段复用。
    隔离单位为 ``(tenant_id, workspace_id)``。
    """
    try:
        from agent.db import get_pool
        from agent.memory.semantic_memory import remember_fact

        pool = get_pool()
        if pool is None:
            return
        fact = f"用户问：{query}\n助手答：{answer}"
        await remember_fact(
            pool, workspace_id, fact,
            memory_type="episodic", importance=0.5,
            tenant_id=_current_tenant_id(),
        )
    except Exception as e:
        logger.warning("类型化记忆落库失败（非致命，跳过）: %s", e)
