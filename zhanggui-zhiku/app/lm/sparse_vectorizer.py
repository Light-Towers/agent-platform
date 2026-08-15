# -*- coding: utf-8 -*-
"""
app/lm/sparse_vectorizer.py —— 零依赖中文/英文稀疏向量生成器（M8，B 路线核心）。

背景：
    硅基流动 embeddings API 只返回稠密向量、不返回稀疏向量；而本项目 Milvus 混合检索
    依赖「稠密 + 稀疏」双路（schema：dense COSINE + sparse IP，见 node_import_milvus）。
    本模块在 api 模式下**本地**生成稀疏向量，保住双路混合检索不退化。

设计要点（均在本模块内显式实现，无任何第三方依赖）：
1. 分词（导入与检索共用同一实现，保证 doc/query token 空间一致）：
   - 英文/数字：连续 [A-Za-z0-9] 词元（含 `-`/`_` 连接的产品型号，如 "bge-m3"），统一小写；
   - 中文：连续 CJK 串 —— 单字直接输出；2 字直接整词；≥3 字输出「重叠 bigram + 整词（≤8 字）」，
     兼顾短查询（bigram）与完整商品名（整词）的命中；
   - 标点/空白天然分隔，不产生词元。
2. token → id：`hashlib.md5` 前 8 位 hex → int，并掩码到 int32 正区间（`& 0x7FFFFFFF`）。
   **严禁使用内置 hash()**（PYTHONHASHSEED 随机化导致跨进程 id 不一致，会破坏 doc/query 对齐）。
3. 权重：词频 TF（单文档导入场景拿不到 DF，TF 即可），最后 **L2 归一化**
   （`w / sqrt(sum(w^2))`，与 BGE-M3 原生 SPLADE 稀疏语义对齐）。
4. 与稠密对齐：api 模式 generate_embeddings 对同一拼接文本（如 `商品：{item_name}，介绍：{content}`）
   调用本模块，保证稠密/稀疏作用在同一文本上。
"""

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
    """
    将词元映射为稳定非负 int32 id（跨进程一致）。

    用 hashlib.md5 而非内置 hash()：内置 hash 受 PYTHONHASHSEED 随机化影响，
    不同进程/不同启动下同一字符串的 hash 值不同，会破坏 doc/query token 空间对齐。
    掩码 `& 0x7FFFFFFF` 保证落在 int32 正区间（Milvus 稀疏向量 id 要求非负整数）。
    """
    digest = hashlib.md5(token.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) & 0x7FFFFFFF


def tokenize(text: str) -> list:
    """
    将文本切分为词元列表（英文小写 + 中文 bigram/整词）。

    :param text: 原始文本（与稠密向量生成使用同一拼接文本）
    :return: 词元列表，标点/空白不产生词元
    """
    tokens = []
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
            # 短整词整体保留：命中「烫金机」「苹果手机」等完整商品名
            if len(run) <= _MAX_CJK_WHOLE_LEN:
                tokens.append(run)
    return tokens


def build_sparse_vector(text: str) -> dict:
    """
    单文本 → {token_id: L2 归一化词频权重} 稀疏向量。

    :param text: 原始文本
    :return: 稀疏向量字典（key 为非负 int32 id，value 为 float 权重）；
             空文本 / 无可分词元时返回空字典 {}
    """
    counts = {}
    for tok in tokenize(text or ""):
        counts[tok] = counts.get(tok, 0) + 1
    if not counts:
        return {}

    # L2 归一化：w / sqrt(sum(w^2))，与 BGE-M3 原生稀疏语义对齐
    norm = math.sqrt(sum(float(w) * float(w) for w in counts.values()))
    if norm < 1e-9:  # 理论不可达（counts 非空则 norm>=1），防御性保留
        return {}
    return {_token_id(k): float(w) / norm for k, w in counts.items()}


def build_sparse_vectors(texts: list) -> list:
    """
    批量入口：文本列表 → 稀疏向量字典列表（与 generate_embeddings 的 sparse 字段对齐）。

    :param texts: 非空文本列表（与稠密向量同一批输入）
    :return: 稀疏向量字典列表，与输入一一对应
    :raise ValueError: 入参非列表时抛出
    """
    if not isinstance(texts, list):
        raise ValueError("参数texts必须是列表")
    return [build_sparse_vector(t) for t in texts]
