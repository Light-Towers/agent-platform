"""RestChannel：REST HTTP 渠道。"""

from typing import Any

import httpx
from agent_core.logging import get_logger

from dialogue_framework.channels.base_channel import BaseChannel

logger = get_logger(__name__)


class RestChannel(BaseChannel):
    """REST 渠道：通过 HTTP 调用对话 API。"""

    def __init__(self, endpoint: str = "http://localhost:8001/query", timeout: float = 30.0) -> None:
        super().__init__(name="rest")
        self._endpoint = endpoint
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def send(self, message: str, **kwargs: Any) -> None:
        session_id = kwargs.get("session_id", "default")
        client = self._ensure_client()
        resp = await client.post(
            self._endpoint,
            json={"query": message, "session_id": session_id},
            timeout=self._timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        kwargs.setdefault("_last_response", data)

    async def receive(self, **kwargs: Any) -> str:
        data = kwargs.get("_last_response")
        if data is None:
            return ""
        return data.get("answer", "")

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient()
        return self._client
