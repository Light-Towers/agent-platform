"""recall_example 节点：NL→SQL 范例召回（A 方案 Stage ②）。

按问题相似度从范例库（004 的 nl2sql_example_info）召回 top-k 历史问答对，
注入生成期 few-shot。embedding 复用 extract_keywords 算好的
`state["query_embedding"]`（P0-11⑤：多路召回共享一次向量化）。

metric_config 路径（直调节点）不带范例——范例库是迁移/持续训练的产物，
配置直调本来就不经过元知识库，与 recall_relation 的 metric_config 分支同构。
"""

from typing import Any

from agent_core.logging import get_logger

from nl2sql_service.agent.context import DataAgentContext

logger = get_logger(__name__)


async def recall_example(state: dict[str, Any]) -> dict[str, Any]:
    ctx: DataAgentContext | None = state.get("context")
    # 未装配（004 未应用/老部署/单测）：静默空召回——缺 few-shot 不阻断查询
    if ctx is None or ctx.example_repository is None:
        return {"examples": []}

    embedding: list[float] | None = state.get("query_embedding")
    if embedding is None:
        return {"examples": []}

    # 作用域过滤（D8 摘键后）：tenant/datasource 两列恒过滤（空值匹配 '' 行）；
    # workspace 不再参与召回过滤——元知识全企业共享（006，2026-10-23）
    filters = (
        ("tenant_id", state.get("tenant_id", "")),
        ("datasource_id", state.get("datasource_id", "")),
    )
    try:
        examples = await ctx.example_repository.recall(
            state.get("keywords", []),
            embedding=embedding,
            top_k=state.get("example_top_k", 3),
            score_margin=state.get("example_score_margin", 0.0),
            filters=filters,
        )
    except Exception:  # noqa: BLE001 - 004 未应用（缺表）/库抖动都只降级空召回
        logger.warning("example recall failed, few-shot disabled for this query", exc_info=True)
        return {"examples": []}
    return {"examples": examples}
