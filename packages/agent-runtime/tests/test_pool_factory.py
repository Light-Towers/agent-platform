# -*- coding: utf-8 -*-
"""连接池工厂用例（agent-runtime 共享件）：显式配额 / 连接级只读 / 统计快照。

固化 2026-10-17 连接池审计结论，防回归到"`AsyncConnectionPool(dsn)` 裸奔"：
默认 `max_size=None` ⇒ 无限新建后端，天花板交给 PG `max_connections`，
超限以 `psycopg.OperationalError` 冒出被上层兜底成无解释的失败。

本文件随 2026-10-18 上移从 nl2sql-service 搬入（方案 §5.12.2 加法式上移）。
nl2sql 的配置面/路由测试留在该服务（那是应用层装配，不是本件的职责）。
"""

from __future__ import annotations

import json

import pytest
from psycopg_pool import AsyncConnectionPool

from agent_runtime.pool_factory import (
    DEFAULT_STATEMENT_TIMEOUT_MS,
    build_options,
    create_pool,
    pool_stats,
)


# ---------------------------------------------------------------------------
# build_options
# ---------------------------------------------------------------------------
def test_options_carry_statement_timeout_and_read_only():
    opts = build_options(1234, read_only=True)
    assert "-c statement_timeout=1234" in opts
    assert "-c default_transaction_read_only=on" in opts


def test_options_omit_read_only_when_not_requested():
    """元知识库/CLI 要写，不能只读——选项里不允许出现 read_only。"""
    assert "read_only" not in build_options(1000, read_only=False)


# ---------------------------------------------------------------------------
# create_pool
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("min_size", "max_size"),
    [
        (-1, 20),  # 负下限
        (5, 4),  # 下限大于上限
        (1, 0),  # 上限为 0
    ],
)
def test_create_pool_rejects_illegal_quota(min_size, max_size):
    with pytest.raises(ValueError, match="min_size|max_size"):
        create_pool(dsn="postgres://u@h/db", name="t", min_size=min_size, max_size=max_size)


def test_create_pool_rejects_non_positive_timeout():
    with pytest.raises(ValueError, match="超时"):
        create_pool(dsn="postgres://u@h/db", name="t", timeout=0)


def test_create_pool_rejects_non_positive_statement_timeout():
    with pytest.raises(ValueError, match="statement_timeout_ms"):
        create_pool(dsn="postgres://u@h/db", name="t", statement_timeout_ms=0)


def test_create_pool_sets_explicit_quota_and_options():
    pool = create_pool(
        dsn="postgres://u@h/db",
        name="meta",
        min_size=2,
        max_size=7,
        timeout=3.5,
        statement_timeout_ms=900,
        read_only=True,
    )
    assert isinstance(pool, AsyncConnectionPool)
    assert pool.min_size == 2
    assert pool.max_size == 7
    assert pool.timeout == 3.5
    # 排队上限 = 2 × max_size：超过即 TooManyRequests 快速失败，而不是无限新建后端
    assert pool.max_waiting == 14
    assert pool.name == "meta"
    assert pool.kwargs == {"options": build_options(900, read_only=True)}


def test_create_pool_defaults_are_conservative():
    pool = create_pool(dsn="postgres://u@h/db", name="dw")
    assert pool.min_size == 1  # 不预占（psycopg 默认 4）
    assert pool.max_size == 20  # 显式上限，不留给 PG max_connections
    assert pool.timeout == 5.0
    assert pool.kwargs == {"options": build_options(DEFAULT_STATEMENT_TIMEOUT_MS, read_only=False)}


# ---------------------------------------------------------------------------
# pool_stats
# ---------------------------------------------------------------------------
class _FakePool:
    """只实现 get_stats() 的最小替身，免连真库。"""

    def __init__(self, stats: dict) -> None:
        self._stats = stats

    def get_stats(self) -> dict:
        return dict(self._stats)


def test_pool_stats_derives_usage_and_is_json_safe():
    fake = _FakePool(
        {
            "pool_min": 1,
            "pool_max": 20,
            "pool_size": 6,
            "pool_available": 4,
            "requests_waiting": 2,
            "requests_queued": 9,
            "requests_wait_ms": 120,
            "requests_errors": 0,
            "usage_ms": 5000,
        }
    )
    out = pool_stats(fake)
    assert out["in_use"] == 2
    assert out["utilization"] == 0.1
    json.dumps(out)  # 不抛异常即 JSON 安全（观测端点直接可序列化）


def test_pool_stats_tolerates_missing_max():
    """pool_max 缺失时 utilization 退 0.0，不抛 ZeroDivisionError。"""
    out = pool_stats(_FakePool({"pool_size": 3, "pool_available": 1}))
    assert out["in_use"] == 2
    assert out["utilization"] == 0.0
