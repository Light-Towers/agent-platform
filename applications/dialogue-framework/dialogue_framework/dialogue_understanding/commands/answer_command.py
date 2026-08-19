"""AnswerCommand：直接回复命令。"""

from dataclasses import dataclass

from dialogue_framework.dialogue_understanding.commands.base import BaseCommand


@dataclass
class AnswerCommand(BaseCommand):
    name: str = "answer"

    async def execute(self, tracker) -> dict:
        return {"type": "answer", "text": self.params.get("text", "")}
