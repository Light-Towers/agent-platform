"""ErrorCommand：错误命令。"""

from dataclasses import dataclass

from dialogue_framework.dialogue_understanding.commands.base import BaseCommand


@dataclass
class ErrorCommand(BaseCommand):
    name: str = "error"

    async def execute(self, tracker) -> dict:
        return {"type": "error", "message": self.params.get("message", "未知错误")}
