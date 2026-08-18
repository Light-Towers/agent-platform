"""L1 粗分类器：embedding + 原型向量余弦相似度。

embedding 后端统一委托 agent-core 的 ``LocalEmbedder``（bge-small-zh-v1.5），
与 Phase 5 缓存 embedding 解耦，永不切换。原型向量 = 每类 20 条典型 query 的
embedding 均值，来源独立于评测集。目标延迟 <10ms（模型加载 ~2s，推理 <10ms 需 benchmark）。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import numpy as np
from agent_core.logging import get_logger

logger = get_logger(__name__)

_PROTOTYPES_PATH = Path(__file__).parent / "prototypes.json"
_MODEL_NAME = os.getenv("INTENT_EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")

_embedder: Any = None
_prototype_vectors: dict[str, np.ndarray] | None = None
_intent_labels: list[str] = []


def _load_embedder() -> Any:
    """懒加载 sentence-transformers 模型（委托 agent-core LocalEmbedder）。

    复用内核的本地 embedder 单例，避免 deepagents 与内核重复加载模型实例。
    """
    global _embedder
    if _embedder is not None:
        return _embedder
    try:
        from agent_core.memory.embedder import LocalEmbedder  # noqa: PLC0415

        _embedder = LocalEmbedder(_MODEL_NAME)
        logger.info("L1 embedding 模型已加载（内核 LocalEmbedder）: %s", _MODEL_NAME)
    except ImportError:
        logger.warning("sentence-transformers 未安装，L1 降级为关键词匹配")
        _embedder = None
    except Exception as e:
        logger.warning("L1 embedding 模型加载失败: %s，降级为关键词匹配", e)
        _embedder = None
    return _embedder


def _build_prototypes() -> dict[str, np.ndarray]:
    """从 prototypes.json 构建原型向量（每类 embedding 均值）。"""
    global _prototype_vectors, _intent_labels

    if _prototype_vectors is not None:
        return _prototype_vectors

    with open(_PROTOTYPES_PATH, encoding="utf-8") as f:
        proto_data = json.load(f)

    embedder = _load_embedder()
    _prototype_vectors = {}

    if embedder is None:
        _intent_labels = list(proto_data.keys())
        for label in _intent_labels:
            _prototype_vectors[label] = np.array([])
        return _prototype_vectors

    for label, queries in proto_data.items():
        embeddings = embedder.embed(queries)
        mean_vec = np.mean(embeddings, axis=0)
        norm = np.linalg.norm(mean_vec)
        if norm > 0:
            mean_vec = mean_vec / norm
        _prototype_vectors[label] = mean_vec

    _intent_labels = list(_prototype_vectors.keys())
    logger.info("L1 原型向量已构建: %s", _intent_labels)
    return _prototype_vectors


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """余弦相似度（向量已归一化时等价于点积）。"""
    if a.size == 0 or b.size == 0:
        return 0.0
    return float(np.dot(a, b))


def _keyword_fallback(query: str) -> list[tuple[str, float]]:
    """无 embedding 模型时的关键词降级。"""
    keywords = {
        "text_to_sql": ["查询", "统计", "列出", "计算", "排序", "分组", "数量", "金额", "订单", "销售"],
        "rag_knowledge": ["流程", "2么", "规定", "制度", "手册", "标准", "规范", "在哪", "如何申请"],
        "customer_service": ["退换", "退款", "物流", "发货", "发票", "售后", "客服", "损坏", "丢件"],
        "web_search": ["最新", "新闻", "趋势", "搜索", "查找", "动态", "热点", "行业"],
        "chitchat": ["你好", "谢谢", "再见", "早上好", "晚安", "笑话", "聊天"],
    }
    scores = []
    for label, kws in keywords.items():
        score = sum(1 for kw in kws if kw in query) / max(len(kws), 1)
        scores.append((label, score))
    scores.sort(key=lambda x: x[1], reverse=True)
    return scores[:3]


def classify(query: str, top_k: int = 3) -> dict[str, Any]:
    """L1 粗分类。

    Args:
        query: 用户查询文本
        top_k: 返回 top-K 候选

    Returns:
        {
            "primary": {"intent": "text_to_sql", "confidence": 0.92},
            "candidates": [{"intent": "...", "confidence": ...}, ...],
            "source": "l1",
        }
    """
    prototypes = _build_prototypes()

    if _embedder is None:
        scores = _keyword_fallback(query)
        candidates = [{"intent": label, "confidence": float(score)} for label, score in scores]
        primary = candidates[0] if candidates else {"intent": "unknown", "confidence": 0.0}
        return {"primary": primary, "candidates": candidates[:top_k], "source": "l1_keyword"}

    query_vec = np.array(_embedder.embed([query])[0])

    scores = []
    for label, proto_vec in prototypes.items():
        sim = _cosine_similarity(query_vec, proto_vec)
        scores.append({"intent": label, "confidence": max(0.0, sim)})

    scores.sort(key=lambda x: x["confidence"], reverse=True)
    return {
        "primary": scores[0] if scores else {"intent": "unknown", "confidence": 0.0},
        "candidates": scores[:top_k],
        "source": "l1",
    }


def is_chitchat(query: str, threshold: float = 0.8) -> bool:
    """快速判断是否为闲聊（short-circuit 用）。"""
    result = classify(query)
    primary = result["primary"]
    return primary["intent"] == "chitchat" and primary["confidence"] >= threshold


def get_intent_labels() -> list[str]:
    """返回所有意图标签。"""
    if not _intent_labels:
        _build_prototypes()
    return list(_intent_labels)
