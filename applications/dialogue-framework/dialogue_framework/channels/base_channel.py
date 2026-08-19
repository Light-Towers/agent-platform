"""BaseChannel：渠道基类（send/receive）。"""

from abc import ABC, abstractmethod
from typing import Any


class BaseChannel(ABC):
    """渠道基类：统一 send/receive 接口。"""

    def __init__(self, name: str = "base") -> None:
        self.name = name

    @abstractmethod
    async def send(self, message: str, **kwargs: Any) -> None:
        """发送消息到渠道。"""

    @abstractmethod
    async def receive(self, **kwargs: Any) -> str:
        """从渠道接收消息。"""

    async def close(self) -> None:
        """关闭渠道（可选覆写）。"""
