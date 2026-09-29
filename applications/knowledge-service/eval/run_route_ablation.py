# -*- coding: utf-8 -*-
"""
路线消融运行器（RRF 混合排名 vs 单路召回 + embedding 内 dense/sparse 向量级消融）。

两级消融矩阵（方案「目标产出」）：
  层 1（RRF 通道层）：emb_only / hyde_only / kg_only / rrf_emb_hyde / rrf_all（+ 可选 rrf_all+rerank）
      —— 控制变量：默认不重排以隔离「融合」本身效果；每路只检索一次并缓存候选，再派生各配置。
  层 2（embedding 内层）：dense_only / sparse_only / dense+sparse + ranker_weights 扫描
      —— 直接调 create_hybrid_search_requests + hybrid_search 传不同 ranker_weights，
         **不改线上 node_search_embedding**。

指标（零依赖纯函数 agent_core.metrics.retrieval）：recall@5 / recall@10 / mrr / hit_rate@5 / ndcg@10。

前置：先运行 `python eval/seed_synthetic_corpus.py` 建合成索引 + 生成重标注 golden
（`golden_queries.labeled.jsonl`，relevant_chunk_ids 为真实 chunk_id），否则指标恒为 0。

诚实声明（防伪造，务必读）：
  - 某路缺依赖 / 无候选（如 KG 未接 Neo4j、HyDE 无 LLM key）→ 该配置标注 skipped，**不预填数字**。
  - KG 路返回 `kg::{item}::{name}` 命名空间 chunk_id，与 Milvus 真实 chunk_id 不同源。若先跑
    `seed_synthetic_corpus.py --with-kg`（写 Neo4j Entity + 产出 `kg_id_map.json`），本脚本会用该 sidecar
    把 `kg::` id 归一到 canonical Milvus id（同基准可比）；无 sidecar 时 KG 相关召回结构性为 0（非缺陷）。
  - EMBEDDING_MODE=api 时 sparse 为本地 TF 词频（非 BGE-M3 learned sparse），层 2 sparse 语义偏移。

用法：
    python eval/run_route_ablation.py [--golden eval/golden_queries.labeled.jsonl]
                                       [--limit N] [--out eval/runs] [--max-results 10]
                                       [--no-hyde] [--no-kg] [--with-rerank] [--no-layer2] [--kg-id-map PATH]
                                       [--id-map SOURCE=PATH ...] [--with-contrib] [--param-scan]
                                       [--web-snapshot PATH]

Phase B 扩展（回答"新增数据源/改参数到底帮没帮上忙"）：
  - --with-contrib：在缓存候选上派生 Leave-one-out（base=rrf_all 逐一减一路）与
    Add-one-in（base=emb_only 逐一加一路），overall + 分桶（tag × expected_source）出**数据源贡献矩阵**，
    配对 bootstrap 95% CI 判显著（不显著判"冗余/噪声"，绝不渲染成"更优"）。
  - --param-scan：rrf.k 网格 + 通道权重单因子敏感性扫描（供回填 retrieval.yaml，非拍脑袋）。
  - --id-map SOURCE=PATH：泛化 id 别名 sidecar（取代仅 kg 专用；--kg-id-map 仍向后兼容）。
  - --web-snapshot PATH：异构 web 冻结快照，配合 --with-rerank 测 web@rerank 对本地相关块的干扰度
    （web 不进 RRF，只在 rerank 合流；无 --with-rerank 则诚实标 skipped，不假装能给 web 算 recall）。

实现说明：重型 import（pymilvus / 检索节点 / run_eval）延迟到执行期加载，
`--help` 在任何环境可打印。Milvus 不可达 / 集合不存在 → 清晰报错并 return 1，不吞异常。
"""

import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# 脚本直跑路径引导（与 run_eval / run_ablation 一致）。
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from eval.ablation import (  # noqa: E402 —— 纯 stdlib，可早导入
    EVAL_COLLECTION_NAME,
    HYBRID_DEFAULT_LABEL,
    LEXICAL_WEIGHT_SCAN,
    ROUTE_CONFIGS,
    ROUTE_ORDER,
    active_route_channels,
    aggregate_route_rows,
    fallback_config_hash,
    leave_one_out_configs,
    select_channels,
    select_route_sources,
)
from eval.source_adapter import (  # noqa: E402 —— 纯 stdlib，插拔契约与 id 别名归一
    alias_channels,
    alias_ids,
    load_id_map,
    onboarding_checklist,
    parse_id_map_arg,
    rrf_channels,
)

# 集合隔离必须在任何 knowledge_service.* 导入前生效（须与 seed 同一集合）。
os.environ.setdefault("CHUNKS_COLLECTION", EVAL_COLLECTION_NAME)

DEFAULT_GOLDEN: Path = Path(__file__).resolve().parent / "golden_queries.labeled.jsonl"
DEFAULT_OUT: Path = Path(__file__).resolve().parent / "runs"
# KG 别名 sidecar（seed --with-kg 产出）：`kg::{item}::{name}` → canonical（Milvus 真实 chunk_id）。
DEFAULT_KG_MAP: Path = Path(__file__).resolve().parent / "kg_id_map.json"
REPORT_FILE = "route_ablation.md"
PER_QUERY_FILE = "route_per_query.jsonl"

# Phase B：贡献矩阵参与配对比较的指标（nDCG 排序质量 + Recall 召回能力）。
CONTRIB_METRIC_KEYS: Tuple[str, ...] = ("ndcg@10", "recall@10")
# Add-one-in 叠加链（base=emb_only，逐级并入 rrf_all 的其余通道）：{label: 叠加后的配置名}。
ADD_ONE_CHAIN: Tuple[Tuple[str, str], ...] = (
    ("+hyde (emb+hyde)", "rrf_emb_hyde"),
    ("+kg (rrf_all)", "rrf_all"),
)
# --param-scan 网格：rrf.k 档位 + 通道权重单因子倍率。
RRF_K_SCAN: Tuple[int, ...] = (20, 40, 60, 100)
CHANNEL_WEIGHT_FACTORS: Tuple[float, ...] = (0.5, 2.0)
# web 异构臂配置名（仅在 --web-snapshot + --with-rerank 时产出）。
WEB_ARM = "rrf_all+rerank+web"
# 检索指标 skip 时的占位零值（与 _run_layer1 旧口径一致，不伪造有效读数）。
_ZERO_METRICS: Dict[str, float] = {
    "recall@5": 0.0,
    "recall@10": 0.0,
    "mrr": 0.0,
    "hit_rate@5": 0.0,
    "ndcg@10": 0.0,
}


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="RRF 混合排名 vs 单路召回 路线消融运行器（层1 RRF 通道 + 层2 dense/sparse 向量级）。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--golden", default=str(DEFAULT_GOLDEN), help="重标注 golden 数据集路径（真实 chunk_id）")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="评测输出根目录")
    parser.add_argument("--limit", type=int, default=None, help="只跑前 N 条 query（调试用）")
    parser.add_argument("--max-results", type=int, default=10, help="RRF 融合 / 检索结果截断上限")
    parser.add_argument("--no-hyde", action="store_true", help="不跑 HyDE 路（无 LLM 环境时关闭）")
    parser.add_argument("--no-kg", action="store_true", help="不跑 KG 路（无 Neo4j 环境时关闭）")
    parser.add_argument(
        "--kg-id-map",
        default=str(DEFAULT_KG_MAP),
        help="KG 别名 sidecar（seed --with-kg 产出）；存在则将 kg:: id 归一到 canonical Milvus id，不存在则保持现状（kg 不匹配）",
    )
    parser.add_argument("--with-rerank", action="store_true", help="额外跑 rrf_all+rerank（需 reranker）")
    parser.add_argument("--no-layer2", action="store_true", help="跳过层 2（dense/sparse 向量级消融）")
    parser.add_argument(
        "--id-map",
        action="append",
        default=[],
        metavar="SOURCE=PATH",
        help="泛化 id 别名 sidecar（可重复，如 kg=kg_id_map.json tavily=tavily_id_map.json）；"
        "覆盖同名源的 --kg-id-map 默认",
    )
    parser.add_argument(
        "--with-contrib",
        action="store_true",
        help="额外输出数据源边际贡献矩阵（Leave-one-out + Add-one-in，overall + 分桶 tag×expected_source，配对 bootstrap 显著性）",
    )
    parser.add_argument(
        "--param-scan",
        action="store_true",
        help="额外做参数敏感性扫描（rrf.k 网格 + 通道权重单因子）",
    )
    parser.add_argument(
        "--web-snapshot",
        default=None,
        help="异构 web 冻结快照 jsonl（每行 {\"query\":..., \"web_docs\":[...]}）；需配 --with-rerank 评测 web@rerank 干扰度",
    )
    parser.add_argument(
        "--skip-sparse-check",
        action="store_true",
        help="跳过稀疏编码一致性 canary（仅调试；正常应让导入/查询编码不一致时 fail-fast）",
    )
    return parser.parse_args(argv)


