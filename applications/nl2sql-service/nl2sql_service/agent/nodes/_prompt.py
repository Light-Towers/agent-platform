"""prompt 加载与渲染：一次读盘 + 安全占位符替换。

为什么单独成模块（2026-10-18 审计 A/B 组）：

1. `_load_prompt()` 此前在 generate/correct 里各写一份且**每次调用都读盘**（每请求 2 次 IO）；
   这里用**带文件身份的缓存**收敛成一次（#116：`lru_cache` 只按参数名缓存，改 prompt
   文件不重启不生效——热改能力被悄悄取消；缓存键含 mtime_ns+size 后，内容变才重读）。
2. 占位符替换刻意**不用** `str.format` 语义（2026-10-19 #108 修订）：模板一旦出现
   字面花括号（JSON few-shot、SQL 片段），`format`/`format_map` 会把 `{"sql": ...}`
   当格式说明符抛 `ValueError`/`KeyError`——`__missing__` 只救"合法未知字段名"，
   救不了字面花括号。改为白名单槽位正则替换：字面花括号与未知槽位一律原样保留，
   渲染永不因模板内容抛异常。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_PROMPT_DIR = Path(__file__).resolve().parents[2] / "prompts"

#: 已知槽位白名单——generate_sql / correct_sql / answer 三个 prompt 文件与其
#: render 调用点实际槽位的并集。新增槽位必须同步这里（漏了只会原样保留，不会炸，
#: 但 prompt 会缺内容）。
_SLOT_RE = re.compile(
    r"\{(query|table_infos|metric_infos|relations|examples|aggregation_hint"
    r"|date_info|db_info|sql|attempted_sql|error|result_view|empty_diagnosis)\}"
)

#: prompt 文件缓存：name → ((mtime_ns, size), text)（#116）。键含文件身份 ⇒
#: 改文件即失效重读（热改恢复），不变不读（读盘仍是一次）。线程安全靠 GIL：
#: 最坏重复读一次，不会读到半截内容（read_text 原子性由 OS 保证）。
_PROMPT_CACHE: dict[str, tuple[tuple[int, int], str]] = {}


def load_prompt(name: str, fallback: str = "") -> str:
    """按名加载 prompt 文件；缺失时用 fallback（保持原有降级行为）。"""
    path = _PROMPT_DIR / name
    try:
        stat = path.stat()
    except OSError:
        return fallback
    identity = (stat.st_mtime_ns, stat.st_size)
    cached = _PROMPT_CACHE.get(name)
    if cached is not None and cached[0] == identity:
        return cached[1]
    text = path.read_text(encoding="utf-8")
    _PROMPT_CACHE[name] = (identity, text)
    return text


def render(template: str, **values: Any) -> str:
    """安全渲染：只替换白名单槽位；字面花括号与未知槽位原样保留。"""
    return _SLOT_RE.sub(lambda m: str(values.get(m.group(1), "")), template)


def json_block(value: Any) -> str:
    """把召回结果渲染成 prompt 可读的 JSON 块；空值给显式占位而不是空串。"""
    if not value:
        return "（无）"
    return json.dumps(value, ensure_ascii=False)
