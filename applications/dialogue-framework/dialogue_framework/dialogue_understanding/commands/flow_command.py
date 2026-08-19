"""FlowCommand：Flow 调用/跳转命令。"""

from dataclasses import dataclass

from dialogue_framework.dialogue_understanding.commands.base import BaseCommand


@dataclass
class FlowCommand(BaseCommand):
    name: str = "flow"

    async def execute(self, tracker) -> dict:
        return {"type": "flow", "flow_id": self.params.get("flow_id"), "step": self.params.get("step", 0)}