def _load_deps() -> Dict[str, Any]:
    """延迟加载检索链路重型依赖（仅真正执行时导入，保证 --help 可打印）。"""
    from eval.metrics import compute_retrieval_metrics
    from eval.run_eval import _extract_ids, load_golden_queries
    from knowledge_service.clients.milvus_utils import (
        create_hybrid_search_requests,
        get_milvus_client,
        hybrid_search,
    )
    try:
        from knowledge_service.conf.config_hash import compute_config_hash
    except ModuleNotFoundError:
        # 部署镜像落后于工作树、缺 conf/config_hash；仅作归因标签/run_id 目录名，不影响检索数值。
        compute_config_hash = fallback_config_hash
    from knowledge_service.conf.embedding_config import embedding_config
    from knowledge_service.conf.milvus_config import milvus_config
    from knowledge_service.conf.retrieval_config import retrieval_cfg
    from knowledge_service.core.tracing import init_tracing
    from knowledge_service.lm.embedding_utils import generate_embeddings
    from knowledge_service.query_process.agent.nodes.node_query_kg import node_query_kg
    from knowledge_service.query_process.agent.nodes.node_rerank import node_rerank
    from knowledge_service.query_process.agent.nodes.node_rrf import _as_entity_list, reciprocal_rank_fusion
    from knowledge_service.query_process.agent.nodes.node_search_embedding_hyde import (
        node_search_embedding_hyde,
    )
    from knowledge_service.utils.milvus_filter_utils import build_retrieval_filter

    return {
        "compute_retrieval_metrics": compute_retrieval_metrics,
        "extract_ids": _extract_ids,
        "load_golden_queries": load_golden_queries,
        "create_hybrid_search_requests": create_hybrid_search_requests,
        "get_milvus_client": get_milvus_client,
        "hybrid_search": hybrid_search,
        "compute_config_hash": compute_config_hash,
        "milvus_config": milvus_config,
        "retrieval_cfg": retrieval_cfg,
        "embedding_config": embedding_config,
        "init_tracing": init_tracing,
        "generate_embeddings": generate_embeddings,
        "node_query_kg": node_query_kg,
        "node_rerank": node_rerank,
        "node_search_embedding_hyde": node_search_embedding_hyde,
        "as_entity_list": _as_entity_list,
        "reciprocal_rank_fusion": reciprocal_rank_fusion,
        "build_retrieval_filter": build_retrieval_filter,
    }


def _channel_weights(retrieval_cfg) -> Dict[str, float]:
    """RRF 各通道权重（读线上同一配置 retrieval.yaml → rrf.weights）。"""
    raw = getattr(retrieval_cfg.rrf, "weights", {}) or {}
    try:
        return {str(k): float(v) for k, v in dict(raw).items()}
    except (TypeError, ValueError):
        return {}


def _build_state(query: str, item_name: str) -> Dict[str, Any]:
    """构造与 retrieve_one 同口径的最小检索 state（不传 tenant/scope → 过滤退化为仅 item_name）。"""
    return {
        "session_id": f"route_{uuid.uuid4().hex[:12]}",
        "original_query": query,
        "rewritten_query": query,
        "item_names": [item_name] if item_name else [],
        "is_stream": False,
    }


def _build_id_maps(args: argparse.Namespace) -> Dict[str, Dict[str, str]]:
    """
    汇总各需别名通道的 id 别名表（泛化版，取代仅 kg 专用实现）。

    优先级：`--id-map SOURCE=PATH` > `--kg-id-map`（向后兼容，kg 默认走 sidecar 文件）。
    只对 `alias_channels()`（声明 needs_id_alias 的同构源）加载；sidecar 缺失 → 空表（不归一，不伪造）。
    """
    explicit = parse_id_map_arg(args.id_map or [])
    maps: Dict[str, Dict[str, str]] = {}
    for ch in alias_channels():
        path = explicit.get(ch)
        if path is None and ch == "kg":
            path = Path(args.kg_id_map)  # 向后兼容：kg 仍默认读 --kg-id-map
        if path is None:
            maps[ch] = {}
            continue
        maps[ch] = load_id_map(Path(path))
    return maps


def _alias_kg_ids(docs: List[Dict[str, Any]], kg_map: Dict[str, str]) -> List[Dict[str, Any]]:
    """把 KG 命中的 `kg::{item}::{name}` 归一到 canonical Milvus chunk_id（与向量路同基准
    可比的关键）；无映射保留原 id。委托 source_adapter.alias_ids（通用实现），只改 eval
    取回的候选 dict，不碰线上检索代码。空映射直接返回原列表（不归一）。"""
    return alias_ids(docs, kg_map)


def _doc_id(doc: Dict[str, Any]) -> str:
    """取单个 doc 的 canonical str 身份（与 _extract_ids 同口径：chunk_id / id / doc_id）。
    向量路 doc 主键落在 `id`(int64)、KG 别名 doc 落在 `chunk_id`(str)，统一转 str 比较。"""
    cid = doc.get("chunk_id") or doc.get("id") or doc.get("doc_id")
    return str(cid) if cid is not None else ""


