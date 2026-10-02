# -*- coding: utf-8 -*-
"""
test_ablation.py —— Dynamic TopK 消融策略纯函数单测（M3.5，方案 §6.4）。

覆盖 eval/ablation.py：
- 策略名解析（fixed_k=N / dynamic，含非法输入）；
- 固定截断行为（fixed_k=3/5/10 与 dynamic 在 mock 检索结果上的截断差异）；
- token 启发式估算函数；
- 文本字段提取（text / content 兼容）；
- 均值 / P95 统计与按策略聚合。

【不依赖重型依赖】：本文件只 import eval.ablation（纯 stdlib），不连 Milvus，
不 import run_ablation / run_eval（避免拉起重型依赖），与 tests/unit 其余用例一致。
"""

import pytest

from eval.ablation import (
    ROUTE_CONFIGS,
    ROUTE_ORDER,
    STRATEGIES,
    active_route_channels,
    aggregate_route_rows,
    aggregate_strategy_rows,
    apply_strategy,
    compute_mean,
    compute_p95,
    estimate_tokens,
    extract_doc_text,
    fallback_config_hash,
    leave_one_out_configs,
    parse_strategy,
    select_channels,
    select_route_sources,
    truncate_to_fixed_k,
)


# ---------------------------------------------------------------------------
# 策略名解析
# ---------------------------------------------------------------------------
def test_parse_strategy_fixed_k():
    assert parse_strategy("fixed_k=3") == ("fixed", 3)
    assert parse_strategy("fixed_k=10") == ("fixed", 10)


def test_parse_strategy_dynamic():
    assert parse_strategy("dynamic") == ("dynamic", None)


def test_parse_strategy_case_insensitive():
    assert parse_strategy("FIXED_K=5") == ("fixed", 5)
    assert parse_strategy("Dynamic") == ("dynamic", None)


def test_parse_strategy_invalid_raises():
    for bad in ("fixed_k=0", "fixed_k=-1", "fixed_k=abc", "unknown", ""):
        with pytest.raises(ValueError):
            parse_strategy(bad)


# ---------------------------------------------------------------------------
# 固定截断
# ---------------------------------------------------------------------------
def _mock_docs(n: int):
    return [{"chunk_id": str(i), "text": f"doc-{i}"} for i in range(1, n + 1)]


def test_truncate_to_fixed_k_basic():
    docs = _mock_docs(5)
    assert [d["chunk_id"] for d in truncate_to_fixed_k(docs, 3)] == ["1", "2", "3"]


def test_truncate_to_fixed_k_k_larger_than_len():
    docs = _mock_docs(5)
    assert len(truncate_to_fixed_k(docs, 10)) == 5


def test_truncate_to_fixed_k_zero_or_empty():
    assert truncate_to_fixed_k(_mock_docs(5), 0) == []
    assert truncate_to_fixed_k([], 3) == []


def test_apply_strategy_fixed_truncates():
    docs = _mock_docs(5)
    assert len(apply_strategy("fixed_k=3", docs)) == 3
    assert len(apply_strategy("fixed_k=5", docs)) == 5
    assert len(apply_strategy("fixed_k=10", docs)) == 5  # 候选不足 10 条 → 全保留


def test_apply_strategy_dynamic_passthrough():
    # dynamic 的截断逻辑在 node_rerank 内部执行，脚本层原样返回
    docs = _mock_docs(5)
    assert apply_strategy("dynamic", docs) == list(docs)


def test_apply_strategy_invalid_raises():
    with pytest.raises(ValueError):
        apply_strategy("fixed_k=abc", _mock_docs(3))


# ---------------------------------------------------------------------------
# token 估算（启发式）
# ---------------------------------------------------------------------------
def test_estimate_tokens_empty():
    assert estimate_tokens("") == 0


def test_estimate_tokens_cjk_one_per_char():
    assert estimate_tokens("烫金机") == 3


def test_estimate_tokens_ascii_four_per_char():
    assert estimate_tokens("abcd") == 1  # int(4/4)=1
    assert estimate_tokens("a" * 20) == 5  # int(20/4)=5


def test_estimate_tokens_mixed():
    # 3 个 CJK + 4 个 ascii → int(3 + 4/4) = 4
    assert estimate_tokens("烫金机abcd") == 4


# ---------------------------------------------------------------------------
# 文本字段提取（rerank text / RRF content 兼容）
# ---------------------------------------------------------------------------
def test_extract_doc_text_prefers_text():
    assert extract_doc_text({"text": "abc", "content": "xyz"}) == "abc"


