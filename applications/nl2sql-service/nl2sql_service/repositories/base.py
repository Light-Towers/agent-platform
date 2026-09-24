"""BaseRepository：仓储协议。"""

from typing import Any, Protocol


class BaseRepository(Protocol):
    """仓储协议：统一召回接口。"""

    async def recall(self, keywords: list[str], embedding: list[float] | None = None, top_k: int = 10) -> list[dict[str, Any]]: ...
