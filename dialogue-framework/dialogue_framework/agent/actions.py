"""Action：动作定义（非图节点，对话入口辅助）。"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Action:
    name: str
    params: dict[str, Any] = field(default_factory=dict)
