# -*- coding: utf-8 -*-
"""L1 轻量意图分类器（嵌入相似度 + 关键词降级）。

从 deepagents ``agent/intent/classifier.py`` 下沉到内核：统一作为双轨共用的
L1 粗分类原语。依赖 ``agent_core.memory.embedder.LocalEmbedder``（已在内核）与
numpy（懒加载，遵循内核框架无关护栏）。

逻辑：
1. chitchat 关键词短链短路 -> CHITCHAT（极高置信）。
2. 否则用 LocalEmbedder 计算 query 与各意图原型向量的余弦相似度，取 top1。
3. 原型数据缺失或嵌入失败时退化为关键词匹配（keyword_rule）。
"""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any

from agent_core.intent.models import (
    CLARIFY_THRESHOLD,
    IntentCandidate,
    IntentLabel,
    IntentResult,
)

_DATA_PATH = Path(__file__).resolve().parent / "data" / "prototypes.json"

# chitchat 关键词短链：命中即直接判为 CHITCHAT，跳过嵌入计算。
#
# 分两组以避免对含礼貌词的业务问题误路由（审计 P2 #十二）：
#  - STRONG：强意图词，原文 substring 命中即短路（如"你是谁""在吗"几乎不会出现在
#    正常业务问句中）。
#  - WEAK：礼貌/告别词（谢谢/hi/bye 等）。这类词常出现在正常业务句里（"谢谢你帮我
#    分析合同"），若用 substring 会误判为 CHITCHAT 跳过 embedding。改为仅在 query
#    去除空白与标点后整体等于该词（即纯问候/礼貌语）时才短路。
#
# WS-6：词表外置到 data/prototypes.json 的 ``chitchat_shortcuts`` 段（数据驱动，
# 新增词不再改代码）；下方常量仅作数据缺失时的兜底。
_CHITCHAT_STRONG_FALLBACK = [
    "你好", "您好", "在吗", "你是谁", "你是机器人吗",
    "who are you", "what are you", "are you a bot",
]
_CHITCHAT_WEAK_FALLBACK = [
    "谢谢", "感谢", "再见", "拜拜", "哈哈", "嘿",
    "hi", "hello", "hey", "thanks", "thank you", "bye",
]


def _is_pure_weak_chitchat(query: str) -> bool:
    """WEAK 词仅当 query（去空白/标点后）整体等于该词时才判 chitchat。"""
    import re

    q = query.strip().lower()
    # 去除所有非字母数字 unicode 字符（含中英文标点、空白），再比较
    core = re.sub(r"[^\w\u4e00-\u9fff]+", "", q)
    _strong, weak = _chitchat_words()
    return core in {k.lower() for k in weak}


@lru_cache(maxsize=1)
def _load_prototypes() -> dict[str, Any]:
    """加载原型数据（意图 -> 样例文本列表 + 预计算原型向量）。

    WS-6：``lru_cache`` 避免每次请求读盘；测试/数据热更经
    ``_load_prototypes.cache_clear()`` 复位。
    """
    with open(_DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def _chitchat_words() -> tuple[list[str], list[str]]:
    """读数据文件中的 chitchat 短链词表（strong, weak）；缺失时回退代码兜底。"""
    try:
        shortcuts = _load_prototypes().get("chitchat_shortcuts") or {}
        strong = list(shortcuts.get("strong") or [])
        weak = list(shortcuts.get("weak") or [])
        if strong and weak:
            return strong, weak
    except Exception:
        pass
    return list(_CHITCHAT_STRONG_FALLBACK), list(_CHITCHAT_WEAK_FALLBACK)


@lru_cache(maxsize=1)
def _embedder():
    """懒加载 LocalEmbedder（避免导入期触发重模型加载）。"""
    from agent_core.memory.embedder import LocalEmbedder

    return LocalEmbedder()


def _cosine(a, b) -> float:
    import numpy as np

    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    denom = math.sqrt(float(np.dot(a, a))) * math.sqrt(float(np.dot(b, b)))
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


@lru_cache(maxsize=128)
def _prototype_vector(intent: str, text: str) -> tuple:
    """缓存单个原型文本向量（按意图+文本）。"""
    return tuple(_embedder().embed(text))


def _intent_prototype_vector(intent: str, samples: list[str]) -> tuple:
    """意图原型向量 = 样例向量均值。"""
    import numpy as np

    vecs = [_prototype_vector(intent, s) for s in samples]
    return tuple(np.mean(np.asarray(vecs, dtype=float), axis=0).tolist())


def _keyword_rule(query: str) -> IntentResult | None:
    """关键词降级：当嵌入层不可用或原型缺失时启用。"""
    strong, _weak = _chitchat_words()
    q = query.lower()
    if any(k in q for k in strong) or _is_pure_weak_chitchat(query):
        return IntentResult(
            primary=IntentLabel.CHITCHAT, confidence=0.7,
            candidates=[IntentCandidate(IntentLabel.CHITCHAT, 0.7)],
            source="l1_keyword",
        )
    return None


def _fallback_result() -> IntentResult:
    """嵌入层不可用/原型全空时的兜底：DIRECT + need_clarify。"""
    return IntentResult(
        primary=IntentLabel.DIRECT, confidence=0.4,
        candidates=[IntentCandidate(IntentLabel.DIRECT, 0.4)],
        source="l1_fallback", need_clarify=True,
    )


def classify_l1(query: str) -> IntentResult:
    """L1 嵌入粗分类（**同步阻塞**：内含嵌入计算，async 链路请用 classify_l1_async）。

    返回 ``IntentResult``（source 为 l1 / l1_keyword / l1_fallback）。
    need_clarify 在置信度 < CLARIFY_THRESHOLD 时置位。
    """
    # 0. 空/空白 query 无分类意义，直接兜底 DIRECT + need_clarify
    if not query or not query.strip():
        return _fallback_result()

    # 1. chitchat 短链
    strong, _weak = _chitchat_words()
    q_low = query.lower()
    if any(k in q_low for k in strong) or _is_pure_weak_chitchat(query):
        return IntentResult(
            primary=IntentLabel.CHITCHAT, confidence=0.95,
            candidates=[IntentCandidate(IntentLabel.CHITCHAT, 0.95)],
            source="l1_keyword",
        )

    # 2. 嵌入相似度
    try:
        data = _load_prototypes()
        proto = data.get("prototypes", {})
        q_vec = tuple(_embedder().embed(query))
        scored = []
        for intent_str, samples in proto.items():
            if not samples:
                continue
            pv = _intent_prototype_vector(intent_str, samples)
            sim = _cosine(q_vec, pv)
            scored.append((IntentLabel.from_str(intent_str), sim))
        scored.sort(key=lambda x: x[1], reverse=True)
        if not scored:
            return _keyword_rule(query) or _fallback_result()
        top = scored[0]
        candidates = [IntentCandidate(i, float(c)) for i, c in scored[:3]]
        return IntentResult(
            primary=top[0], confidence=float(top[1]),
            candidates=candidates, source="l1",
            need_clarify=top[1] < CLARIFY_THRESHOLD,
        )
    except Exception:
        # 3. 嵌入失败时降级关键词
        return _keyword_rule(query) or _fallback_result()


async def classify_l1_async(query: str) -> IntentResult:
    """``classify_l1`` 的异步入口（WS-6）：经 ``asyncio.to_thread`` 移出事件循环。

    历史事故教训：``to_thread`` 只能包**同步**函数（误包 async 函数会导致
    coroutine 从未被 await 的静默失效），此处包裹的 classify_l1 为纯同步。
    """
    import asyncio

    return await asyncio.to_thread(classify_l1, query)
