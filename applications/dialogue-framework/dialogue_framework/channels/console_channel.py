"""ConsoleChannel：命令行交互渠道。"""

import sys
from typing import Any

from dialogue_framework.channels.base_channel import BaseChannel


class ConsoleChannel(BaseChannel):
    """Console 渠道：stdin/stdout 交互。"""

    def __init__(self, prompt: str = "user> ") -> None:
        super().__init__(name="console")
        self._prompt = prompt

    async def send(self, message: str, **kwargs: Any) -> None:
        sys.stdout.write(f"bot> {message}\n")
        sys.stdout.flush()

    async def receive(self, **kwargs: Any) -> str:
        try:
            line = input(self._prompt)
            return line.strip()
        except EOFError:
            return ""

    async def receive_stream(self, stream: Any = None) -> str:
        stream = stream or sys.stdin
        line = stream.readline()
        return line.strip()
