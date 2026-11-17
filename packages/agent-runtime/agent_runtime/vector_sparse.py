# -*- coding: utf-8 -*-
"""agent_runtime/vector_sparse.py —— 零依赖中英稀疏向量生成器（B 路线共享件）。

来源与同步纪律（改动必须两侧同步）：
    本文件是 applications/knowledge-service/knowledge_service/lm/sparse_vectorizer.py
    （M8，B 路线核心）的**逐算法镜像端口**：分词、md5 token id、TF 权重、L2 归一化
    必须与 KS 侧完全一致 —— 两侧各写一半（KS 写文档稀疏向量、平台侧生成查询稀疏
    向量），token id 空间不一致时混合检索的稀疏路会静默失效（查询打不中文档词）。

为什么落 agent-runtime 而不是让 agent_server 复制一份：
    稀疏向量生成是纯 stdlib、与业务无关的通用能力；放共享层保证「同一算法只有
    一份实现」（横切关注点全局优先）。KS 侧迁移到本件待其检索基线解冻后另行
    立项（ADR-0009：KS 检索回归基线已冻结，不在本次统一范围内动它）。

设计要点（与 KS 侧逐条对齐，勿单侧改动）：
1. 分词（导入与检索共用同一实现，保证 doc/query token 空间一致）：
   - 英文/数字：连续 [A-Za-z0-9] 词元（含 `-`/`_` 连接的产品型号，如 "bge-m3"），统一小写；
   - 中文：连续 CJK 串 —— 单字直接输出；2 字直接整词；≥3 字输出「重叠 bigram + 整词（≤8 字）」；
   - 标点/空白天然分隔，不产生词元。
2. token → id：`hashlib.md5` 前 8 位 hex → int，掩码到 int32 正区间（`& 0x7FFFFFFF`）。
   **严禁使用内置 hash()**（PYTHONHASHSEED 随机化导致跨进程 id 不一致）。
3. 权重：词频 TF，最后 L2 归一化（与 BGE-M3 原生 SPLADE 稀疏语义对齐）。
"""

from __future__ import annotations

import hashlib
import math
import re

# 连续 CJK（基本汉字区）串：用于中文 bigram / 整词切分
_CJK_RE = re.compile(r"[\u4e00-\u9fff]+")
# 英文/数字词元（含 -_ 连接，覆盖 bge-m3 / HAK-180 等产品型号形态）
_WORD_RE = re.compile(r"[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*")
# 整词保留上限（超过该长度的 CJK 串只出 bigram，避免超长词元稀释权重）
_MAX_CJK_WHOLE_LEN = 8


def _token_id(token: str) -> int:
    """将词元映射为稳定非负 int32 id（跨进程一致；与 KS 侧同一 md5 口径）。"""
    digest = hashlib.md5(token.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) & 0x7FFFFFFF


def tokenize(text: str) -> list[str]:
    """将文本切分为词元列表（英文小写 + 中文 bigram/整词）。"""
    tokens: list[str] = []
    for m in _WORD_RE.finditer(text or ""):
        tokens.append(m.group(0).lower())
    for m in _CJK_RE.finditer(text or ""):
        run = m.group(0)
        if len(run) == 1:
            tokens.append(run)
        elif len(run) == 2:
            tokens.append(run)
        else:
            # 重叠 bigram：保留相邻字符共现信息（短查询命中率高于纯整词）
            tokens.extend(run[i : i + 2] for i in range(len(run) - 1))
            # 短整词整体保留：命中完整产品名/术语
            if len(run) <= _MAX_CJK_WHOLE_LEN:
                tokens.append(run)
    return tokens


def build_sparse_vector(text: str) -> dict[int, float]:
    """单文本 → {token_id: L2 归一化词频权重} 稀疏向量；空文本返回 {}。"""
    counts: dict[str, float] = {}
    for tok in tokenize(text or ""):
        counts[tok] = counts.get(tok, 0.0) + 1.0
    if not counts:
        return {}

    # L2 归一化：w / sqrt(sum(w^2))，与 BGE-M3 原生稀疏语义对齐
    norm = math.sqrt(sum(float(w) * float(w) for w in counts.values()))
    if norm < 1e-9:  # 理论不可达（counts 非空则 norm>=1），防御性保留
        return {}
    return {_token_id(k): float(w) / norm for k, w in counts.items()}


def build_sparse_vectors(texts: list[str]) -> list[dict[int, float]]:
    """批量入口：文本列表 → 稀疏向量字典列表（与稠密向量同一批输入对齐）。"""
    if not isinstance(texts, list):
        raise ValueError("参数 texts 必须是列表")
    return [build_sparse_vector(t) for t in texts]


__all__ = ["tokenize", "build_sparse_vector", "build_sparse_vectors"]
