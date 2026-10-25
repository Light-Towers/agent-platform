# -*- coding: utf-8 -*-
"""golden 用例集结构校验（常驻、无 LLM、无 DB）。

2026-10-19 扩集（3→22 条，issue #97）时新增。门禁跑分需要活 LLM（资源阻塞
时跑不了），但**用例集自身的完整性**不该等 LLM——本文件把「集子坏没坏」
变成每次 pytest 都查的机械判据：

1. JSON 合法 + question 非空（复用 run_golden._load_golden 的同一解析器）；
2. id 唯一（删了不复用——历史读数错位的防线，baseline 文档 §2 字段表）；
3. session 链闭合：同一 session_id 的用例 ≥2 条（孤儿链等于单轮，
   挂着 session_id 是误导；run_golden 按文件序串链）；
4. 判轴字段类型合法 + 不共轭（expect_nonempty 与 expect_empty 不得同真）。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from nl2sql_service.scripts.run_golden import _load_golden

_GOLDEN = Path(__file__).resolve().parents[1] / "golden" / "nl2sql_golden.jsonl"


@pytest.fixture(scope="module")
def cases() -> list[dict]:
    assert _GOLDEN.exists(), f"golden 文件不存在：{_GOLDEN}"
    return _load_golden(str(_GOLDEN))


def test_golden_file_parses(cases):
    assert cases, "golden 集为空"
    assert all(c.get("question", "").strip() for c in cases), "存在空 question 用例"


def test_ids_unique(cases):
    ids = [c.get("id") for c in cases if c.get("id")]
    assert len(ids) == len(set(ids)), f"id 重复：{[i for i in ids if ids.count(i) > 1]}"


def test_session_chains_closed(cases):
    """同一 session_id 必须 ≥2 条（链的意义在承接）；单条 = 孤儿。"""
    chains: dict[str, list[str]] = {}
    for c in cases:
        sid = c.get("session_id")
        if sid:
            chains.setdefault(sid, []).append(c.get("id", "?"))
    orphans = {sid: members for sid, members in chains.items() if len(members) < 2}
    assert not orphans, f"孤儿 session 链（挂着 session_id 却只有一条）：{orphans}"


def test_expect_fields_well_formed(cases):
    for c in cases:
        cid = c.get("id", "?")
        for key in ("expect_tables", "expect_values"):
            v = c.get(key)
            assert v is None or (isinstance(v, list) and all(isinstance(x, str) for x in v)), (
                f"{cid}: {key} 必须是 str 列表"
            )
        for key in ("expect_nonempty", "expect_empty"):
            v = c.get(key)
            assert v is None or isinstance(v, bool), f"{cid}: {key} 必须是 bool"
        assert not (c.get("expect_nonempty") and c.get("expect_empty")), (
            f"{cid}: expect_nonempty 与 expect_empty 共轭（同一用例不可能既期望非空又期望空）"
        )


def test_golden_covers_required_families(cases):
    """baseline 文档 §2 来源③要求覆盖的面在集子里有对应（防扩集只堆数量）。"""
    families = {
        "多轮继承": any(c.get("session_id") for c in cases),
        "聚合": any(("多少" in c["question"] or "总金额" in c["question"] or "平均" in c["question"]) for c in cases),
        "字面变体": any(("付款成功" in c["question"] or "北京市" in c["question"]) for c in cases),
        "时间窗": any(("月" in c["question"]) for c in cases),
        "空结果极": any(c.get("expect_empty") for c in cases),
        "安全类": any("手机" in c["question"] for c in cases),
    }
    missing = [name for name, ok in families.items() if not ok]
    assert not missing, f"golden 集缺少必需面：{missing}（baseline 文档 §2 来源③）"


def test_minimum_size(cases):
    """baseline 文档 §2 要求 20–50 条。"""
    assert len(cases) >= 20, f"golden 集 {len(cases)} 条，低于文档下限 20"
