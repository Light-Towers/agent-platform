"""policy 节点：策略投票 → Action。"""

from typing import Any

from dialogue_framework.policies.base_policy import Action


async def policy(state: dict[str, Any]) -> dict[str, Any]:
    commands = state.get("commands", [])
    if commands:
        cmd = commands[0]
        action = Action(name=cmd.get("type", "answer"), params=cmd.get("params", {}))
        return {"action": action}
    return {"action": Action(name="answer", params={"text": "抱歉，我没理解。"})}
