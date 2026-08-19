"""SocketIOChannel：WebSocket 实时双向渠道。"""

from typing import Any

from agent_core.logging import get_logger

from dialogue_framework.channels.base_channel import BaseChannel

logger = get_logger(__name__)


class SocketIOChannel(BaseChannel):
    """SocketIO 渠道：WebSocket 实时双向通信。"""

    def __init__(self, host: str = "localhost", port: int = 8002) -> None:
        super().__init__(name="socketio")
        self._host = host
        self._port = port
        self._sio = None
        self._last_message: str = ""

    async def connect(self) -> None:
        try:
            import socketio

            self._sio = socketio.AsyncClient()
            await self._sio.connect(f"http://{self._host}:{self._port}")
            self._sio.on("response", self._on_response)
        except ImportError:
            logger.warning("python-socketio not installed, SocketIOChannel degraded")

    async def _on_response(self, data: dict[str, Any]) -> None:
        self._last_message = data.get("answer", "")

    async def send(self, message: str, **kwargs: Any) -> None:
        if self._sio is not None:
            await self._sio.emit("query", {"query": message, "session_id": kwargs.get("session_id", "default")})

    async def receive(self, **kwargs: Any) -> str:
        return self._last_message

    async def close(self) -> None:
        if self._sio is not None:
            await self._sio.disconnect()
            self._sio = None
