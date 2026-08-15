"""BasePolicy：策略基类与 Action 定义。"""

from typing import Any, Protocol


class Action:
    def __init__(self, name: str, params: dict[str, Any] | None = None) -> None:
        self.name = name
        self.params = params or {}


class BasePolicy(Protocol):
    async def predict(self, state: dict[str, Any]) -> list[Action]: ...
