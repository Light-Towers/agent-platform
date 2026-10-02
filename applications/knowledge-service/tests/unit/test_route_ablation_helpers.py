# -*- coding: utf-8 -*-
"""
test_route_ablation_helpers.py —— 路线消融运行器的 Phase B 纯分析助手单测（不连 Milvus）。

只导入 eval.run_route_ablation 中**不触碰 Milvus/Neo4j** 的纯函数（顶层 import 均 stdlib，
_load_deps 为延迟加载，故模块可安全导入）：
- _paired_series：base/variant 配对对齐 + skip 剔除（不伪造）；
- _compute_contrib：LOO/Add-one 方向判定 + 分桶；
- _compute_web_interference：web@rerank 挤掉本地相关块判"有害"，空样本返回 []。
"""

from eval.run_route_ablation import (
    _compute_contrib,
    _compute_web_interference,
    _paired_series,
)


def _rec(qid, base, emb_only, emb_hyde, loo_kg, tag="参数查询", esrc="kg", skip_variant=False):
    return {
        "qid": qid,
        "tag": tag,
        "expected_source": esrc,
        "configs": {
            "rrf_all": {"metrics": {"ndcg@10": base, "recall@10": base}, "skipped": False},
            "emb_only": {"metrics": {"ndcg@10": emb_only, "recall@10": emb_only}, "skipped": False},
            "rrf_emb_hyde": {"metrics": {"ndcg@10": emb_hyde, "recall@10": emb_hyde}, "skipped": False},
            "loo:kg": {
                "metrics": {"ndcg@10": loo_kg, "recall@10": loo_kg},
                "skipped": skip_variant,
            },
        },
    }


def _mk(base, emb_only, emb_hyde, loo_kg, n=6, **kw):
    return [_rec(f"q{i}", base, emb_only, emb_hyde, loo_kg, **kw) for i in range(n)]


def test_paired_series_drops_unaligned_and_skipped():
    records = [
        _rec("q0", 0.9, 0.3, 0.8, 0.5),
        _rec("q1", 0.9, 0.3, 0.8, 0.5, skip_variant=True),  # variant skip → 整对剔除
    ]
    b, v = _paired_series(records, "rrf_all", "loo:kg", ("ndcg@10",))
    assert len(b["ndcg@10"]) == 1  # 只剩对齐且双方非 skip 的一条
    assert len(v["ndcg@10"]) == 1


def test_compute_contrib_loo_positive_and_add_gain():
    # base=0.9，去 kg 掉到 0.5 → kg 正贡献；emb_only 0.3 → +hyde 0.8 → 增益
    records = _mk(0.9, 0.3, 0.8, 0.5)
    contrib = _compute_contrib(records, ["loo:kg"])
    loo = contrib["overall_loo"]
    assert loo and all(r["verdict"] == "正贡献(去掉变差)" for r in loo)
    assert all(r["significant"] for r in loo)
    add = contrib["overall_add"]
    assert add and all(r["verdict"] == "增益" for r in add)
    # 分桶（tag / expected_source 均单一值且 >=2 样本）
    assert "tag=参数查询" in contrib["per_bucket"]
    assert "expected_source=kg" in contrib["per_bucket"]


def test_compute_contrib_significant_loss_on_removal():
    # 去掉 kg 反而涨分（0.9 → 1.0 变体）→ kg 拖后腿
    records = _mk(0.9, 0.9, 0.9, 1.0)
    contrib = _compute_contrib(records, ["loo:kg"])
    loo = [r for r in contrib["overall_loo"] if r["label"] == "loo:kg"]
    assert loo and all(r["verdict"] == "拖后腿(去掉变好)" for r in loo)


def test_web_interference_negative_when_web_displaces_local():
    pairs = [
        {
            "no_web": {"metrics": {"ndcg@10": 0.8, "recall@10": 0.8}, "skipped": False},
            "web": {"metrics": {"ndcg@10": 0.5, "recall@10": 0.5}, "skipped": False},
        }
        for _ in range(5)
    ]
    rows = _compute_web_interference(pairs)
    assert rows and all(r["verdict"] == "有害" for r in rows)


def test_web_interference_empty_not_fabricated():
    assert _compute_web_interference([]) == []
    # 全 skip 不产出
    pairs = [
        {
            "no_web": {"metrics": {"ndcg@10": 0.8, "recall@10": 0.8}, "skipped": True},
            "web": {"metrics": {"ndcg@10": 0.5, "recall@10": 0.5}, "skipped": False},
        }
    ]
    assert _compute_web_interference(pairs) == []
