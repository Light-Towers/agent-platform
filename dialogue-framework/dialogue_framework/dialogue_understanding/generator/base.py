"""生成器基类协议。"""

from typing import Any, Protocol


class BaseGenerator(Protocol):
    async def generate(self, user_message: str, tracker) -> list[dict[str, Any]]: ...
