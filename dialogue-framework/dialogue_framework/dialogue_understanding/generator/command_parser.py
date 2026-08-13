"""命令解析器：将 LLM 输出解析为命令列表。"""

import json
from typing import Any


def parse_commands(text: str) -> list[dict[str, Any]]:
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "commands" in data:
            return data["commands"]
        return [data]
    except json.JSONDecodeError:
        return [{"type": "answer", "params": {"text": text}}]
