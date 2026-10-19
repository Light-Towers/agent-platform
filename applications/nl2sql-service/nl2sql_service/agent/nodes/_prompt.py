"""prompt 加载与渲染：一次读盘 + 安全占位符替换。

为什么单独成模块（2026-10-18 审计 A/B 组）：

1. `_load_prompt()` 此前在 generate/correct 里各写一份且**每次调用都读盘**（每请求 2 次 IO）；
   这里用 `lru_cache` 收敛成一次。
2. 占位符替换刻意**不用** `str.format` 语义（2026-10-19 #108 修订）：模板一旦出现
   字面花括号（JSON few-shot、SQL 片段），`format`/`format_map` 会把 `{"sql": ...}`
   当格式说明符抛 `ValueError`/`KeyError`——`__missing__` 只救"合法未知字段名"，
   救不了字面花括号。改为白名单槽位正则替换：字面花括号与未知槽位一律原样保留，
   渲染永不因模板内容抛异常。
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

_PROMPT_DIR = Path(__file__).resolve().parents[2] / "prompts"

#: 已知槽位白名单——与 prompts/generate_sql.prompt、correct_sql.prompt 实际槽位一致。
#: 新增槽位必须同步这里（漏了只会原样保留，不会炸，但 prompt 会缺内容）。
_SLOT_RE = re.compile(r"\{(query|table_infos|metric_infos|date_info|db_info|sql|error)\}")


@lru_cache(maxsize=None)
def load_prompt(name: str, fallback: str = "") -> str:
    """按名加载 prompt 文件；缺失时用 fallback（保持原有降级行为）。"""
    path = _PROMPT_DIR / name
    if path.exists():
        return path.read_text(encoding="utf-8")
    return fallback


def render(template: str, **values: Any) -> str:
    """安全渲染：只替换白名单槽位；字面花括号与未知槽位原样保留。"""
    return _SLOT_RE.sub(lambda m: str(values.get(m.group(1), "")), template)


def json_block(value: Any) -> str:
    """把召回结果渲染成 prompt 可读的 JSON 块；空值给显式占位而不是空串。"""
    if not value:
        return "（无）"
    return json.dumps(value, ensure_ascii=False)
