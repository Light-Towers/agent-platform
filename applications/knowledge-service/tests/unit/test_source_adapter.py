# -*- coding: utf-8 -*-
"""
test_source_adapter.py —— 数据源插拔契约单测（纯 stdlib，不连 Milvus/Neo4j）。

覆盖 eval/source_adapter.py：
- 合流类别判定（rrf 同构 vs rerank 异构）：web 不进 RRF、kg 需 id 别名；
- sidecar 泛化命名与读取（不存在/非法 → 空表不伪造）；
- alias_ids 命中/未命中/空表三态；
- parse_id_map_arg 解析与非法抛错；
- SourceSpec 非法 merge 抛错；
- onboarding_checklist 五步显性门禁。
"""

from pathlib import Path

import pytest

from eval.source_adapter import (
    DEFAULT_SOURCES,
    MERGE_RERANK,
    MERGE_RRF,
    SourceSpec,
    alias_channels,
    alias_ids,
    default_id_map_path,
    load_id_map,
    onboarding_checklist,
    parse_id_map_arg,
    rerank_channels,
    rrf_channels,
    spec_for,
)


def test_merge_classes_partition_channels():
    # web 是异构、只在 rerank 合流；embedding/hyde/kg 进 RRF
    assert "web" not in rrf_channels()
    assert "web" in rerank_channels()
    assert set(rrf_channels()) == {"embedding", "hyde", "kg"}
    # rrf 与 rerank 不交叠、并集覆盖全部登记源
    assert not (set(rrf_channels()) & set(rerank_channels()))
    assert set(rrf_channels()) | set(rerank_channels()) == {s.name for s in DEFAULT_SOURCES}


def test_kg_is_only_alias_channel():
    assert alias_channels() == ("kg",)


def test_spec_for_lookup():
    assert spec_for("kg").merge == MERGE_RRF
    assert spec_for("kg").needs_id_alias is True
    assert spec_for("web").merge == MERGE_RERANK
    assert spec_for("does-not-exist") is None


def test_invalid_merge_raises():
    with pytest.raises(ValueError):
        SourceSpec("x", "nonsense")


def test_default_id_map_path_generalized(tmp_path):
    # kg → kg_id_map.json（向后兼容），新源同样规则
    assert default_id_map_path("kg", tmp_path) == tmp_path / "kg_id_map.json"
    assert default_id_map_path("tavily", tmp_path) == tmp_path / "tavily_id_map.json"


def test_load_id_map_missing_returns_empty(tmp_path):
    assert load_id_map(tmp_path / "nope.json") == {}


def test_load_id_map_valid(tmp_path):
    p = tmp_path / "kg_id_map.json"
    p.write_text('{"kg::A::x": "123", "kg::B::y": 9}', encoding="utf-8")
    m = load_id_map(p)
    assert m == {"kg::A::x": "123", "kg::B::y": "9"}  # value 统一 str 归一


def test_load_id_map_corrupt_returns_empty(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    assert load_id_map(p) == {}


def test_alias_ids_hit_miss_and_empty():
    docs = [{"chunk_id": "kg::A::x"}, {"chunk_id": "other"}]
    mapped = alias_ids(docs, {"kg::A::x": "123"})
    assert mapped[0]["chunk_id"] == "123"
    assert mapped[1]["chunk_id"] == "other"  # 未命中保留原 id
    # 空表原样返回（同一对象引用，无副作用）
    assert alias_ids(docs, {}) is docs


def test_parse_id_map_arg_ok_and_invalid():
    out = parse_id_map_arg(["kg=a.json", "tavily = b.json "])
    assert out["kg"] == Path("a.json")
    assert out["tavily"] == Path("b.json")
    with pytest.raises(ValueError):
        parse_id_map_arg(["no_equals_sign"])
    with pytest.raises(ValueError):
        parse_id_map_arg(["=missing_name"])


def test_onboarding_checklist_five_steps():
    steps = onboarding_checklist()
    assert len(steps) == 5
    assert any("add-one-in" in s for s in steps)
    assert any("expected_source" in s for s in steps)