def test_extract_doc_text_falls_back_to_content():
    assert extract_doc_text({"text": "", "content": "xyz"}) == "xyz"


def test_extract_doc_text_missing():
    assert extract_doc_text({}) == ""
    assert extract_doc_text("not-a-dict") == ""


# ---------------------------------------------------------------------------
# 均值 / P95 / 聚合
# ---------------------------------------------------------------------------
def test_compute_mean():
    assert compute_mean([1, 2, 3, 4]) == pytest.approx(2.5)
    assert compute_mean([]) == 0.0


def test_compute_p95_known_values():
    assert compute_p95([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]) == pytest.approx(10.0)
    assert compute_p95([1]) == pytest.approx(1.0)
    assert compute_p95([1, 2, 3]) == pytest.approx(3.0)  # idx = ceil(2.85)-1 = 2
    assert compute_p95([]) == 0.0


def test_aggregate_strategy_rows_covers_all_strategies():
    per_query = {
        s: [
            {
                "metrics": {"recall@10": 0.5, "ndcg@10": 0.4},
                "returned": 3,
                "tokens_estimate": 100.0,
                "latency_ms": 10.0,
            }
        ]
        for s in STRATEGIES
    }
    rows = aggregate_strategy_rows(per_query)
    assert [r["strategy"] for r in rows] == list(STRATEGIES)
    for row in rows:
        assert row["recall@10"] == pytest.approx(0.5)
        assert row["ndcg@10"] == pytest.approx(0.4)
        assert row["avg_returned"] == pytest.approx(3.0)
        assert row["avg_tokens"] == pytest.approx(100.0)
        assert row["p95_latency_ms"] == pytest.approx(10.0)


def test_aggregate_strategy_rows_means():
    per_query = {
        "dynamic": [
            {
                "metrics": {"recall@10": 0.5, "ndcg@10": 0.4},
                "returned": 3,
                "tokens_estimate": 100.0,
                "latency_ms": 10.0,
            },
            {
                "metrics": {"recall@10": 0.7, "ndcg@10": 0.6},
                "returned": 5,
                "tokens_estimate": 200.0,
                "latency_ms": 20.0,
            },
        ]
    }
    rows = aggregate_strategy_rows(per_query)
    dynamic = [r for r in rows if r["strategy"] == "dynamic"][0]
    assert dynamic["recall@10"] == pytest.approx(0.6)
    assert dynamic["ndcg@10"] == pytest.approx(0.5)
    assert dynamic["avg_returned"] == pytest.approx(4.0)
    assert dynamic["avg_tokens"] == pytest.approx(150.0)
    assert dynamic["p95_latency_ms"] == pytest.approx(20.0)


# ---------------------------------------------------------------------------
# 路线消融：select_route_sources / active_route_channels / aggregate_route_rows
# ---------------------------------------------------------------------------
def _routes():
    return {
        "embedding": [{"chunk_id": "1"}, {"chunk_id": "2"}],
        "hyde": [{"chunk_id": "2"}, {"chunk_id": "3"}],
        "kg": [{"chunk_id": "kg::x"}],
    }


def test_select_route_sources_single_route_passthrough():
    # 单路：仅返回该路 source（权重默认 1.0），RRF 不改变单列表顺序
    srcs = select_route_sources(_routes(), "emb_only")
    assert len(srcs) == 1
    docs, w = srcs[0]
    assert [d["chunk_id"] for d in docs] == ["1", "2"]
    assert w == pytest.approx(1.0)


def test_select_route_sources_all_three_channels():
    srcs = select_route_sources(_routes(), "rrf_all")
    assert len(srcs) == 3


def test_select_route_sources_emb_hyde_excludes_kg():
    srcs = select_route_sources(_routes(), "rrf_emb_hyde")
    assert len(srcs) == 2


def test_select_route_sources_drops_empty_channels():
    routes = {"embedding": [{"chunk_id": "1"}], "hyde": [], "kg": []}
    # rrf_all 声明三路，但 hyde/kg 为空 → 仅保留 embedding（运行器据此可判 skip）
    srcs = select_route_sources(routes, "rrf_all")
    assert len(srcs) == 1
    assert [d["chunk_id"] for d in srcs[0][0]] == ["1"]


def test_select_route_sources_applies_weights():
    srcs = select_route_sources(_routes(), "rrf_all", weights={"embedding": 1.0, "hyde": 0.6, "kg": 1.0})
    weights = sorted(w for _docs, w in srcs)
    assert weights == pytest.approx([0.6, 1.0, 1.0])


def test_select_route_sources_all_empty_returns_empty():
    routes = {"embedding": [], "hyde": [], "kg": []}
    assert select_route_sources(routes, "rrf_all") == []


