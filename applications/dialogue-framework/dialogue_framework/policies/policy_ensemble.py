"""PolicyEnsemble：策略集成（优先级/投票）。"""

from typing import Any

from dialogue_framework.policies.base_policy import Action


class PolicyEnsemble:
    def __init__(self, policies: list, mode: str = "priority") -> None:
        self._policies = policies
        self._mode = mode

    async def predict(self, state: dict[str, Any]) -> list[Action]:
        all_actions: list[Action] = []
        for policy in self._policies:
            actions = await policy.predict(state)
            if actions and self._mode == "priority":
                return actions
            all_actions.extend(actions)
        return all_actions
