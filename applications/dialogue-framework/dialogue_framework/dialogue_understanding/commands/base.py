"""BaseCommand：命令基类。命令系统核心抽象。"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class BaseCommand:
    name: str
    params: dict[str, Any] = field(default_factory=dict)

    async def execute(self, tracker) -> dict[str, Any]:
        raise NotImplementedError
