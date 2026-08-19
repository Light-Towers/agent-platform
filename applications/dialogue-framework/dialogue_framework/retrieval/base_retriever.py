"""BaseRetriever Protocol：检索可插拔接口抽象。"""

from typing import Protocol


class BaseRetriever(Protocol):
    """检索协议。生产实现：PgvectorRetriever。"""

    async def retrieve(self, query: str, k: int = 4) -> list[dict]: ...
