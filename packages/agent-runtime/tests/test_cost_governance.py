"""V3 补-3 单测：Cost / Resource Governance 多层预算。

验证：
- BudgetUsage：使用量计算 / 超限判定 / 利用率；
- InMemoryBudgetStore：记录 / 查询 / 窗口分桶；
- CostGovernance：check / record / get_usage / get_all_usage / BudgetExceeded。
"""

import pytest

from agent_runtime.cost_governance import (
    BudgetDimension,
    BudgetExceeded,
    BudgetLimit,
    BudgetUsage,
    CostGovernance,
    InMemoryBudgetStore,
)

# ===== BudgetUsage =====

def test_usage_not_exceeded():
    u = BudgetUsage("t1", BudgetDimension.TOKENS, 50, 100, 3600)
    assert not u.exceeded
    assert u.remaining == 50
    assert u.utilization == 0.5


def test_usage_exceeded():
    u = BudgetUsage("t1", BudgetDimension.TOKENS, 101, 100, 3600)
    assert u.exceeded
    assert u.remaining == 0
    assert u.utilization == 1.01


def test_usage_over_limit():
    u = BudgetUsage("t1", BudgetDimension.TOKENS, 150, 100, 3600)
    assert u.exceeded
    assert u.remaining == 0  # max(0, ...)
    assert u.utilization == 1.5


def test_usage_to_dict():
    u = BudgetUsage("t1", BudgetDimension.REQUESTS, 5, 10, 3600)
    d = u.to_dict()
    assert d["tenant_id"] == "t1"
    assert d["dimension"] == "requests"
    assert d["utilization"] == 0.5


# ===== InMemoryBudgetStore =====

async def test_store_record_and_get():
    store = InMemoryBudgetStore()
    total = await store.record("t1", BudgetDimension.TOKENS, 50, 3600)
    assert total == 50
    total = await store.record("t1", BudgetDimension.TOKENS, 30, 3600)
    assert total == 80
    assert await store.get_usage("t1", BudgetDimension.TOKENS, 3600) == 80


async def test_store_different_tenants_isolated():
    store = InMemoryBudgetStore()
    await store.record("t1", BudgetDimension.TOKENS, 50, 3600)
    await store.record("t2", BudgetDimension.TOKENS, 30, 3600)
    assert await store.get_usage("t1", BudgetDimension.TOKENS, 3600) == 50
    assert await store.get_usage("t2", BudgetDimension.TOKENS, 3600) == 30


async def test_store_different_dimensions_isolated():
    store = InMemoryBudgetStore()
    await store.record("t1", BudgetDimension.TOKENS, 50, 3600)
    await store.record("t1", BudgetDimension.COST, 1.5, 3600)
    assert await store.get_usage("t1", BudgetDimension.TOKENS, 3600) == 50
    assert await store.get_usage("t1", BudgetDimension.COST, 3600) == 1.5


# ===== CostGovernance =====

def _make_gov() -> CostGovernance:
    store = InMemoryBudgetStore()
    return CostGovernance(
        store,
        limits={
            BudgetDimension.REQUESTS: BudgetLimit(BudgetDimension.REQUESTS, limit=100),
            BudgetDimension.TOKENS: BudgetLimit(BudgetDimension.TOKENS, limit=1000),
            BudgetDimension.COST: BudgetLimit(BudgetDimension.COST, limit=10.0),
        },
    )


async def test_gov_check_within_limit():
    gov = _make_gov()
    usage = await gov.check("t1", BudgetDimension.TOKENS, estimated_amount=500)
    assert not usage.exceeded
    assert usage.used == 500  # projected


async def test_gov_check_exceeds():
    gov = _make_gov()
    with pytest.raises(BudgetExceeded) as exc_info:
        await gov.check("t1", BudgetDimension.TOKENS, estimated_amount=1500)
    assert exc_info.value.usage.dimension is BudgetDimension.TOKENS


async def test_gov_record_and_check():
    gov = _make_gov()
    await gov.record("t1", BudgetDimension.TOKENS, 600)
    usage = await gov.check("t1", BudgetDimension.TOKENS, estimated_amount=300)
    assert usage.used == 900  # 600 + 300

    with pytest.raises(BudgetExceeded):
        await gov.check("t1", BudgetDimension.TOKENS, estimated_amount=500)


async def test_gov_record_exceeds():
    gov = _make_gov()
    await gov.record("t1", BudgetDimension.REQUESTS, 50)
    await gov.record("t1", BudgetDimension.REQUESTS, 50)
    with pytest.raises(BudgetExceeded):
        await gov.record("t1", BudgetDimension.REQUESTS, 1)


async def test_gov_get_usage():
    gov = _make_gov()
    await gov.record("t1", BudgetDimension.TOKENS, 300)
    usage = await gov.get_usage("t1", BudgetDimension.TOKENS)
    assert usage is not None
    assert usage.used == 300
    assert usage.limit == 1000


async def test_gov_get_usage_no_limit():
    gov = _make_gov()
    usage = await gov.get_usage("t1", BudgetDimension.DURATION)
    assert usage is None  # 未设限


async def test_gov_get_all_usage():
    gov = _make_gov()
    await gov.record("t1", BudgetDimension.TOKENS, 300)
    await gov.record("t1", BudgetDimension.COST, 2.5)
    all_usage = await gov.get_all_usage("t1")
    assert len(all_usage) == 3
    assert all_usage[BudgetDimension.TOKENS].used == 300
    assert all_usage[BudgetDimension.COST].used == 2.5
    assert all_usage[BudgetDimension.REQUESTS].used == 0


async def test_gov_no_limit_for_dimension():
    """未设限的维度不检查。"""
    gov = _make_gov()
    usage = await gov.check("t1", BudgetDimension.DURATION, estimated_amount=999999)
    assert not usage.exceeded  # 无限


async def test_gov_set_limit_after_init():
    gov = CostGovernance(InMemoryBudgetStore())
    gov.set_limit(BudgetLimit(BudgetDimension.DURATION, limit=60))
    usage = await gov.check("t1", BudgetDimension.DURATION, estimated_amount=30)
    assert not usage.exceeded