def test_select_route_sources_unknown_config_raises():
    with pytest.raises(ValueError):
        select_route_sources(_routes(), "not_a_config")


def test_active_route_channels_filters_empty():
    routes = {"embedding": [{"chunk_id": "1"}], "hyde": [], "kg": [{"chunk_id": "k"}]}
    assert set(active_route_channels(routes, "rrf_all")) == {"embedding", "kg"}


def test_active_route_channels_unknown_raises():
    with pytest.raises(ValueError):
        active_route_channels(_routes(), "bad")


def test_route_configs_order_keys_align():
    # ROUTE_ORDER 中每个配置都必须在 ROUTE_CONFIGS 有定义
    for config in ROUTE_ORDER:
        assert config in ROUTE_CONFIGS


def _rec(m, returned=1, skipped=False):
    return {"metrics": m, "returned": returned, "skipped": skipped}


def _full_metrics(r10, nd10):
    return {"recall@5": r10, "recall@10": r10, "mrr": nd10, "hit_rate@5": r10, "ndcg@10": nd10}


def test_aggregate_route_rows_means_over_active_only():
    per_config = {
        "emb_only": [
            _rec(_full_metrics(0.5, 0.4), returned=3),
            _rec(_full_metrics(0.7, 0.6), returned=5),
        ]
    }
    rows = aggregate_route_rows(per_config, ["emb_only"])
    row = rows[0]
    assert row["config"] == "emb_only"
    assert row["skipped"] is False
    assert row["sample_size"] == 2
    assert row["recall@10"] == pytest.approx(0.6)
    assert row["ndcg@10"] == pytest.approx(0.5)
    assert row["avg_returned"] == pytest.approx(4.0)


def test_aggregate_route_rows_skips_skipped_records():
    # 含一条 skipped → 不计入均值（避免空列表把均值拉低成假数据）
    per_config = {
        "hyde_only": [
            _rec(_full_metrics(0.8, 0.8), returned=4),
            _rec(_full_metrics(0.0, 0.0), returned=0, skipped=True),
        ]
    }
    row = aggregate_route_rows(per_config, ["hyde_only"])[0]
    assert row["sample_size"] == 1
    assert row["recall@10"] == pytest.approx(0.8)


def test_aggregate_route_rows_all_skipped_marks_row_skipped():
    per_config = {"kg_only": [_rec(_full_metrics(0.0, 0.0), returned=0, skipped=True)]}
    row = aggregate_route_rows(per_config, ["kg_only"])[0]
    assert row["skipped"] is True
    assert row["sample_size"] == 0
    assert row["ndcg@10"] == pytest.approx(0.0)


def test_aggregate_route_rows_missing_config_defaults_zero():
    row = aggregate_route_rows({}, ["rrf_all"])[0]
    assert row["skipped"] is True
    assert row["recall@10"] == 0.0


# ---------------------------------------------------------------------------
# config_hash 降级实现（部署镜像缺 conf/config_hash 时的兜底标签，仅用于归因/run_id）
# ---------------------------------------------------------------------------
def test_fallback_config_hash_deterministic_and_env_driven(monkeypatch):
    monkeypatch.setenv("CHUNKS_COLLECTION", "eval_rag_routes")
    monkeypatch.setenv("EMBEDDING_MODE", "local")
    h1 = fallback_config_hash()
    # 形状与 compute_config_hash 一致："fb" 前缀 + sha256 前 8 位十六进制。
    assert h1.startswith("fb") and len(h1) == 10
    assert h1 == fallback_config_hash()  # 同 env 下稳定（可复现）
    monkeypatch.setenv("CHUNKS_COLLECTION", "other_collection")
    assert fallback_config_hash() != h1  # env 变化则哈希变化


