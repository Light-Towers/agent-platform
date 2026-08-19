"""LLM 生成器：复用 shared/llm/langchain_client 生成命令。"""

from typing import Any

from dialogue_framework.dialogue_understanding.generator.command_parser import parse_commands
from dialogue_framework.dialogue_understanding.generator.prompt_builder import build_prompt
from dialogue_framework.shared.llm.langchain_client import build_chat_model


async def generate_commands(user_message: str, tracker) -> list[dict[str, Any]]:
    llm = build_chat_model()
    prompt = build_prompt(user_message, tracker)
    if llm is None:
        return [{"type": "answer", "params": {"text": user_message}}]
    from langchain_core.messages import HumanMessage

    resp = await llm.ainvoke([HumanMessage(content=prompt)])
    return parse_commands(resp.content if hasattr(resp, "content") else str(resp))
