# -*- coding: utf-8 -*-
"""
test_normalize_sparse.py —— 验证 app/utils/normalize_sparse_vector.py 的稀疏向量 L2 归一化。

【不依赖重型依赖，可在纯 pytest+numpy+python-dotenv 环境运行。】
仅依赖 numpy。

源码语义：对 dict 格式稀疏向量做 L2 归一化（各值除以 L2 范数），
空向量或范数≈0 时返回原向量。归一化后 L2 范数应为 1。
"""

import numpy as np

from app.utils.normalize_sparse_vector import normalize_sparse_vector


def test_empty_vector_returns_same():
    assert normalize_sparse_vector({}) == {}


def test_zero_norm_returns_original():
    vec = {0: 0.0, 1: 0.0}
    out = normalize_sparse_vector(vec)
    # 范数≈0，应原样返回（避免除零）
    assert out == vec


def test_l2_norm_becomes_one():
    vec = {0: 3.0, 1: 4.0}
    out = normalize_sparse_vector(vec)
    values = np.array(list(out.values()), dtype=np.float64)
    norm = np.linalg.norm(values)
    assert abs(norm - 1.0) < 1e-9


def test_normalization_values_are_correct():
    # [3, 4] 的 L2 范数为 5 -> 归一化为 [0.6, 0.8]
    vec = {0: 3.0, 1: 4.0}
    out = normalize_sparse_vector(vec)
    assert abs(out[0] - 0.6) < 1e-9
    assert abs(out[1] - 0.8) < 1e-9


def test_keys_are_preserved():
    vec = {"a": 1.0, "b": 2.0, "c": 2.0}
    out = normalize_sparse_vector(vec)
    assert set(out.keys()) == {"a", "b", "c"}


def test_negative_values_normalize_to_unit_norm():
    # [-3, 4] 范数为 5，归一化后范数仍为 1
    vec = {0: -3.0, 1: 4.0}
    out = normalize_sparse_vector(vec)
    values = np.array(list(out.values()), dtype=np.float64)
    assert abs(np.linalg.norm(values) - 1.0) < 1e-9
    assert abs(out[0] - (-0.6)) < 1e-9
    assert abs(out[1] - 0.8) < 1e-9


def test_single_dimension_becomes_one():
    vec = {5: 7.0}
    out = normalize_sparse_vector(vec)
    assert abs(out[5] - 1.0) < 1e-9


def test_three_dimension_normalization():
    vec = {0: 1.0, 1: 2.0, 2: 2.0}
    out = normalize_sparse_vector(vec)
    values = np.array(list(out.values()), dtype=np.float64)
    expected = values / np.linalg.norm(values)
    for k, v in zip(vec.keys(), expected):
        assert abs(out[k] - v) < 1e-9
