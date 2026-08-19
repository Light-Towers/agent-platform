"""DialogueState：对话图状态。"""

from typing import Any, TypedDict


class DialogueState(TypedDict, total=False):
    tracker: Any
    user_message: str
    intent: str | None
    action: Any
    action_result: str
    action_type: str
    response: str
    commands: list[dict[str, Any]]
    guard_passed: bool
    guard_reason: str
    need_clarification: bool
    retriever: Any
    rephrase_enabled: bool
