# -*- coding: utf-8 -*-
"""
test_sparse_vectorizer.py —— 验证 app/lm/sparse_vectorizer.py 的零依赖稀疏向量生成。

【不依赖重型依赖，可在纯 pytest 环境运行。】
验证重点：
1. 同一文本多次调用生成结果稳定（token id 一致）；
2. **跨进程稳定**：token id 由 hashlib.md5 定义（显式断言与 md5 结果一致），
   而非内置 hash()（内置 hash 受 PYTHONHASHSEED 随机化影响）；
3. 权重 L2 归一化（sum(w^2)≈1）；
4. 中英文混合文本；
5. 空文本 / 极短文本 / 纯标点边界。
"""

import hashlib
import math

from app.lm.sparse_vectorizer import _token_id, build_sparse_vector, build_sparse_vectors, tokenize


def test_same_text_stable_across_calls():
    # 同一文本多次调用（模拟同进程不同时刻 / 跨进程）token id 完全一致
    text = "苹果手机 介绍：支持5G网络 bge-m3 模型"
    v1 = build_sparse_vector(text)
    v2 = build_sparse_vector(text)
    v3 = build_sparse_vector(text)
    assert v1 == v2 == v3


def test_token_id_matches_md5_definition():
    # 显式断言 id 来自 hashlib.md5 前 8 位 hex（掩码到 int32 正区间），而非内置 hash()
    for tok in ["苹果", "iphone", "bge-m3", "烫金机", "15", "介绍"]:
        expected = int(hashlib.md5(tok.encode("utf-8")).hexdigest()[:8], 16) & 0x7FFFFFFF
        assert _token_id(tok) == expected


def test_token_id_in_int32_positive_range():
    # Milvus 稀疏向量 id 要求非负整数；设计上落在 int32 正区间
    for tok in ["苹果手机", "支持", "5G", "网络", "模型", "x" * 40]:
        tid = _token_id(tok)
        assert isinstance(tid, int)
        assert 0 <= tid <= 0x7FFFFFFF


def test_different_tokens_mapping_differs():
    # 不同词元 id 不同（md5 碰撞概率极低，固定样例强断言）
    ids = {_token_id(t) for t in ["苹果", "手机", "烫金机", "iphone", "bge-m3"]}
    assert len(ids) == 5


def test_l2_norm_is_one():
    text = "苹果手机 介绍：支持5G网络 bge-m3 模型"
    v = build_sparse_vector(text)
    norm = math.sqrt(sum(float(w) * float(w) for w in v.values()))
    assert abs(norm - 1.0) < 1e-9


def test_weight_is_term_frequency_normalized():
    # "苹果 苹果" 中 "苹果" 出现 2 次：TF=2，L2 归一化后权重应为 1.0（唯一词元）
    v = build_sparse_vector("苹果 苹果")
    assert len(v) == 1
    assert abs(list(v.values())[0] - 1.0) < 1e-9


def test_sparse_keys_are_int_values_are_float():
    v = build_sparse_vector("苹果手机 5G 网络")
    for k, w in v.items():
        assert isinstance(k, int)
        assert isinstance(w, float)


def test_empty_text_returns_empty():
    assert build_sparse_vector("") == {}
    assert build_sparse_vector(None) == {}


def test_punctuation_only_returns_empty():
    assert build_sparse_vector("，。！？  ！！") == {}


def test_single_char_text():
    v = build_sparse_vector("机")
    assert len(v) == 1
    assert abs(list(v.values())[0] - 1.0) < 1e-9


def test_chinese_english_mixed_text():
    # 中英混合：中文 bigram/整词 + 英文小写词元共存
    text = "苹果iPhone 15 Pro Max 支持5G网络"
    tokens = tokenize(text)
    assert "苹果" in tokens
    assert "iphone" in tokens
    assert "15" in tokens
    assert "pro" in tokens
    assert "max" in tokens
    assert "5g" in tokens
    v = build_sparse_vector(text)
    # 关键中文词元能命中（导入/检索共用同一实现）
    assert _token_id("苹果") in v
    assert _token_id("网络") in v


def test_cjk_bigram_and_whole_word_coexist():
    # ≥3 字 CJK 串同时产出重叠 bigram 与短整词（≤8 字）
    tokens = tokenize("烫金机")
    assert "烫金" in tokens
    assert "金机" in tokens
    assert "烫金机" in tokens


def test_build_sparse_vectors_batch():
    texts = ["苹果手机", "介绍：支持5G网络", "烫金机使用说明"]
    vecs = build_sparse_vectors(texts)
    assert isinstance(vecs, list)
    assert len(vecs) == 3
    for v in vecs:
        norm = math.sqrt(sum(float(w) * float(w) for w in v.values())) if v else 0.0
        assert abs(norm - 1.0) < 1e-9 or norm == 0.0


def test_build_sparse_vectors_requires_list():
    try:
        build_sparse_vectors("不是列表")
    except ValueError:
        pass
    else:
        raise AssertionError("build_sparse_vectors 入参非列表时应抛出 ValueError")
