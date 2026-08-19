"""FlowPolicy：Flow 策略，根据状态选择 Flow。"""

from typing import Any

from dialogue_framework.policies.base_policy import Action


class FlowPolicy:
    def __init__(self, flows: dict[str, Any]) -> None:
        self._flows = flows

    async def predict(self, state: dict[str, Any]) -> list[Action]:
        intent = state.get("intent")
        if intent and intent in self._flows:
            return [Action(name="call_flow", params={"flow_id": intent})]
        return []
