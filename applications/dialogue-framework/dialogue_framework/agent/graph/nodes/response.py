"""response 节点：NLG 生成。

依赖 nlg/nlg_generator，将 action_result 经模板渲染 + LLM 重写为自然语言响应。
检测槽位缺失时设置 need_clarification=True，条件边回退 understand 追问。
"""

from typing import Any

from agent_core.logging import get_logger

from dialogue_framework.nlg.nlg_generator import NLGGenerator

logger = get_logger(__name__)

_nlg = NLGGenerator()


async def response(state: dict[str, Any]) -> dict[str, Any]:
    action_result = state.get("action_result", "")
    action_type = state.get("action_type", "answer")
    tracker = state.get("tracker")

    template_name = _TEMPLATE_MAP.get(action_type, "default")
    rephrase_enabled = bool(state.get("rephrase_enabled", False))

    try:
        text = await _nlg.generate(
            template_name=template_name,
            text=action_result,
            rephrase_enabled=rephrase_enabled,
        )
    except Exception:
        logger.exception("NLG generation failed, fallback to raw result")
        text = action_result

    need_clarification = _check_slot_missing(tracker)
    return {"response": text, "need_clarification": need_clarification}


def _check_slot_missing(tracker: Any) -> bool:
    if tracker is None:
        return False
    slots = getattr(tracker, "slots", {})
    for slot in slots.values():
        if getattr(slot, "required", False) and not getattr(slot, "filled", False):
            return True
    return False


_TEMPLATE_MAP = {
    "answer": "default",
    "search": "knowledge",
    "flow": "flow",
    "error": "error",
    "session": "session",
}
