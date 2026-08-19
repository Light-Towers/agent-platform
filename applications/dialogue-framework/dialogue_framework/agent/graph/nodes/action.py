"""action 节点：动作执行。

根据 Action.name 分发执行：
- answer: 直接返回文本
- search: 调用检索器获取知识
- flow: 推进 Flow 执行
- error: 返回错误信息
- session: 会话控制（结束/切换）
"""

from typing import Any

from agent_core.logging import get_logger

from dialogue_framework.policies.base_policy import Action

logger = get_logger(__name__)


async def action(state: dict[str, Any]) -> dict[str, Any]:
    act: Action | None = state.get("action")
    if act is None:
        return {"action_result": "", "action_type": "none"}

    handler = _HANDLERS.get(act.name, _handle_answer)
    result = await handler(act, state)
    logger.debug("action executed: name=%s result_len=%d", act.name, len(result))
    return {"action_result": result, "action_type": act.name}


async def _handle_answer(act: Action, state: dict[str, Any]) -> str:
    return act.params.get("text", "")


async def _handle_search(act: Action, state: dict[str, Any]) -> str:
    query = act.params.get("query", state.get("user_message", ""))
    retriever = state.get("retriever")
    if retriever is None:
        return ""
    try:
        docs = await retriever.retrieve(query, k=4)
    except Exception:
        logger.exception("search action failed: query=%s", query)
        return ""
    return "\n".join(doc.get("content", "") for doc in docs)


async def _handle_flow(act: Action, state: dict[str, Any]) -> str:
    return act.params.get("text", "")


async def _handle_error(act: Action, state: dict[str, Any]) -> str:
    return act.params.get("text", "发生错误，请稍后重试。")


async def _handle_session(act: Action, state: dict[str, Any]) -> str:
    return act.params.get("text", "")


_HANDLERS = {
    "answer": _handle_answer,
    "search": _handle_search,
    "flow": _handle_flow,
    "error": _handle_error,
    "session": _handle_session,
}
