"""MessageProcessor：消息处理器（用户消息 → DialogueState → 图执行 → 响应）。

供 API/Channel 层调用，封装会话查找、图执行、响应格式化。
"""

from typing import Any

from agent_core.logging import get_logger

from dialogue_framework.agent.agent import DialogueAgent

logger = get_logger(__name__)


class MessageProcessor:
    """消息处理器：绑定 Agent，处理入站消息并返回结构化响应。"""

    def __init__(self, agent: DialogueAgent | None = None) -> None:
        self._agent = agent or DialogueAgent()

    async def process(self, session_id: str, message: str, **kwargs: Any) -> dict[str, Any]:
        if not message or not message.strip():
            return {"response": "", "error": "empty_message"}

        logger.info("process message: session=%s len=%d", session_id, len(message))
        result = await self._agent.chat(session_id, message, **kwargs)

        return {
            "session_id": session_id,
            "response": result.get("response", ""),
            "intent": result.get("intent"),
            "action_type": result.get("action_type"),
            "guard_passed": result.get("guard_passed", True),
            "fallback": result.get("fallback", False),
        }

    async def process_batch(
        self, messages: list[dict[str, str]], **kwargs: Any
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for msg in messages:
            session_id = msg.get("session_id", "default")
            text = msg.get("message", "")
            result = await self.process(session_id, text, **kwargs)
            results.append(result)
        return results
