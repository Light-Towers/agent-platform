"""InspectProxy：inspect 代理渠道（调试/检查用）。"""

from typing import Any

from agent_core.logging import get_logger

from dialogue_framework.channels.base_channel import BaseChannel

logger = get_logger(__name__)


class InspectProxy(BaseChannel):
    """inspect 代理渠道：转发消息到目标渠道并记录交互日志。"""

    def __init__(self, target: BaseChannel) -> None:
        super().__init__(name="inspect")
        self._target = target
        self._history: list[dict[str, str]] = []

    async def send(self, message: str, **kwargs: Any) -> None:
        logger.debug("inspect send via %s: %s", self._target.name, message[:100])
        await self._target.send(message, **kwargs)
        self._history.append({"direction": "send", "message": message})

    async def receive(self, **kwargs: Any) -> str:
        result = await self._target.receive(**kwargs)
        logger.debug("inspect receive via %s: %s", self._target.name, result[:100])
        self._history.append({"direction": "receive", "message": result})
        return result

    @property
    def history(self) -> list[dict[str, str]]:
        return list(self._history)

    def clear_history(self) -> None:
        self._history.clear()

    async def close(self) -> None:
        await self._target.close()
