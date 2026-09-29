# -*- coding: utf-8 -*-
"""agent_core.metrics.compare 单元测试（纯 stdlib，无需外部服务）。"""

import pytest

from agent_core.metrics.compare import (
    average_rank,
    bootstrap_mean_diff_ci,
    cohens_kappa,
    kendall_tau,
    pearson_r,
    spearman_rho,
)


# ---------------------------------------------------------------------------
# bootstrap_mean_diff_ci
# ---------------------------------------------------------------------------
def test_bootstrap_identical_samples_not_significant():
    a = [0.5, 0.6, 0.7, 0.5, 0.6]
    res = bootstrap_mean_diff_ci(a, list(a), seed=1)
    assert res["mean_diff"] == pytest.approx(0.0)
    assert res["significant"] is False
    assert res["n"] == len(a)


def test_bootstrap_clearly_separated_is_significant():
    a = [0.9, 0.95, 0.88, 0.92, 0.91, 0.89]
    b = [0.10, 0.12, 0.08, 0.11, 0.09, 0.13]
    res = bootstrap_mean_diff_ci(a, b, n_resamples=500, seed=42)
    assert res["mean_diff"] > 0.5
    assert res["significant"] is True
    assert res["ci_low"] > 0.0


def test_bootstrap_is_deterministic_with_seed():
    a = [0.4, 0.5, 0.6, 0.7]
    b = [0.1, 0.2, 0.3, 0.35]
    r1 = bootstrap_mean_diff_ci(a, b, seed=7)
    r2 = bootstrap_mean_diff_ci(a, b, seed=7)
    assert r1 == r2


def test_bootstrap_rejects_unequal_length():
    with pytest.raises(ValueError):
        bootstrap_mean_diff_ci([1, 2], [1, 2, 3])


# ---------------------------------------------------------------------------
# ranks / pearson
# ---------------------------------------------------------------------------
def test_average_rank_handles_ties():
    # [10,10,20] → 前两个并列名次 1,2 → 平均 1.5；20 名次 3
    assert average_rank([10, 10, 20]) == [1.5, 1.5, 3.0]


def test_pearson_perfect_positive():
    assert pearson_r([1, 2, 3], [2, 4, 6]) == pytest.approx(1.0)


def test_pearson_constant_series_returns_zero():
    assert pearson_r([1, 1, 1], [1, 2, 3]) == 0.0


# ---------------------------------------------------------------------------
# spearman / kendall
# ---------------------------------------------------------------------------
def test_spearman_monotonic_is_one():
    assert spearman_rho([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)


def test_spearman_reversed_is_minus_one():
    assert spearman_rho([1, 2, 3, 4], [40, 30, 20, 10]) == pytest.approx(-1.0)


def test_spearman_nonlinear_monotonic_still_one():
    # Spearman 只看秩，非线性单调映射也应 = 1.0（区别于 Pearson）
    assert spearman_rho([1, 2, 3, 4], [1, 4, 9, 16]) == pytest.approx(1.0)


def test_spearman_constant_returns_zero():
    assert spearman_rho([1, 2, 3], [5, 5, 5]) == 0.0


def test_kendall_tau_perfect_and_reversed():
    assert kendall_tau([1, 2, 3], [1, 2, 3]) == pytest.approx(1.0)
    assert kendall_tau([1, 2, 3], [3, 2, 1]) == pytest.approx(-1.0)


def test_kendall_tau_b_with_ties():
    # x=[1,1,2] y=[1,2,2]：仅 (0,2) 一致对 → C=1,D=0；x 有 1 并列对、y 有 1 并列对
    # τ-b = (C-D)/sqrt((n0-n1)(n0-n2)) = 1/sqrt((3-1)(3-1)) = 0.5
    tau = kendall_tau([1, 1, 2], [1, 2, 2])
    assert tau == pytest.approx(0.5, rel=1e-6)


# ---------------------------------------------------------------------------
# cohens_kappa
# ---------------------------------------------------------------------------
def test_kappa_perfect_agreement():
    assert cohens_kappa([1, 2, 1, 2, 0], [1, 2, 1, 2, 0]) == pytest.approx(1.0)


def test_kappa_single_category_is_neutral():
    # 全同类别 → pe=1 → 无法区分，返回中性 0.0（非 1.0）
    assert cohens_kappa([1, 1, 1], [1, 1, 1]) == 0.0


def test_kappa_rejects_unequal_length():
    with pytest.raises(ValueError):
        cohens_kappa([1, 2], [1, 2, 2])
