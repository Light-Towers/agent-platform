"""SessionCommand：会话控制命令（开始/结束/重置）。"""

from dataclasses import dataclass

from dialogue_framework.dialogue_understanding.commands.base import BaseCommand


@dataclass
class SessionCommand(BaseCommand):
    name: str = "session"

    async def execute(self, tracker) -> dict:
        action = self.params.get("action", "reset")
        if action == "reset":
            tracker.slots.clear()
            tracker.events.clear()
        return {"type": "session", "action": action}
