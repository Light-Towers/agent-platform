"""understand 节点：命令解析 + Flow 加载 + 栈管理。"""

from typing import Any

from dialogue_framework.dialogue_understanding.processor.command_processor import CommandProcessor


async def understand(state: dict[str, Any]) -> dict[str, Any]:
    tracker = state["tracker"]
    user_message = state["user_message"]
    processor = CommandProcessor()
    commands = await processor.process(user_message, tracker)
    intent = commands[0].get("type") if commands else None
    return {"commands": commands, "intent": intent}