def _dedupe_docs_by_id(docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """按 canonical str id 对排序列表去重，保留首次（即最高排名）出现。

    必要而非可选：检索指标（尤其 nDCG）假设排序列表元素互异；KG 别名归一到 canonical 后，
    同一底层 chunk 会以「向量路 id(int) + KG 路 chunk_id(str)」两个不同 RRF key 各出现一次
    （int/str 键不等使线上 RRF 无法合并），若不去重则 DCG 双计 gain 致 nDCG>1 的测量假象。
    只在 eval 取回结果上收敛，不改动线上 RRF/检索代码，也不放宽任何断言。"""
    seen: set = set()
    out: List[Dict[str, Any]] = []
    for doc in docs:
        key = _doc_id(doc)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(doc)
    return out


def _subset_fusion_record(
    deps: Dict[str, Any],
    routes: Dict[str, List[Dict[str, Any]]],
    channels: Tuple[str, ...],
    weights: Dict[str, float],
    k: int,
    max_results: int,
    relevant_ids: List[str],
    grades: Dict[str, Any],
) -> Dict[str, Any]:
    """在缓存候选上对任意通道子集做加权 RRF 融合并算指标（LOO / param-scan 复用同一原语）。

    不重检索（用循环内已缓存的 routes），不碰线上代码；子集全空/无候选 → skipped（不伪造读数）。
    返回与 _run_layer1 兼容的记录 dict（含 metrics/skipped/ids/returned/channels）。
    """
    sources = select_channels(routes, channels, weights)
    if not sources:
        return {
            "skipped": True,
            "metrics": dict(_ZERO_METRICS),
            "ids": [],
            "returned": 0,
            "channels": list(channels),
            "reason": "子集全空",
        }
    fused = deps["reciprocal_rank_fusion"](sources, k=k, max_results=max_results)
    docs = _dedupe_docs_by_id([doc for doc, _score in fused])
    ids = deps["extract_ids"](docs)
    return {
        "skipped": len(ids) == 0,
        "ids": ids,
        "returned": len(docs),
        "metrics": deps["compute_retrieval_metrics"](ids, relevant_ids, grades),
        "channels": list(channels),
    }


def _load_web_snapshot(path: Path) -> Dict[str, List[Dict[str, Any]]]:
    """读异构 web 冻结快照 jsonl（{"query":..., "web_docs":[...]}）→ {query: web_docs}。

    缺失/非法行 → 跳过或返回空（web 臂不启用，不伪造外部检索）。web 无 canonical id、不进 RRF，
    仅在 rerank 阶段合流（既有设计），故需与 --with-rerank 配合才有意义。
    """
    if not path or not Path(path).exists():
        print(f"[route-ablation] web 快照不存在，web 臂不启用：{path}", file=sys.stderr)
        return {}
    out: Dict[str, List[Dict[str, Any]]] = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            q = str(rec.get("query", "")).strip()
            docs = rec.get("web_docs")
            if q and isinstance(docs, list):
                out[q] = docs
    return out


def _embedding_route(
    deps: Dict[str, Any],
    dense_vec: List[float],
    sparse_vec: Dict[int, float],
    expr: Optional[str],
    weights: Tuple[float, float],
    limit: int,
) -> List[Dict[str, Any]]:
    """
    embedding 路检索（eval 侧独立实现，支持任意 ranker_weights，不改线上节点）。
    返回规整后的 entity dict 列表（供 RRF / _extract_ids）。失败返回 []。
    """
    reqs = deps["create_hybrid_search_requests"](
        dense_vector=dense_vec,
        sparse_vector=sparse_vec,
        expr=expr,
        limit=max(limit, 5),  # 底层候选不少于 5，给融合/重排留余量
    )
    res = deps["hybrid_search"](
        client=deps["get_milvus_client"](),
        collection_name=deps["milvus_config"].chunks_collection,
        reqs=reqs,
        ranker_weights=weights,
        norm_score=True,
        limit=limit,
        output_fields=["chunk_id", "content", "item_name"],
    )
    if not res:
        return []
    return deps["as_entity_list"](res[0])


def _run_layer1(
    deps: Dict[str, Any],
    routes: Dict[str, List[Dict[str, Any]]],
    relevant_ids: List[str],
    grades: Dict[str, Any],
    args: argparse.Namespace,
    state: Dict[str, Any],
    web_docs: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Dict[str, Any]]:
    """层 1：在缓存的三路候选上派生各 RRF 配置，逐配置算指标。

    web_docs 非 None 时（--web-snapshot 命中本 query 且 --with-rerank），额外产出
    rrf_all+rerank+web 臂（异构 web 只在 rerank 合流），与无 web 的 rrf_all+rerank 对比本地相关块干扰度。
    """
    retrieval_cfg = deps["retrieval_cfg"]
    weights = _channel_weights(retrieval_cfg)
    k = int(getattr(retrieval_cfg.rrf, "k", 60))
    fused_docs_by_config: Dict[str, List[Dict[str, Any]]] = {}
    out: Dict[str, Dict[str, Any]] = {}

    order = list(ROUTE_ORDER)
    if args.with_rerank:
        order.append("rrf_all+rerank")

    for config in order:
        if config == "rrf_all+rerank":
            # 在 rrf_all 融合结果之上叠 BGE 重排（异常降级 → skipped）
            base = fused_docs_by_config.get("rrf_all", [])
            if not base:
                out[config] = {"skipped": True, "reason": "rrf_all 无候选"}
                if web_docs is not None:
                    out[WEB_ARM] = {"skipped": True, "reason": "rrf_all 无候选"}
                continue
            rerank_state = dict(state)
            rerank_state["rrf_chunks"] = base
            rerank_state["web_search_docs"] = []
            try:
                reranked = deps["node_rerank"](rerank_state).get("reranked_docs", []) or []
            except Exception as e:  # noqa: BLE001 —— reranker 为可选增强臂，外部 I/O 异常面宽，降级为 skipped 不阻断其余配置
                out[config] = {"skipped": True, "reason": f"rerank 异常：{e}"}
                if web_docs is not None:
                    out[WEB_ARM] = {"skipped": True, "reason": f"rerank 异常：{e}"}
                continue
            reranked = _dedupe_docs_by_id(reranked)
            ids = deps["extract_ids"](reranked)
            out[config] = {
                "skipped": len(ids) == 0,
                "ids": ids,
                "returned": len(reranked),
                "channels": ["rerank(rrf_all)"],
            }
            # web@rerank 异构臂：同 base 融合文档 + web 候选，看 web 是否挤掉本地相关块
            if web_docs is not None:
                web_state = dict(state)
                web_state["rrf_chunks"] = base
                web_state["web_search_docs"] = web_docs
                try:
                    web_reranked = deps["node_rerank"](web_state).get("reranked_docs", []) or []
                except Exception as e:  # noqa: BLE001 —— 同 rerank 臂，外部异常降级 skipped 不阻断
                    out[WEB_ARM] = {"skipped": True, "reason": f"rerank(web) 异常：{e}"}
                    continue
                web_reranked = _dedupe_docs_by_id(web_reranked)
                web_ids = deps["extract_ids"](web_reranked)
                out[WEB_ARM] = {
                    "skipped": len(web_ids) == 0,
                    "ids": web_ids,
                    "returned": len(web_reranked),
                    "channels": ["rerank(rrf_all+web)"],
                }
            continue

        sources = select_route_sources(routes, config, weights)
        if not sources:
            out[config] = {"skipped": True, "reason": f"无候选通道（{', '.join(ROUTE_CONFIGS[config])} 均空）"}
            continue
        fused = deps["reciprocal_rank_fusion"](sources, k=k, max_results=args.max_results)
        docs = _dedupe_docs_by_id([doc for doc, _score in fused])
        fused_docs_by_config[config] = docs
        ids = deps["extract_ids"](docs)
        out[config] = {
            "skipped": len(ids) == 0,
            "ids": ids,
            "returned": len(docs),
            "channels": list(active_route_channels(routes, config)),
        }

    # 统一算指标
    for config, rec in out.items():
        if rec.get("skipped"):
            rec["metrics"] = {
                "recall@5": 0.0,
                "recall@10": 0.0,
                "mrr": 0.0,
                "hit_rate@5": 0.0,
                "ndcg@10": 0.0,
            }
            rec.setdefault("ids", [])
            rec.setdefault("returned", 0)
        else:
            rec["metrics"] = deps["compute_retrieval_metrics"](rec["ids"], relevant_ids, grades)
    return out


def _layer2_order_and_weights(retrieval_cfg) -> Tuple[List[str], Dict[str, Tuple[float, float]]]:
    """层 2 配置序 + 每个 label 的 (dense, sparse) 权重（含线上默认档 dense+sparse）。"""
    dense_default = float(retrieval_cfg.hybrid.dense_weight)
    sparse_default = float(retrieval_cfg.hybrid.sparse_weight)
    weights: Dict[str, Tuple[float, float]] = {label: (dw, sw) for label, (dw, sw) in LEXICAL_WEIGHT_SCAN}
    # 单列线上默认档（等同当前 retrieval.yaml hybrid 配比）
    weights[HYBRID_DEFAULT_LABEL] = (dense_default, sparse_default)
    order = ["dense_only", "sparse_only", HYBRID_DEFAULT_LABEL]
    order += [lbl for lbl, _ in LEXICAL_WEIGHT_SCAN if lbl not in order]
    return order, weights


def _run_layer2(
    deps: Dict[str, Any],
    dense_vec: List[float],
    sparse_vec: Dict[int, float],
    expr: Optional[str],
    relevant_ids: List[str],
    grades: Dict[str, Any],
    args: argparse.Namespace,
) -> Dict[str, Dict[str, Any]]:
    """层 2：对同一 query 用不同 ranker_weights 各检索一次 embedding，算指标。"""
    order, weights = _layer2_order_and_weights(deps["retrieval_cfg"])
    out: Dict[str, Dict[str, Any]] = {}
    for label in order:
        docs = _embedding_route(deps, dense_vec, sparse_vec, expr, weights[label], args.max_results)
        ids = deps["extract_ids"](docs)
        rec = {
            "weights": list(weights[label]),
            "ids": ids,
            "returned": len(docs),
        }
        rec["skipped"] = len(ids) == 0
        rec["metrics"] = deps["compute_retrieval_metrics"](ids, relevant_ids, grades)
        out[label] = rec
    return out


def _best_single_config(rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """层 1 单路配置（*_only）中 ndcg@10 最高者，用于 Δ(fusion - best_single)。"""
    singles = [r for r in rows if r["config"].endswith("_only") and not r["skipped"]]
    if not singles:
        return None
    return max(singles, key=lambda r: r["ndcg@10"])


def _render_report(
    run_id: str,
    config_hash: str,
    collection: str,
    sample_size: int,
    args: argparse.Namespace,
    embedding_mode: str,
    route_rows: List[Dict[str, Any]],
    layer2_rows: Optional[List[Dict[str, Any]]],
    skipped_notes: Dict[str, str],
    route_channels: Dict[str, List[str]],
    kg_aliased: bool,
) -> str:
    """生成 Markdown 报告（层1 + 层2 对比表 + Δ + 证据包 + 诚实 caveat）。数字全部实测。"""
    lines: List[str] = [
        "# RRF 混合排名 vs 单路召回 —— 路线消融报告",
        "",
        f"- run_id: `{run_id}`",
        f"- config_hash: `{config_hash}`",
        f"- collection: `{collection}`",
        f"- sample_size: {sample_size}（合成集，单桶样本可能 <15，结论仅定性方向，非线上指标）",
        f"- EMBEDDING_MODE: `{embedding_mode}`"
        + ("  ⚠️ api 模式 sparse=本地 TF 词频（非 learned sparse），层 2 sparse 语义偏移" if embedding_mode == "api" else ""),
        f"- max_results: {args.max_results} | hyde: {not args.no_hyde} | kg: {not args.no_kg} | rerank: {args.with_rerank}",
        f"- kg_id_alias: {'on（kg:: id 已归一到 canonical Milvus id，与向量路同基准）' if kg_aliased else 'off（未供 sidecar，kg:: id 与 golden 不匹配）'}",
        "",
        "## 层 1：RRF 通道层（默认不重排，隔离融合本身效果）",
        "",
        "| 配置 | 融合通道 | Recall@5 | Recall@10 | MRR | HitRate@5 | nDCG@10 | 平均返回 | 状态 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for row in route_rows:
        if row["skipped"]:
            status = "skipped"
            channels = skipped_notes.get(row["config"], "无候选")
        else:
            status = ""
            channels = "+".join(route_channels.get(row["config"], [])) or "-"
        lines.append(
            f"| {row['config']} | {channels} | {row['recall@5']} | {row['recall@10']} | "
            f"{row['mrr']} | {row['hit_rate@5']} | {row['ndcg@10']} | {row['avg_returned']} | {status} |"
        )

    # Δ(fusion - best single)
    fusion = next((r for r in route_rows if r["config"] == "rrf_all" and not r["skipped"]), None)
    best_single = _best_single_config(route_rows)
    lines += ["", "### 融合 vs 最好单路（Δ，正=融合更优）", ""]
    if fusion and best_single:
        for metric in ("recall@10", "ndcg@10"):
            delta = round(fusion[metric] - best_single[metric], 4)
            lines.append(f"- Δ({metric}) = rrf_all({fusion[metric]}) - best_single[{best_single['config']}]({best_single[metric]}) = **{delta}**")
    else:
        lines.append("- _缺可对比的融合/单路行（相关配置被 skip 或无候选），不计算 Δ。_")

    if layer2_rows is not None:
        lines += [
            "",
            "## 层 2：embedding 内 dense/sparse 向量级消融 + ranker_weights 扫描",
            "",
            "| 配比 | (dense, sparse) | Recall@5 | Recall@10 | MRR | HitRate@5 | nDCG@10 | 平均返回 | 状态 |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for row in layer2_rows:
            status = "skipped" if row["skipped"] else ""
            w = row.get("weights", "")
            lines.append(
                f"| {row['config']} | {w} | {row['recall@5']} | {row['recall@10']} | "
                f"{row['mrr']} | {row['hit_rate@5']} | {row['ndcg@10']} | {row['avg_returned']} | {status} |"
            )

    # 证据包（供后续检索原语统一重构方案引用；仅在有真实数据时给方向，否则标注待补）
    lines += ["", "## 证据包（→ 检索原语统一重构方案的量化输入）", ""]
    lines += _evidence_pack(route_rows, layer2_rows, embedding_mode)

    # 诚实 caveat
    lines += [
        "",
        "## 诚实声明与测量口径",
        "",
        "- **指标恒为 0 的前置**：relevant_chunk_ids 须为真实 chunk_id（先跑 seed_synthetic_corpus.py）；否则属管线未打通，非路线结论。",
        (
            "- **KG 命名空间（本次已别名）**：query_kg 合成的 `kg::{item}::{name}` 已经 seed `--with-kg` 产出的 "
            "sidecar 归一到 canonical Milvus chunk_id（同一底层文档在不同索引的本地 id → 共享 doc 身份），"
            "故 KG 与 emb/hyde 在同一 relevant 基准上公平比较。"
            if kg_aliased
            else (
                "- **KG 命名空间**：kg_chunks 的 chunk_id 为 `kg::{item}::{name}`，与 Milvus 真实 chunk_id 不同源；"
                "未供 kg_id_map sidecar（或未跑 seed --with-kg）时 kg 相关召回结构性为 0（非缺陷）。KG 单路被 skip 多因未接 Neo4j。"
            )
        ),
        f"- **sparse 语义**：`EMBEDDING_MODE={embedding_mode}`"
        + ("（TF 词频，无 IDF/learned 权重）" if embedding_mode == "api" else "（BGE-M3 learned sparse）")
        + "。要评 learned sparse / BM25 须用 local 模式或引入 Milvus 原生 BM25 Function。",
        "- 合成集样本小（单桶可能 <15），仅供定性方向判断，非线上指标。",
        "",
    ]
    return "\n".join(lines)


def _evidence_pack(
    route_rows: List[Dict[str, Any]],
    layer2_rows: Optional[List[Dict[str, Any]]],
    embedding_mode: str,
) -> List[str]:
    """从实测行里量化回填：词法最优配比 + 融合是否优于单路（无数据则标注待补，不伪造）。"""
    out: List[str] = []
    fusion = next((r for r in route_rows if r["config"] == "rrf_all" and not r["skipped"]), None)
    best_single = _best_single_config(route_rows)
    if fusion and best_single:
        better = fusion["ndcg@10"] >= best_single["ndcg@10"]
        out.append(
            f"- **RRF 融合 vs 最好单路**：rrf_all nDCG@10={fusion['ndcg@10']} vs "
            f"{best_single['config']}={best_single['ndcg@10']} → 融合{'更优' if better else '未超单路'}"
            f"（词法/通道是否统一为一种，参考此差异）"
        )
    else:
        out.append("- **RRF 融合 vs 最好单路**：数据不足（相关配置被 skip），暂无法给出结论，待补齐环境后复跑。")

    if layer2_rows:
        active = [r for r in layer2_rows if not r["skipped"]]
        if active:
            best = max(active, key=lambda r: r["ndcg@10"])
            out.append(
                f"- **ranker_weights 最优配比（本次合成集）**：`{best['config']}` (dense,sparse)={best.get('weights')} "
                f"nDCG@10={best['ndcg@10']}、Recall@10={best['recall@10']} → 支持回填 retrieval.yaml hybrid。"
            )
            dense_only = next((r for r in active if r["config"] == "dense_only"), None)
            sparse_only = next((r for r in active if r["config"] == "sparse_only"), None)
            if dense_only and sparse_only:
                lex = "sparse(learned)" if embedding_mode != "api" else "sparse(TF)"
                winner = lex if sparse_only["ndcg@10"] > dense_only["ndcg@10"] else "dense"
                out.append(
                    f"- **lexical vs dense 单向量**：dense_only nDCG@10={dense_only['ndcg@10']} vs "
                    f"{lex}={sparse_only['ndcg@10']} → 本次词法侧更贡献的向量={winner}"
                    f"（是否统一为 BM25 / 换 learned sparse 的判据之一）。"
                )
        else:
            out.append("- **ranker_weights 最优配比**：层 2 全部无候选，待补真实索引后复跑。")
    else:
        out.append("- **ranker_weights 最优配比**：本次未跑层 2（--no-layer2）。")
    return out


# ---------------------------------------------------------------------------
# Phase B：数据源贡献矩阵（配对 bootstrap 显著性，overall + 分桶）与 web 干扰度
# ---------------------------------------------------------------------------
_CONTRIB_HEADER = [
    "| 变体 | 指标 | Δ均值 | 95% CI | 显著 | 判定 | n |",
    "|---|---|---|---|---|---|---|",
]


def _paired_series(
    records: List[Dict[str, Any]],
    base_cfg: str,
    var_cfg: str,
    metric_keys: Sequence[str],
) -> Tuple[Dict[str, List[float]], Dict[str, List[float]]]:
    """base 与 variant 都在同 query 上非 skip 的配对序列（qid 对齐由 records 同序保证）。"""
    b: Dict[str, List[float]] = {m: [] for m in metric_keys}
    v: Dict[str, List[float]] = {m: [] for m in metric_keys}
    for rec in records:
        cfgs = rec.get("configs") or {}
        bb = cfgs.get(base_cfg)
        vv = cfgs.get(var_cfg)
        if not bb or not vv or bb.get("skipped") or vv.get("skipped"):
            continue
        for m in metric_keys:
            bm = (bb.get("metrics") or {}).get(m)
            vm = (vv.get("metrics") or {}).get(m)
            if bm is not None and vm is not None:
                b[m].append(bm)
                v[m].append(vm)
    return b, v


def _contribution_block(
    records: List[Dict[str, Any]],
    base_cfg: str,
    variants: Sequence[Tuple[str, str]],
    mode: str,
) -> List[Dict[str, Any]]:
    """variants: [(label, config_name), ...] → 逐个与 base 配对做 bootstrap，汇总行。"""
    from eval.analysis import contribution_rows

    rows: List[Dict[str, Any]] = []
    for label, cfg in variants:
        b, v = _paired_series(records, base_cfg, cfg, CONTRIB_METRIC_KEYS)
        rows += contribution_rows(b, {label: v}, mode=mode, metric_keys=CONTRIB_METRIC_KEYS)
    return rows


def _distinct_values(records: List[Dict[str, Any]], key: str) -> List[Any]:
    seen: List[Any] = []
    for rec in records:
        val = rec.get(key)
        if val is not None and val != "unknown" and val not in seen:
            seen.append(val)
    return sorted(seen)


def _compute_contrib(
    records: List[Dict[str, Any]], loo_labels: Sequence[str]
) -> Dict[str, Any]:
    """产出 LOO / Add-one 的 overall + 分桶（tag × expected_source）贡献矩阵数据。"""
    loo_variants: List[Tuple[str, str]] = [(lbl, lbl) for lbl in loo_labels]
    add_variants: List[Tuple[str, str]] = list(ADD_ONE_CHAIN)
    out: Dict[str, Any] = {
        "overall_loo": _contribution_block(records, "rrf_all", loo_variants, "leave_one_out"),
        "overall_add": _contribution_block(records, "emb_only", add_variants, "add_one_in"),
        "per_bucket": {},
    }
    for key in ("tag", "expected_source"):
        for val in _distinct_values(records, key):
            sub = [r for r in records if r.get(key) == val]
            if len(sub) < 2:  # 配对 bootstrap 至少需 2 条对齐样本；过小桶略过（不伪造显著性）
                continue
            out["per_bucket"][f"{key}={val}"] = {
                "loo": _contribution_block(sub, "rrf_all", loo_variants, "leave_one_out"),
                "add": _contribution_block(sub, "emb_only", add_variants, "add_one_in"),
            }
    return out


def _compute_web_interference(web_pairs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """web@rerank 相对无 web rerank 的配对差（add_one_in：正=web 有帮助，负且显著=挤掉本地相关块）。"""
    from eval.analysis import contribution_rows

    b: Dict[str, List[float]] = {m: [] for m in CONTRIB_METRIC_KEYS}
    w: Dict[str, List[float]] = {m: [] for m in CONTRIB_METRIC_KEYS}
    for p in web_pairs:
        nw, wv = p["no_web"], p["web"]
        if nw.get("skipped") or wv.get("skipped"):
            continue
        for m in CONTRIB_METRIC_KEYS:
            bm = (nw.get("metrics") or {}).get(m)
            wm = (wv.get("metrics") or {}).get(m)
            if bm is not None and wm is not None:
                b[m].append(bm)
                w[m].append(wm)
    if not any(b[m] for m in CONTRIB_METRIC_KEYS):
        return []
    return contribution_rows(b, {"web@rerank": w}, mode="add_one_in", metric_keys=CONTRIB_METRIC_KEYS)


def _fmt_contrib_row(r: Dict[str, Any]) -> str:
    sig = "✅" if r["significant"] else "—"
    return (
        f"| {r['label']} | {r['metric']} | {round(r['mean_diff'], 4)} | "
        f"[{round(r['ci_low'], 4)}, {round(r['ci_high'], 4)}] | {sig} | {r['verdict']} | {r['n']} |"
    )


def _render_contrib(contrib: Dict[str, Any]) -> str:
    lines: List[str] = [
        "## 数据源边际贡献矩阵（Leave-one-out + Add-one-in，配对 bootstrap 95% CI）",
        "",
        "### Leave-one-out（base=rrf_all，逐一减一路；正=该路有正贡献，负=拖后腿）",
        "",
    ]
    if contrib["overall_loo"]:
        lines += _CONTRIB_HEADER + [_fmt_contrib_row(r) for r in contrib["overall_loo"]]
    else:
        lines += ["_无可配对的 LOO 变体（相关通道全 skip 或样本不足）。_"]
    lines += ["", "### Add-one-in（base=emb_only，逐级并入通道；正=叠加有增益，负=叠加有害）", ""]
    if contrib["overall_add"]:
        lines += _CONTRIB_HEADER + [_fmt_contrib_row(r) for r in contrib["overall_add"]]
    else:
        lines += ["_无可配对的 add-one 变体。_"]
    if contrib["per_bucket"]:
        lines += ["", "### 分桶贡献（tag × expected_source；单桶样本可能 <15，仅定性方向）", ""]
        for bucket, blk in contrib["per_bucket"].items():
            lines += [f"#### {bucket}", ""]
            rows = blk["loo"] + blk["add"]
            if rows:
                lines += _CONTRIB_HEADER + [_fmt_contrib_row(r) for r in rows]
            else:
                lines += ["_该桶无可配对样本。_"]
    lines += ["", "> 判定口径：CI 含 0 → 不显著（冗余/噪声），经不渲染为‘更优’。"]
    return "\n".join(lines) + "\n"


def _render_param_scan(
    param_rows: List[Dict[str, Any]], base_k: int, base_weights: Dict[str, float]
) -> str:
    lines: List[str] = [
        "## 参数敏感性扫描（rrf.k 网格 + 通道权重单因子，基于 rrf_all）",
        "",
        "| 参数档 | Recall@5 | Recall@10 | MRR | HitRate@5 | nDCG@10 | 平均返回 | 状态 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in param_rows:
        status = "skipped" if r["skipped"] else ""
        lines.append(
            f"| {r['config']} | {r['recall@5']} | {r['recall@10']} | {r['mrr']} | "
            f"{r['hit_rate@5']} | {r['ndcg@10']} | {r['avg_returned']} | {status} |"
        )
    active = [r for r in param_rows if not r["skipped"]]
    if active:
        best = max(active, key=lambda r: r["ndcg@10"])
        lines += [
            "",
            f"- 建议档（本次 nDCG@10 最高）：`{best['config']}` → nDCG@10={best['ndcg@10']}、"
            f"Recall@10={best['recall@10']}（线上基线 k={base_k}, weights={base_weights}）。供回填参考，非自动生效。",
        ]
    else:
        lines += ["", "_参数扫描全部无候选，待补真实索引后复跑。_"]
    return "\n".join(lines) + "\n"


def _render_web(web_rows: List[Dict[str, Any]], web_hit: int, total: int, without_rerank: bool) -> str:
    lines: List[str] = ["## web@rerank 异构干扰度（web 不进 RRF，只在 rerank 合流）", ""]
    if without_rerank:
        lines += ["_--web-snapshot 未配 --with-rerank，web 臂未评测。_"]
        return "\n".join(lines) + "\n"
    lines += [f"- web 快照命中：{web_hit}/{total} query（未命中的 query 不产 web 臂，不伪造）。", ""]
    if web_rows:
        lines += [
            "| 变体（加 web 相对不加） | 指标 | Δ均值 | 95% CI | 显著 | 判定 | n |",
            "|---|---|---|---|---|---|---|",
        ]
        lines += [_fmt_contrib_row(r) for r in web_rows]
        lines += ["", "> 负且显著 = web 挤掉本地相关块（干扰）；正且显著 = web 在 rerank 公平胜出；含 0 = 无显著影响。"]
    else:
        lines += ["_无可配对的 web rerank 样本（快照为空或全 skip）。_"]
    return "\n".join(lines) + "\n"


def _render_onboarding() -> str:
    lines: List[str] = ["## 新增数据源接入清单（插拔契约，来自 eval/source_adapter.py）", ""]
    lines += [f"- {s}" for s in onboarding_checklist()]
    lines += ["", f"- 当前登记进 RRF 的同构通道：{list(rrf_channels())}；异构源需声明 merge=rerank 且不进 RRF。"]
    return "\n".join(lines) + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    deps = _load_deps()
    golden_path = Path(args.golden)
    out_root = Path(args.out)

    collection_name = deps["milvus_config"].chunks_collection
    print(f"[route-ablation] 目标集合：{collection_name}")

    # ---------- 环境守卫（Milvus 不可达 / 集合不存在 → return 1，不吞异常） ----------
    client = deps["get_milvus_client"]()
    if client is None:
        print(
            f"错误：无法连接 Milvus（{deps['milvus_config'].milvus_url}）。"
            "请先启动 Milvus 并确认 MILVUS_URL 配置。",
            file=sys.stderr,
        )
        return 1
    if not client.has_collection(collection_name=collection_name):
        print(
            f"错误：Milvus 集合 {collection_name} 不存在。请先运行 "
            f"`python eval/seed_synthetic_corpus.py` 建立合成索引。",
            file=sys.stderr,
        )
        return 1

    config_hash = deps["compute_config_hash"]()
    deps["init_tracing"](config_hash=config_hash, collection=collection_name)

    # ---------- 加载 golden ----------
    queries = deps["load_golden_queries"](golden_path)
    if args.limit is not None:
        queries = queries[: args.limit]
    if not queries:
        print(f"错误：golden 数据集 {golden_path} 无有效 query。", file=sys.stderr)
        return 1
    print(f"[route-ablation] 加载 {len(queries)} 条 golden query（来源：{golden_path}）")

    embedding_mode = deps["embedding_config"].embedding_mode or "local"
    retrieval_cfg = deps["retrieval_cfg"]

    # ---------- 稀疏编码一致性 fail-fast（防止导入/查询 EMBEDDING_MODE 不一致→层2 静默作废） ----------
    if not args.skip_sparse_check:
        from knowledge_service.utils.sparse_consistency import (
            SparseEncodingMismatchError,
            assert_sparse_encoding_consistent,
        )

        try:
            assert_sparse_encoding_consistent(deps["get_milvus_client"](), collection_name, use_cache=False)
        except SparseEncodingMismatchError as e:
            print(f"[route-ablation] 稀疏编码门禁未通过，fail-fast（勿跑，否则层2 结论无效）：\n  {e}", file=sys.stderr)
            return 1
        except Exception as e:  # noqa: BLE001 —— canary 自身环境异常（非编码错配）不应阻断评测，告警续跑
            print(f"[route-ablation] 警告：稀疏编码 canary 无法执行（非错配判定），跳过校验继续：{e}", file=sys.stderr)

    # id 别名归一（泛化）：对声明 needs_id_alias 的同构源（如 kg）把非 Milvus 命名空间 id 归一到
    # canonical，使其与 emb/hyde 在同一 relevant 基准公平比较。无 sidecar → 不归一（该路 0/skip）。
    id_maps = _build_id_maps(args)
    kg_map = id_maps.get("kg", {})
    kg_aliased = bool(kg_map) and not args.no_kg
    if not args.no_kg:
        if kg_map:
            print(f"[route-ablation] KG 别名启用：{len(kg_map)} 条 kg:: id → canonical")
        else:
            print(
                f"[route-ablation] 未找到 KG 别名 sidecar（{args.kg_id_map}），KG id 不归一"
                "→ kg 召回将因命名空间不匹配为 0（需先跑 seed --with-kg）。",
                file=sys.stderr,
            )

    # 异构 web 快照（--web-snapshot）：仅在 --with-rerank 时有意义（web 不进 RRF，只在 rerank 合流）。
    web_snapshot: Dict[str, List[Dict[str, Any]]] = {}
    web_requested = bool(args.web_snapshot)
    web_without_rerank = web_requested and not args.with_rerank
    if web_requested and args.with_rerank:
        web_snapshot = _load_web_snapshot(Path(args.web_snapshot))
        print(f"[route-ablation] web 快照加载 {len(web_snapshot)} 条 query（异构，仅进 rerank 臂）")
    elif web_without_rerank:
        print(
            "[route-ablation] 警告：--web-snapshot 需配 --with-rerank（web 不进 RRF），本次跳过 web 臂评测。",
            file=sys.stderr,
        )

    # 贡献矩阵 / 参数扫描的基线通道与权重（读同一线上 retrieval.yaml）
    base_weights = _channel_weights(retrieval_cfg)
    base_k = int(getattr(retrieval_cfg.rrf, "k", 60))
    rrf_all_channels = ROUTE_CONFIGS["rrf_all"]
    loo_configs = leave_one_out_configs("rrf_all") if args.with_contrib else {}
    rrf_channel_names = tuple(c for c in rrf_channels() if c in ROUTE_CONFIGS["rrf_all"])
    param_labels: List[str] = []
    if args.param_scan:
        param_labels += [f"k={kk}" for kk in RRF_K_SCAN]
        for ch in rrf_channel_names:
            for f in CHANNEL_WEIGHT_FACTORS:
                param_labels.append(f"w:{ch}x{f}")

    # ---------- 逐条：每路只检索一次，派生层1 + 层2 (+ 贡献/参数扫描) ----------
    per_route: Dict[str, List[Dict[str, Any]]] = {c: [] for c in ROUTE_ORDER}
    if args.with_rerank:
        per_route["rrf_all+rerank"] = []
    per_param: Dict[str, List[Dict[str, Any]]] = {lbl: [] for lbl in param_labels}
    layer2_order, _ = _layer2_order_and_weights(retrieval_cfg)
    per_layer2: Dict[str, List[Dict[str, Any]]] = {lbl: [] for lbl in layer2_order}
    skipped_notes: Dict[str, str] = {}
    route_channels: Dict[str, set] = {}
    all_query_records: List[Dict[str, Any]] = []
    # 贡献矩阵用的 per-query 记录：{qid, tag, expected_source, configs: {name: {metrics, skipped}}}
    contrib_records: List[Dict[str, Any]] = []
    web_hit_count = 0
    # web 干扰度配对（仅在快照命中且 --with-rerank 时收集）：{no_web:{metrics,skipped}, web:{...}}
    web_pairs: List[Dict[str, Any]] = []

    for idx, item in enumerate(queries, start=1):
        qid = item.get("qid", f"q{idx:03d}")
        query = item.get("query", "")
        item_name = item.get("item_name", "")
        relevant_ids = [str(x) for x in (item.get("relevant_chunk_ids") or [])]
        grades = item.get("grade") or {}

        state = _build_state(query, item_name)
        expr = deps["build_retrieval_filter"](item_names=state["item_names"])

        # 查询向量（一次），供 embedding 路 + 层 2 复用
        emb = deps["generate_embeddings"]([query])
        dense_vec = emb.get("dense")[0]
        sparse_vec = emb.get("sparse")[0]

        dense_default = float(retrieval_cfg.hybrid.dense_weight)
        sparse_default = float(retrieval_cfg.hybrid.sparse_weight)

        # 缓存三路候选（embedding 必跑；hyde/kg 按开关）
        routes: Dict[str, List[Dict[str, Any]]] = {}
        routes["embedding"] = _embedding_route(
            deps, dense_vec, sparse_vec, expr, (dense_default, sparse_default), args.max_results
        )
        if not args.no_hyde:
            try:
                hyde_res = deps["node_search_embedding_hyde"](state) or {}
                routes["hyde"] = deps["as_entity_list"](hyde_res.get("hyde_embedding_chunks"))
            except Exception as e:  # noqa: BLE001 —— HyDE 为可选路（依赖 LLM），异常面宽，降级为该路空→skipped
                print(f"[route-ablation] {qid} HyDE 异常，跳过：{e}", file=sys.stderr)
                routes["hyde"] = []
        else:
            routes["hyde"] = []
        if not args.no_kg:
            try:
                kg_res = deps["node_query_kg"](state) or {}
                routes["kg"] = deps["as_entity_list"](kg_res.get("kg_chunks"))
            except Exception as e:  # noqa: BLE001 —— KG 为可选路（依赖 Neo4j），异常面宽，降级为该路空→skipped
                print(f"[route-ablation] {qid} KG 异常，跳过：{e}", file=sys.stderr)
                routes["kg"] = []
        else:
            routes["kg"] = []

        # 泛化 id 别名：对每个声明 needs_id_alias 的同构源应用其 sidecar（归一到 canonical）
        for _ch, _m in id_maps.items():
            if _m and routes.get(_ch):
                routes[_ch] = alias_ids(routes[_ch], _m)

        # web 异构候选（仅 --with-rerank + 快照命中本 query 时不为 None）
        web_docs: Optional[List[Dict[str, Any]]] = None
        if web_snapshot:
            matched = web_snapshot.get(query.strip())
            if matched is not None:
                web_docs = matched
                web_hit_count += 1

        # 层 1
        route_out = _run_layer1(deps, routes, relevant_ids, grades, args, state, web_docs=web_docs)
        # web@rerank 干扰配对（base=无 web rerank，variant=有 web rerank，同一 query 对齐）
        if web_docs is not None and WEB_ARM in route_out and "rrf_all+rerank" in route_out:
            web_pairs.append(
                {
                    "no_web": {
                        "metrics": route_out["rrf_all+rerank"]["metrics"],
                        "skipped": route_out["rrf_all+rerank"].get("skipped", False),
                    },
                    "web": {
                        "metrics": route_out[WEB_ARM]["metrics"],
                        "skipped": route_out[WEB_ARM].get("skipped", False),
                    },
                }
            )
        for config, rec in route_out.items():
            if config not in per_route:
                per_route[config] = []
            per_route[config].append(
                {
                    "metrics": rec["metrics"],
                    "returned": rec["returned"],
                    "skipped": rec.get("skipped", False),
                }
            )
            if rec.get("channels"):
                route_channels.setdefault(config, set()).update(rec["channels"])
            if rec.get("skipped") and rec.get("reason"):
                skipped_notes.setdefault(config, rec["reason"])

        # Phase B：数据源边际贡献（LOO 变体）+ per-query 记录（供 overall/分桶 配对显著性）
        if args.with_contrib:
            loo_out = {
                label: _subset_fusion_record(
                    deps, routes, channels, base_weights, base_k, args.max_results, relevant_ids, grades
                )
                for label, channels in loo_configs.items()
            }
            # base/变体所需标准配置（rrf_all / emb_only / rrf_emb_hyde）+ 刚算的 loo:* 一起入记录
            cfgs = {
                name: route_out[name]
                for name in ("rrf_all", "emb_only", "rrf_emb_hyde")
                if name in route_out
            }
            cfgs.update(loo_out)
            tags = item.get("tags") or []
            contrib_records.append(
                {
                    "qid": qid,
                    "tag": (tags[0] if tags else item.get("tag")) or "unknown",
                    "expected_source": item.get("expected_source") or "unknown",
                    "configs": {
                        name: {"metrics": r["metrics"], "skipped": r.get("skipped", False)}
                        for name, r in cfgs.items()
                    },
                }
            )

        # Phase B：参数敏感性扫描（rrf.k 网格 + 通道权重单因子），均基于 rrf_all 通道集
        if args.param_scan:
            for kk in RRF_K_SCAN:
                rec = _subset_fusion_record(
                    deps, routes, rrf_all_channels, base_weights, kk, args.max_results, relevant_ids, grades
                )
                per_param[f"k={kk}"].append(
                    {"metrics": rec["metrics"], "returned": rec["returned"], "skipped": rec.get("skipped", False)}
                )
            for ch in rrf_channel_names:
                for factor in CHANNEL_WEIGHT_FACTORS:
                    w = dict(base_weights)
                    w[ch] = float(base_weights.get(ch, 1.0)) * factor
                    rec = _subset_fusion_record(
                        deps, routes, rrf_all_channels, w, base_k, args.max_results, relevant_ids, grades
                    )
                    per_param[f"w:{ch}x{factor}"].append(
                        {"metrics": rec["metrics"], "returned": rec["returned"], "skipped": rec.get("skipped", False)}
                    )

        # 层 2
        if not args.no_layer2:
            layer2_out = _run_layer2(deps, dense_vec, sparse_vec, expr, relevant_ids, grades, args)
            for label, rec in layer2_out.items():
                per_layer2[label].append(
                    {
                        "metrics": rec["metrics"],
                        "returned": rec["returned"],
                        "skipped": rec.get("skipped", False),
                    }
                )

        all_query_records.append(
            {
                "qid": qid,
                "query": query,
                "item_name": item_name,
                "relevant_ids": relevant_ids,
                "layer1": {c: {"ids": r["ids"], "metrics": r["metrics"], "skipped": r.get("skipped", False)}
                           for c, r in route_out.items()},
                "layer2": (
                    {lbl: {"ids": r["ids"], "metrics": r["metrics"]} for lbl, r in layer2_out.items()}
                    if not args.no_layer2
                    else {}
                ),
            }
        )
        print(f"[route-ablation] {idx}/{len(queries)} {qid} 完成")

    # ---------- 聚合 ----------
    route_rows = aggregate_route_rows(per_route, list(per_route.keys()))
    layer2_rows = None if args.no_layer2 else aggregate_route_rows(per_layer2, layer2_order)
    # 给层 2 行附回 weights（便于报告展示）
    if layer2_rows is not None:
        _, wmap = _layer2_order_and_weights(retrieval_cfg)
        for row in layer2_rows:
            row["weights"] = list(wmap.get(row["config"], ()))

    # Phase B：参数扫描聚合（与层表同口径均值）+ 数据源贡献矩阵 + web 干扰度
    param_rows = aggregate_route_rows(per_param, param_labels) if args.param_scan else None
    contrib = _compute_contrib(contrib_records, list(loo_configs.keys())) if args.with_contrib else None
    web_rows = _compute_web_interference(web_pairs) if (args.web_snapshot and args.with_rerank) else None

    # ---------- 输出 ----------
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    run_id = f"{timestamp}_{config_hash}"
    run_dir = out_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    md = _render_report(
        run_id,
        config_hash,
        collection_name,
        len(queries),
        args,
        embedding_mode,
        route_rows,
        layer2_rows,
        skipped_notes,
        {k: sorted(v) for k, v in route_channels.items()},
        kg_aliased,
    )
    # Phase B 附加章节（仅相应开关时追加，保持默认报告与历史 run 形状一致）
    if contrib is not None:
        md += "\n" + _render_contrib(contrib)
    if param_rows is not None:
        md += "\n" + _render_param_scan(param_rows, base_k, base_weights)
    if web_rows is not None:
        md += "\n" + _render_web(web_rows, web_hit_count, len(queries), web_without_rerank)
    elif web_without_rerank:
        md += (
            "\n## web@rerank 异构干扰度\n\n"
            "_--web-snapshot 需配 --with-rerank（web 不进 RRF，只在 rerank 合流），本次未评测 web 臂。_\n"
        )
    md += "\n" + _render_onboarding()

    report_path = run_dir / REPORT_FILE
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(md)

    with open(run_dir / PER_QUERY_FILE, "w", encoding="utf-8") as f:
        for rec in all_query_records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(f"\n[route-ablation] 完成：{report_path}")
    for row in route_rows:
        tag = " (skipped)" if row["skipped"] else ""
        print(
            f"[route-ablation] 层1 {row['config']}: ndcg@10={row['ndcg@10']} "
            f"recall@10={row['recall@10']} avg_returned={row['avg_returned']}{tag}"
        )
    if contrib is not None:
        print(
            f"[route-ablation] 贡献矩阵：LOO {len(contrib['overall_loo'])} 行、"
            f"Add-one {len(contrib['overall_add'])} 行、分桶 {len(contrib['per_bucket'])} 个"
        )
    if web_rows is not None:
        print(f"[route-ablation] web@rerank 干扰度：命中 {web_hit_count}/{len(queries)} query")
    if layer2_rows is not None:
        for row in layer2_rows:
            tag = " (skipped)" if row["skipped"] else ""
            print(
                f"[route-ablation] 层2 {row['config']}{row.get('weights')}: "
                f"ndcg@10={row['ndcg@10']} recall@10={row['recall@10']}{tag}"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
