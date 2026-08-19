"""JsonStore：开发零依赖实现（JSON 文件持久化 Tracker）。"""

import json
from pathlib import Path

from dialogue_framework.core.tracker import Tracker


class JsonStore:
    def __init__(self, base_dir: str = ".dialogue_framework_store") -> None:
        self._base = Path(base_dir)
        self._base.mkdir(parents=True, exist_ok=True)

    def _path(self, session_id: str) -> Path:
        return self._base / f"{session_id}.json"

    async def save_tracker(self, tracker: Tracker) -> None:
        self._path(tracker.session_id).write_text(
            json.dumps(tracker.to_dict(), ensure_ascii=False), encoding="utf-8"
        )

    async def load_tracker(self, session_id: str) -> Tracker | None:
        path = self._path(session_id)
        if not path.exists():
            return None
        return Tracker.from_dict(json.loads(path.read_text(encoding="utf-8")))
