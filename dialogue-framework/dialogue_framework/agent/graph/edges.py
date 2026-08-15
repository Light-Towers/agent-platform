"""条件边：guard 拒绝→回退 policy；response 需追问→回退 understand。"""

from typing import Any

from langgraph.graph import END


def route_after_guard(state: dict[str, Any]) -> str:
    if not state.get("guard_passed", True):
        return "policy"
    return "response"


def route_after_response(state: dict[str, Any]) -> str:
    if state.get("need_clarification", False):
        return "understand"
    return END
