"""policy 节点：策略投票 → Action。"""

from typing import Any

from dialogue_framework.policies.base_policy import Action


async def policy(state: dict[str, Any]) -> dict[str, Any]:
    ensemble = state.get("policy_ensemble")
    if ensemble is not None:
        actions = await ensemble.predict(state)
        if actions:
            return {"action": actions[0]}

    commands = state.get("commands", [])
    if commands:
        cmd = commands[0]
        action = Action(name=cmd.get("type", "answer"), params=cmd.get("params", {}))
        return {"action": action}
    return {"action": Action(name="answer", params={"text": "抱歉，我没理解。"})}
