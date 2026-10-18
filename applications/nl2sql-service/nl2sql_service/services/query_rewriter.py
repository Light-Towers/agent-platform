"""多轮查询改写（§5.13 M3）：指代与时间替换分型，**不改写用户原始 query**。

两类继承混作一团会把"换时间"错实现成"换实体"；改写原始 query 则 trace 失真、
无法复盘。故本模块只做**可观测的增量**：产出 `effective_query`（给召回/生成用）
与 `substitutions`（trace 用），原始 `query` 一个字节都不动。

- **指代**（"上述/那些/它们/这些"）：命中且四元组有实体 ⇒ 把上文实体显式补进
  effective_query（"上文实体：…"），让模型有承接对象，而不是当独立问题重解。
- **时间**（"那上个月呢/上个月/这个月/最近"）：命中且四元组有时间窗 ⇒ 把上文
  时间窗补进 effective_query，由模型结合 date_info 做真实偏移（改写器不算日期，
  避免把"换时间"错算成具体月份）。

真正的日期偏移与实体绑定交给 LLM（它有 date_info 锚点）；本模块负责"把上文
四元组喂到模型眼前"并留下 trace 痕迹——这是 M3 要求的分型与可观测，不是 NLU。
"""

from __future__ import annotations

import re
from typing import Any

#: 指代词（承接上文实体）
_REFERENT_MARKERS = ("上述", "那些", "它们", "这些", "上个问题", "前面的")
#: 时间迁移词（换时间窗，常见追问"那上个月呢"）
_TIME_MARKERS = ("上个月", "这个月", "下个月", "上月", "本月", "去年", "今年", "最近", "那上周", "上周")


def detect_substitution_types(query: str) -> list[str]:
    """识别本轮 query 命中的继承类型（referent / time），用于分型与 trace。"""
    kinds: list[str] = []
    if any(m in query for m in _REFERENT_MARKERS):
        kinds.append("referent")
    if any(m in query for m in _TIME_MARKERS):
        kinds.append("time")
    return kinds


def apply_inheritance(query: str, quadruple: dict[str, Any] | None) -> tuple[str, list[str]]:
    """按四元组把上文上下文补进 query；返回 (effective_query, substitutions)。

    无四元组或无命中 ⇒ effective == query、substitutions == []（单轮逐字节一致）。
    """
    if not quadruple:
        return query, []
    kinds = detect_substitution_types(query)
    if not kinds:
        return query, []

    hints: list[str] = []
    applied: list[str] = []
    if "referent" in kinds:
        entities = [str(e) for e in (quadruple.get("entities") or []) if e]
        if entities:
            hints.append("上文实体：" + "、".join(entities))
            applied.append("referent")
    if "time" in kinds:
        window = (quadruple.get("time_window") or "").strip()
        if window:
            hints.append(f"上文时间窗：{window}")
            applied.append("time")
    if not applied:
        return query, []
    effective = f"{query}（{'；'.join(hints)}）"
    return effective, applied


__all__ = ["apply_inheritance", "detect_substitution_types", "extract_time_window"]


#: 显式时间窗（best-effort，供四元组 time_window 落库）：YYYY年M月 / YYYY-MM / M月
_TIME_WINDOW_RES: tuple[re.Pattern, ...] = (
    re.compile(r"(20\d{2}|19\d{2})\s*年\s*(\d{1,2})\s*月"),
    re.compile(r"(20\d{2}|19\d{2})-(\d{1,2})(?!\d)"),
    re.compile(r"(?<![\d年])(\d{1,2})\s*月(?![\d])"),
)


def extract_time_window(query: str) -> str:
    """从 query 抽取显式时间窗（best-effort）；抽不到返回空串。

    只认字面年月，不做自然语言推断——推不准就把 time_window 留空，让下一轮
    继承退回"只有 date_info 锚点"，比存一个错的窗更安全（错窗会让"那上个月呢"
    继承到错误月份）。
    """
    for rx in _TIME_WINDOW_RES:
        m = rx.search(query or "")
        if m:
            parts = [p for p in m.groups() if p]
            if len(parts) == 2:
                return f"{parts[0]}-{int(parts[1]):02d}"
            return f"{int(parts[0]):02d}月"
    return ""
