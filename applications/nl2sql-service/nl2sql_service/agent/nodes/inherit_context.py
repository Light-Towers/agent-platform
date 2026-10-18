"""inherit_context 节点：多轮上下文继承入口（§5.13 M1/M2/M3/M4）。

位置在 extract_keywords 之前：继承要在召回与生成**之前**完成（M3），否则
指代/时间追问会被当独立问题重解。

四条契约的落点：

- **M1**：不传 session_id ⇒ 本节点返回 {}（零 state 变更），单轮行为与现状
  逐字节一致；有 session_id 才读库。
- **M2**：只继承四元组（时间窗/实体/候选表/已生成 SQL），不碰 retrieved_info
  大文本（随 schema 漂移快速 stale 且每轮 prompt 膨胀）。
- **M3**：指代/时间替换分型，产出 `effective_query`（召回/生成用）与
  `substitutions`（trace 用）；**原始 query 不改写**——trace 要能看前后。
- **M4**：按 datasource_id 作用域读会话；换源 = 另一行 = 不继承（跨源实体
  串味比不继承更糟）。

meta 库不可用（无 meta_repository / 002 未应用）时静默跳过——缺表不是启动
故障，只是没有多轮继承（与 table_stats 同理）。
"""

from __future__ import annotations

from typing import Any

from agent_core.logging import get_logger

from nl2sql_service.agent.context import DataAgentContext
from nl2sql_service.services.query_rewriter import apply_inheritance

logger = get_logger(__name__)


async def inherit_context(state: dict[str, Any]) -> dict[str, Any]:
    session_id = (state.get("session_id") or "").strip()
    # M1：无 session_id = 单轮，零变更返回（逐字节一致底线）
    if not session_id:
        return {"turn": 1}

    ctx: DataAgentContext | None = state.get("context")
    meta = getattr(ctx, "meta_repository", None) if ctx is not None else None
    datasource_id = state.get("datasource_id", "")
    tenant_id = state.get("tenant_id", "")
    workspace_id = state.get("workspace_id", "")

    if meta is None:
        return {"turn": 1}

    try:
        session = await meta.get_session(session_id, datasource_id, tenant_id=tenant_id, workspace_id=workspace_id)
    except Exception:  # noqa: BLE001 - 002 未应用/库不可用都不该阻断查询
        logger.info("session load failed（002 未应用？），本轮按单轮处理", exc_info=True)
        return {"turn": 1}

    if not session:
        return {"turn": 1}

    prev_turn = int(session.get("turn") or 0)
    quadruple = session.get("quadruple") or {}
    if not isinstance(quadruple, dict):
        quadruple = {}

    effective, substitutions = apply_inheritance(state.get("query", ""), quadruple)
    out: dict[str, Any] = {
        "turn": prev_turn + 1,
        "inherit_quadruple": quadruple,
        "substitutions": substitutions,
    }
    # 仅在有改写时设 effective_query；消费节点 `effective_query or query` 回落
    if effective != state.get("query", ""):
        out["effective_query"] = effective
    return out
