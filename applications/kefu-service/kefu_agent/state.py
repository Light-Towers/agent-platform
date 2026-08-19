"""LangGraph State：对应 legacy Tracker。

legacy Tracker → LangGraph State 语义映射：
- Tracker.slots → State.slots
- Tracker.flow_stack → State.flow_state
- Tracker.history → State.history
"""

from __future__ import annotations

from typing import Any, TypedDict


class KefuState(TypedDict, total=False):
    """kefu-service 对话状态。"""

    user_message: str
    session_id: str
    tenant_id: str

    intent: str | None
    slots: dict[str, Any]
    flow_state: str | None
    response: str | None
    history: list[dict[str, str]]
