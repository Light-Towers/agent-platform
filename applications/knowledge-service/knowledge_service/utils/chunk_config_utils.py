# -*- coding: utf-8 -*-
"""切分参数配置的默认值与校验（纯函数，零 KS / Mongo 依赖）。

对应主方案 plan-kb-chunking-profile-2026-11-20.md §3.1：
- 三个用户可配置项：split_strategy / max_content_length / chunk_overlap_ratio
- 默认值 title / 2000 / 0.10（用户 2026-11-21 拍板；重叠 0→10% 是已拍板的行为变更，非回归）
- 块大小范围 500–2000 已定稿；重叠比例范围 0–0.5 为暂定值（P-2 取证后可收紧）

设计纪律：
- 缺省补全（normalize 接受 None / 部分 dict），让"未传"一律落全局默认；
- 非法值抛 ValueError（带具名原因），由调用方（/upload、/collections）转 HTTP 400；
- 交叉约束只做"与单块自洽"的部分（ratio < 1.0）；合并阶段 max 截断属切分实现（刀 2），
  不在本模块校验——见主方案 §3.1 F-2。
"""
from __future__ import annotations

from typing import Any, Dict

#: 全局默认（与 state.py graph_default_state 的切分字段保持一致）
DEFAULT_CHUNK_CONFIG: Dict[str, Any] = {
    "split_strategy": "title",
    "max_content_length": 2000,
    "chunk_overlap_ratio": 0.10,
}

VALID_STRATEGIES = ("title", "char", "line")
MAX_MIN = 500   # 对应 node_document_split.py:23 MIN_CONTENT_LENGTH，块大小下限（已定稿）
MAX_MAX = 2000  # 用户拍板的块大小上限（已定稿）
OVERLAP_RATIO_MIN = 0.0
OVERLAP_RATIO_MAX = 0.5  # 暂定值，P-2 取证后可收紧


def overlap_chars(max_content_length: int, chunk_overlap_ratio: float) -> int:
    """把重叠比例换算成字符数（state 存字符数供切分器用）。"""
    return round(max_content_length * chunk_overlap_ratio)


def normalize_chunk_config(raw: Dict[str, Any] | None) -> Dict[str, Any]:
    """补全默认值 + 逐字段校验 + 交叉校验。非法抛 ValueError（具名原因）。

    :param raw: 原始配置（可能缺字段或字段为 None）；None 表示完全未传 → 全默认
    :return: 规范化后的 {split_strategy, max_content_length, chunk_overlap_ratio}
    """
    src = raw or {}
    cfg = {
        "split_strategy": src.get("split_strategy") or DEFAULT_CHUNK_CONFIG["split_strategy"],
        "max_content_length": src.get("max_content_length") or DEFAULT_CHUNK_CONFIG["max_content_length"],
        "chunk_overlap_ratio": src.get("chunk_overlap_ratio"),
    }
    if cfg["chunk_overlap_ratio"] is None:
        cfg["chunk_overlap_ratio"] = DEFAULT_CHUNK_CONFIG["chunk_overlap_ratio"]

    # 逐字段校验
    if cfg["split_strategy"] not in VALID_STRATEGIES:
        raise ValueError(
            f"split_strategy 非法: {cfg['split_strategy']!r}，应为 {VALID_STRATEGIES}"
        )
    max_len = cfg["max_content_length"]
    if isinstance(max_len, bool) or not isinstance(max_len, int):
        raise ValueError(f"max_content_length 必须为整数，收到 {max_len!r}")
    if not (MAX_MIN <= max_len <= MAX_MAX):
        raise ValueError(f"max_content_length 越界: {max_len}（应 {MAX_MIN}–{MAX_MAX}）")
    ratio = cfg["chunk_overlap_ratio"]
    if isinstance(ratio, bool) or not isinstance(ratio, (int, float)):
        raise ValueError(f"chunk_overlap_ratio 必须为数值，收到 {ratio!r}")
    if not (OVERLAP_RATIO_MIN <= ratio <= OVERLAP_RATIO_MAX):
        raise ValueError(
            f"chunk_overlap_ratio 越界: {ratio}（应 {OVERLAP_RATIO_MIN}–{OVERLAP_RATIO_MAX}）"
        )

    # 交叉约束：换算后的重叠字符数必须 < 块大小（否则 LangChain 抛 ValueError）
    if overlap_chars(max_len, ratio) >= max_len:
        raise ValueError(
            f"重叠字符数 {overlap_chars(max_len, ratio)} 必须小于块大小 {max_len}"
        )
    return cfg


__all__ = [
    "DEFAULT_CHUNK_CONFIG",
    "VALID_STRATEGIES",
    "MAX_MIN",
    "MAX_MAX",
    "OVERLAP_RATIO_MIN",
    "OVERLAP_RATIO_MAX",
    "overlap_chars",
    "normalize_chunk_config",
]
