# -*- coding: utf-8 -*-
"""
config_hash 单一实现（方案 §7.5 实验追踪归因）。

职责：读 knowledge_service/conf/retrieval.yaml + rerank.yaml 内容 + 集合名，
计算短哈希（sha256 前 8 位），供两处**共同引用**：
- 生产运行时：``main.py`` 经 ``init_tracing(config_hash=...)`` 注入统一 span 属性
  （内核 agent_core.tracing 框架无关，要求宿主注入真实值）；
- 评测链路：``eval/run_eval.py`` / ``eval/run_ablation.py`` 标记实验配置版本。

历史备注：本函数原住 ``eval/run_eval.py``，被生产代码反向 import，
形成「生产 → 评测 harness」架构倒挂，且 wheel only-include=knowledge_service
不含 eval/ 导致打包部署缺模块；2026-09-25 上收至 conf 包（见
docs/plans/plan-workspace-toplevel-eval-disambiguation-2026-09-25.md）。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List

from knowledge_service.conf.milvus_config import milvus_config
from knowledge_service.conf.rerank_config import rerank_cfg  # TD-9：统一引用 yaml 配置
from knowledge_service.conf.retrieval_config import retrieval_cfg  # TD-9：同上

# ---------------------------------------------------------------------------
# TD-9：运行时配置快照（config_hash 的兜底来源），统一从 retrieval.yaml / rerank.yaml 读取。
# 不再硬编码超参，避免与线上配置漂移。yaml 缺失时退化为空 dict（compute_config_hash 直接读文件内容）。
# ---------------------------------------------------------------------------
_RUNTIME_BASELINE: Dict[str, Any] = {
    "rrf": {
        "k": retrieval_cfg.rrf.k,
        "max_results": retrieval_cfg.rrf.max_results,
        "weights": list(retrieval_cfg.rrf.weights.values()) if hasattr(retrieval_cfg.rrf.weights, 'values') else retrieval_cfg.rrf.weights,
    },
    "hybrid": {
        "dense_weight": retrieval_cfg.hybrid.dense_weight,
        "sparse_weight": retrieval_cfg.hybrid.sparse_weight,
    },
    "rerank_dynamic_topk": {
        "gap_ratio": rerank_cfg.dynamic_topk.gap_ratio,
        "gap_abs": rerank_cfg.dynamic_topk.gap_abs,
        "min_k": rerank_cfg.dynamic_topk.min_k,
        "max_k": rerank_cfg.dynamic_topk.max_k,
    },
}


def _sha256_hex(content: str) -> str:
    """返回内容 sha256 前 8 位十六进制，作为短 config_hash。"""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:8]


def compute_config_hash() -> str:
    """
    计算当前检索配置哈希（实验/trace 归因用）。

    优先：knowledge_service/conf/retrieval.yaml + rerank.yaml（M3 起存在）内容 + 集合名。
    兜底：M2 硬编码基线快照 + 集合名（yaml 尚不存在时退化）。
    """
    conf_dir = Path(__file__).resolve().parent
    parts: List[str] = [milvus_config.chunks_collection]
    yaml_files = [conf_dir / "retrieval.yaml", conf_dir / "rerank.yaml"]
    any_yaml = False
    for yf in yaml_files:
        if yf.exists():
            any_yaml = True
            parts.append(yf.read_text(encoding="utf-8"))
    if not any_yaml:
        parts.append(json.dumps(_RUNTIME_BASELINE, sort_keys=True, ensure_ascii=False))
    return _sha256_hex("\n".join(parts))
