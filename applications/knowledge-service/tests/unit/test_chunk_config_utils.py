# -*- coding: utf-8 -*-
"""切分参数默认值与校验（纯函数，零外部依赖）。

钉四件事：
1. None/部分 dict 补全到全局默认 title/2000/0.10；
2. 三字段各自非法值被拒（枚举/整数/数值/越界）；
3. 边界值 500/2000、ratio 0/0.5 通过；
4. 重叠字符数换算 round(max×ratio) 正确。
"""
from __future__ import annotations

import pytest

from knowledge_service.utils.chunk_config_utils import (
    DEFAULT_CHUNK_CONFIG,
    normalize_chunk_config,
    overlap_chars,
)


def test_none_and_partial_fill_defaults() -> None:
    assert normalize_chunk_config(None) == DEFAULT_CHUNK_CONFIG
    assert normalize_chunk_config({"split_strategy": "char"}) == {
        "split_strategy": "char",
        "max_content_length": 2000,
        "chunk_overlap_ratio": 0.10,
    }
    assert normalize_chunk_config({}) == DEFAULT_CHUNK_CONFIG


def test_boundary_values_pass() -> None:
    assert normalize_chunk_config({"max_content_length": 500, "chunk_overlap_ratio": 0.0})
    assert normalize_chunk_config({"max_content_length": 2000, "chunk_overlap_ratio": 0.5})
    for strat in ("title", "char", "line"):
        assert normalize_chunk_config({"split_strategy": strat})["split_strategy"] == strat


@pytest.mark.parametrize("bad", [
    {"split_strategy": "bogus"},
    {"max_content_length": 499},
    {"max_content_length": 2001},
    {"max_content_length": "2000"},   # 非整数（字符串）
    {"max_content_length": True},     # bool 不算整数
    {"chunk_overlap_ratio": -0.1},
    {"chunk_overlap_ratio": 0.6},
    {"chunk_overlap_ratio": "0.1"},   # 非数值（字符串）
])
def test_invalid_values_rejected(bad: dict) -> None:
    with pytest.raises(ValueError):
        normalize_chunk_config(bad)


def test_overlap_chars_rounding() -> None:
    assert overlap_chars(2000, 0.10) == 200
    assert overlap_chars(500, 0.5) == 250
    assert overlap_chars(1000, 0.0) == 0
