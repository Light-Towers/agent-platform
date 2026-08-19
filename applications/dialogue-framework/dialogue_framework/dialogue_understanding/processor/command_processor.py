"""CommandProcessor：命令分发 + 处理。"""

from typing import Any

from dialogue_framework.dialogue_understanding.commands.answer_command import AnswerCommand
from dialogue_framework.dialogue_understanding.commands.error_command import ErrorCommand
from dialogue_framework.dialogue_understanding.commands.flow_command import FlowCommand
from dialogue_framework.dialogue_understanding.commands.session_command import SessionCommand
from dialogue_framework.dialogue_understanding.commands.slot_command import SlotCommand
from dialogue_framework.dialogue_understanding.generator.llm_generator import generate_commands

_COMMAND_MAP = {
    "answer": AnswerCommand,
    "error": ErrorCommand,
    "flow": FlowCommand,
    "session": SessionCommand,
    "slot": SlotCommand,
}


class CommandProcessor:
    async def process(self, user_message: str, tracker) -> list[dict[str, Any]]:
        commands = await generate_commands(user_message, tracker)
        results = []
        for cmd in commands:
            cmd_type = cmd.get("type", "answer")
            params = cmd.get("params", {})
            cls = _COMMAND_MAP.get(cmd_type, AnswerCommand)
            command = cls(name=cmd_type, params=params)
            results.append(await command.execute(tracker))
        return results
