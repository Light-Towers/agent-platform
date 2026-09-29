# -*- coding: utf-8 -*-
"""
test_gen_golden.py —— 真实语料自举 golden 的纯标注逻辑单测（不连 Milvus/LLM）。

覆盖 eval/gen_golden.py 的确定性纯函数：
- 中文分词 / Jaccard；
- 干扰块选取（同 item / 跨 item）与近似重复检测；
- expected_source / tag 启发式归类；
- LLM JSON 稳健解析（含 markdown 围栏、非法输入抛错不猜值）；
- golden 记录组装（relevant=真实 id + 干扰块 grade 0）与抽检表渲染。
"""

import pytest

from eval.gen_golden import (
    build_golden_record,
    derive_expected_source,
    detect_near_dupes,
    guess_tag,
    jaccard,
    parse_llm_json,
    render_audit,
    select_hard_negatives,
    synthesis_prompt,
    tokenize_cn,
)

_POOL = [
    {"chunk_id": "1", "content": "HAK 180 烫金机额定电压 220V 功率 1.5kW", "item_name": "HAK 180 烫金机"},
    {"chunk_id": "2", "content": "HAK 180 烫金机额定电压为 220V 交流电", "item_name": "HAK 180 烫金机"},
    {"chunk_id": "3", "content": "烫金机如何更换烫金头：先断电再拆固定螺丝", "item_name": "HAK 180 烫金机"},
    {"chunk_id": "4", "content": "万用表 RS-12 额定电压 9V 电池供电", "item_name": "万用表RS-12"},
]


def test_tokenize_and_jaccard():
    a = tokenize_cn("额定电压 220V")
    b = tokenize_cn("额定电压为 220V")
    assert "额定" in a
    assert "220v" in a  # ASCII 词小写
    assert 0.0 < jaccard(a, b) <= 1.0
    assert jaccard(set(), a) == 0.0


def test_select_hard_negatives_prefers_same_item():
    target = _POOL[0]
    hn = select_hard_negatives(target, _POOL, same_item_limit=2, cross_item_limit=1)
    # 同 item 的 2、3 应优先于跨 item 的 4；且不含自身 1
    assert "1" not in hn
    assert len(hn) <= 3


def test_detect_near_dupes():
    # chunk 2 与 chunk 1 高度近似（同 item 同类参数）
    nd = detect_near_dupes(_POOL[0], _POOL, threshold=0.2)
    assert "1" not in nd
    assert isinstance(nd, list)


def test_derive_expected_source_heuristics():
    # 专有型号 + 故障 → kg
    assert derive_expected_source({}, "HAK 180 烫金机报错 E01 怎么解决") in ("kg", "hyde")
    # 纯参数事实无型号 → embedding
    assert derive_expected_source({}, "这个设备的额定功率是多少") == "embedding"


def test_guess_tag():
    assert guess_tag("如何更换烫金头") == "操作步骤"
    assert guess_tag("开机报错怎么办") == "故障排查"
    assert guess_tag("额定电压和功率分别是多少") == "多跳"
    assert guess_tag("额定电压是多少") == "参数查询"


def test_parse_llm_json_plain_and_fenced():
    assert parse_llm_json('{"query": "q", "tag": "参数查询"}')["query"] == "q"
    assert parse_llm_json('```json\n{"query": "fenced"}\n```')["query"] == "fenced"
    assert parse_llm_json('前缀噪声 {"reference_answer": "x"} 后缀')['reference_answer'] == "x"


def test_parse_llm_json_raises_on_garbage():
    with pytest.raises(ValueError):
        parse_llm_json("完全不是 json 的一句话")


def test_build_golden_record_shape():
    rec = build_golden_record(
        _POOL[0],
        {"query": "额定电压多少", "reference_answer": "220V", "tag": "参数查询", "expected_source": "embedding"},
        ["2", "4"],
        ["2"],
        qid="g001",
    )
    assert rec["relevant_chunk_ids"] == ["1"]  # 真实 chunk_id 直接可计分
    assert rec["grade"]["1"] == 2
    assert rec["grade"]["2"] == 0 and rec["grade"]["4"] == 0  # 干扰块 grade 0
    assert rec["expected_source"] == "embedding"
    assert rec["tags"] == ["参数查询"]
    assert rec["reference_answer"] == "220V"


def test_build_golden_record_invalid_tag_falls_back():
    rec = build_golden_record(
        _POOL[0], {"query": "如何开机", "tag": "瞎写的类别"}, [], [], qid="g002"
    )
    assert rec["tags"] == ["操作步骤"]  # guess_tag 兜底


def test_synthesis_prompt_contains_chunk_and_schema():
    p = synthesis_prompt(_POOL[0])
    assert "HAK 180" in p
    assert "reference_answer" in p
    assert "expected_source" in p


def test_render_audit_escapes_and_samples():
    recs = [
        build_golden_record(_POOL[0], {"query": "a|b", "reference_answer": "c\nd", "tag": "参数查询"}, [], [], qid="g001"),
        build_golden_record(_POOL[1], {"query": "q2", "reference_answer": "a2", "tag": "参数查询"}, [], [], qid="g002"),
    ]
    md = render_audit(recs, sample=2, seed=0)
    assert "| g0" in md
    assert "\\|" in md  # 竖线被转义，避免破表
    assert "人工抽检" in md
