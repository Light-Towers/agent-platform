"""Slot：槽位。"""

from dataclasses import dataclass


@dataclass
class Slot:
    name: str
    value: str | None = None
    filled: bool = False

    def fill(self, value: str) -> None:
        self.value = value
        self.filled = True

    def reset(self) -> None:
        self.value = None
        self.filled = False