# ---------------------------------------------------------------------------
# KG 别名归一（--with-kg）：锁死「seed 合成的 kg:: 键 == query_kg 线上产出键」这一可比性命门。
# 顶层不 import run_route_ablation（沿用本文件「只依赖纯 stdlib」约定），故在用例内局部导入；
# 这两个函数与 _load_deps 无关（不触碰 Milvus/Neo4j），导入安全。
# ---------------------------------------------------------------------------
def test_kg_alias_roundtrip_matches_query_kg_id_shape():
    from eval.run_route_ablation import _alias_kg_ids  # 纯函数，无重依赖
    from eval.seed_synthetic_corpus import _KG_ENTITY_PREFIX, _kg_entity_id

    item_raw = "HAK180烫金机"          # 原始 golden item_name（query_kg 精确 IN，不归一）
    chunk_key = "c_101"
    canonical = "4501"                   # Milvus 自增主键（真实 chunk_id）
    name = f"{_KG_ENTITY_PREFIX}{chunk_key}"

    # seed 侧预测的别名键，必须与 query_kg 合成的 chunk_id 逐字相等（否则归一失效、KG 恒 0）。
    kg_id = _kg_entity_id(item_raw, name)
    assert kg_id == f"kg::{item_raw}::{name}"

    kg_map = {kg_id: canonical}
    docs = [
        {"chunk_id": kg_id, "content": "x"},      # 命中别名 → 归一到 canonical
        {"chunk_id": "kg::未知::实体", "content": "y"},  # 无映射 → 保留原 id
    ]
    out = _alias_kg_ids(docs, kg_map)
    assert out[0]["chunk_id"] == canonical
    assert out[1]["chunk_id"] == "kg::未知::实体"


def test_kg_alias_noop_without_map():
    from eval.run_route_ablation import _alias_kg_ids

    docs = [{"chunk_id": "kg::a::b"}]
    assert _alias_kg_ids(docs, {}) is docs  # 空映射直接返回原列表（不归一）


def test_dedupe_docs_by_id_collapses_int_str_canonical_collision():
    from eval.run_route_ablation import _dedupe_docs_by_id

    # 同一底层 chunk：向量路主键落在 id(int)，KG 别名路落在 chunk_id(str)。
    docs = [
        {"id": 469256213779738620, "content": "vec"},
        {"chunk_id": "469256213779738620", "content": "kg"},  # 同 canonical，应被去掉（保留首次）
        {"id": 999, "content": "other"},
        {"no_id": True},  # 无身份 → 丢弃
    ]
    out = _dedupe_docs_by_id(docs)
    assert [d.get("content") for d in out] == ["vec", "other"]


def test_ndcg_never_exceeds_one_after_dedupe():
    from eval.metrics import ndcg_at_k
    from eval.run_route_ablation import _dedupe_docs_by_id

    # 不去重：同一相关 chunk 重复出现 → 原始 nDCG 会 >1（测量假象）。
    relevant = ["1", "2"]
    grades = {"1": 2.0, "2": 2.0}
    dup_docs = [
        {"id": 1}, {"chunk_id": "1"}, {"id": 2},
    ]
    raw_ids = [str(d.get("chunk_id") or d.get("id")) for d in dup_docs]
    assert ndcg_at_k(raw_ids, relevant, grades, k=10) > 1.0  # 复现 bug

    deduped_ids = [str(d.get("chunk_id") or d.get("id")) for d in _dedupe_docs_by_id(dup_docs)]
    assert ndcg_at_k(deduped_ids, relevant, grades, k=10) <= 1.0 + 1e-9  # 修复后合法


# ---------------------------------------------------------------------------
# select_channels（边际贡献的任意子集派生入口）
# ---------------------------------------------------------------------------
def test_select_channels_explicit_subset_and_weight():
    routes = {"embedding": [{"id": 1}], "hyde": [{"id": 2}], "kg": [{"id": 3}]}
    srcs = select_channels(routes, ("embedding", "kg"), {"kg": 0.5})
    assert len(srcs) == 2
    weights = sorted(round(w, 3) for _docs, w in srcs)
    assert weights == [0.5, 1.0]


def test_select_channels_drops_empty_channels():
    routes = {"embedding": [{"id": 1}], "kg": []}
    srcs = select_channels(routes, ("embedding", "kg"))
    assert len(srcs) == 1


def test_select_route_sources_delegates_to_select_channels():
    routes = {"embedding": [{"id": 1}], "hyde": [{"id": 2}], "kg": [{"id": 3}]}
    assert select_route_sources(routes, "rrf_all") == select_channels(
        routes, ROUTE_CONFIGS["rrf_all"]
    )


# ---------------------------------------------------------------------------
# leave_one_out_configs（数据源净贡献归因的变体枚举）
# ---------------------------------------------------------------------------
def test_leave_one_out_configs_enumerates_base():
    loo = leave_one_out_configs("rrf_all")
    assert set(loo) == {"loo:embedding", "loo:hyde", "loo:kg"}
    assert loo["loo:kg"] == ("embedding", "hyde")
    # 每个变体应比 base 少恰好一个通道
    for label, chs in loo.items():
        assert set(chs) == set(ROUTE_CONFIGS["rrf_all"]) - {label.split(":", 1)[1]}


def test_leave_one_out_configs_rejects_unknown_base():
    with pytest.raises(ValueError):
        leave_one_out_configs("nope")
