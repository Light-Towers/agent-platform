"""ModelStorage：模型存储，不依赖课程栈/Rasa。

JSON 文件存储，支持 save/load/list/delete。
"""

import json
from pathlib import Path

from agent_core.logging import get_logger

logger = get_logger(__name__)

_DEFAULT_DIR = Path(".models") / "dialogue_framework"


class ModelStorage:
    """模型存储：JSON 文件持久化。"""

    def __init__(self, base_dir: str | Path | None = None) -> None:
        self._base_dir = Path(base_dir) if base_dir else _DEFAULT_DIR

    def save(self, name: str, data: dict) -> Path:
        path = self._base_dir / f"{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.debug("model saved: %s", path)
        return path

    def load(self, name: str) -> dict | None:
        path = self._base_dir / f"{name}.json"
        if not path.exists():
            return None
        with path.open(encoding="utf-8") as f:
            return json.load(f)

    def list_models(self) -> list[str]:
        if not self._base_dir.exists():
            return []
        return sorted(p.stem for p in self._base_dir.glob("*.json"))

    def delete(self, name: str) -> bool:
        path = self._base_dir / f"{name}.json"
        if path.exists():
            path.unlink()
            return True
        return False
