"""BaseStore Protocol：对话 Tracker 存储可插拔接口。"""

from typing import Protocol

from dialogue_framework.core.tracker import Tracker


class BaseStore(Protocol):
    """Tracker 存储协议。"""

    async def save_tracker(self, tracker: Tracker) -> None: ...

    async def load_tracker(self, session_id: str) -> Tracker | None: ...
