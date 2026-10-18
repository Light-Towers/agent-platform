"""prompt 加载与渲染：一次读盘 + 安全占位符替换。

为什么单独成模块（2026-10-18 审计 A/B 组）：

1. `_load_prompt()` 此前在 generate/correct 里各写一份且**每次调用都读盘**（每请求 2 次 IO）；
   这里用 `lru_cache` 收敛成一次。
2. 此前直接用 `str.format()`：prompt 模板一旦出现字面花括号（JSON 示例、SQL 里的 `{...}`），
   会抛 `KeyError` 把整个请求打成 500。`format_map` + `__missing__` 让未知占位符原样保留，
   渲染失败不再升级为请求失败。
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_PROMPT_DIR = Path(__file__).resolve().parents[2] / "prompts"


class _SafeDict(dict):
    """未知占位符原样保留，不抛 KeyError。"""

    def __missing__(self, key: str) -> str:  # noqa: D105 - 语义即返回值
        return "{" + key + "}"


@lru_cache(maxsize=None)
def load_prompt(name: str, fallback: str = "") -> str:
    """按名加载 prompt 文件；缺失时用 fallback（保持原有降级行为）。"""
    path = _PROMPT_DIR / name
    if path.exists():
        return path.read_text(encoding="utf-8")
    return fallback


def render(template: str, **values: Any) -> str:
    """安全渲染：未知占位符保留原样，不因模板漂移抛异常。"""
    return template.format_map(_SafeDict(values))


def json_block(value: Any) -> str:
    """把召回结果渲染成 prompt 可读的 JSON 块；空值给显式占位而不是空串。"""
    if not value:
        return "（无）"
    return json.dumps(value, ensure_ascii=False)
