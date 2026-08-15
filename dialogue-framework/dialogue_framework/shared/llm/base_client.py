"""LLM 客户端基类协议。"""

from typing import Any, Protocol


class BaseChatClient(Protocol):
    """LLM 对话客户端协议。"""

    async def ainvoke(self, *args: Any, **kwargs: Any) -> Any: ...

    def with_structured_output(self, schema: Any) -> Any: ...
