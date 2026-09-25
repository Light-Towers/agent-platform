"""V3-2 Effect Contract 单测（agent-runtime）。

验证：
- 枚举与 6 字段契约模型（DeliverySemantics / IdempotencyStrategy / ReceiptStrategy /
  RetryPolicy / FailureRecovery）；
- 常用预设（read_only / idempotent_write / non_idempotent_write / async_task）；
- ``decide_failure_action`` 决策矩阵（异常分类 × retry_policy）；
- ExecutionGraph 集成：UNSAFE contract 失败不重试；SAFE contract 重试；
  effect_type 优先用 EffectContract.effect_key。
"""

from agent_core.resilience import ErrorClass

from agent_runtime.effect_contract import (
    DeliverySemantics,
    EffectContract,
    FailureAction,
    FailureRecovery,
    IdempotencyStrategy,
    ReceiptStrategy,
    RetryPolicy,
    decide_failure_action,
)
from agent_runtime.planner.durability import InMemorySideEffectStore
from agent_runtime.planner.execution_graph import ExecutionGraph, _run_graph_in_place
from agent_runtime.planner.protocol import PlannerRuntime
from agent_runtime.skills.registry import Skill, SkillKind, SkillRegistry

# ===== 单元：模型与预设 =====

def test_effect_contract_has_six_fields():
    c = EffectContract(
        effect_key="order_id",
        delivery_semantics=DeliverySemantics.EFFECTIVELY_ONCE,
        idempotency_strategy=IdempotencyStrategy.BUSINESS_KEY,
        receipt_strategy=ReceiptStrategy.EXTERNAL_ID,
        retry_policy=RetryPolicy.SAFE,
        failure_recovery=FailureRecovery.RETRY_SAFE,
    )
    d = c.to_dict()
    assert set(d) == {
        "effect_key",
        "delivery_semantics",
        "idempotency_strategy",
        "receipt_strategy",
        "retry_policy",
        "failure_recovery",
    }
    assert d["delivery_semantics"] == "effectively-once"
    assert d["retry_policy"] == "safe"


def test_presets():
    ro = EffectContract.read_only()
    assert ro.retry_policy is RetryPolicy.SAFE
    assert ro.delivery_semantics is DeliverySemantics.AT_MOST_ONCE

    iw = EffectContract.idempotent_write("order_id")
    assert iw.effect_key == "order_id"
    assert iw.idempotency_strategy is IdempotencyStrategy.BUSINESS_KEY
    assert iw.retry_policy is RetryPolicy.SAFE

    nw = EffectContract.non_idempotent_write("payment")
    assert nw.retry_policy is RetryPolicy.UNSAFE
    assert nw.failure_recovery is FailureRecovery.MANUAL
    assert nw.idempotency_strategy is IdempotencyStrategy.NONE

    at = EffectContract.async_task("job_id")
    assert at.receipt_strategy is ReceiptStrategy.EXTERNAL_ID
    assert at.retry_policy is RetryPolicy.QUERY_FIRST
    assert at.failure_recovery is FailureRecovery.QUERY_BEFORE_RETRY


# ===== 单元：决策矩阵 =====

def test_decide_fatal_always_aborts():
    # FATAL 无论 contract 如何都终止
    assert decide_failure_action(None, ErrorClass.FATAL) is FailureAction.ABORT
    assert (
        decide_failure_action(EffectContract.read_only(), ErrorClass.FATAL)
        is FailureAction.ABORT
    )


def test_decide_recoverable_no_retry():
    assert (
        decide_failure_action(None, ErrorClass.RECOVERABLE) is FailureAction.NO_RETRY
    )
    assert (
        decide_failure_action(EffectContract.read_only(), ErrorClass.RECOVERABLE)
        is FailureAction.NO_RETRY
    )


def test_decide_retryable_undeclared_keeps_v2_behavior():
    # 未声明 contract → 保持 v2 语义（可重试）
    assert (
        decide_failure_action(None, ErrorClass.RETRYABLE) is FailureAction.RETRY_SAFE
    )


def test_decide_retryable_by_policy():
    assert (
        decide_failure_action(EffectContract.read_only(), ErrorClass.RETRYABLE)
        is FailureAction.RETRY_SAFE
    )
    assert (
        decide_failure_action(
            EffectContract.non_idempotent_write("payment"), ErrorClass.RETRYABLE
        )
        is FailureAction.NO_RETRY
    )
    assert (
        decide_failure_action(EffectContract.async_task("job_id"), ErrorClass.RETRYABLE)
        is FailureAction.QUERY_BEFORE_RETRY
    )


# ===== 集成：ExecutionGraph 决策 =====

def _registry(skills: dict, contracts: dict | None = None) -> SkillRegistry:
    reg = SkillRegistry()
    for name, fn in skills.items():
        reg.register(
            Skill(
                name,
                name,
                SkillKind.FUNCTION,
                fn,
                effect_contract=(contracts or {}).get(name),
            )
        )
    return reg


async def _collect(runtime, graph, execution_id=None):
    events = []
    async with runtime.execution(execution_id=execution_id):
        async for ev in _run_graph_in_place(
            graph, runtime, execution_id=execution_id
        ):
            events.append(ev)
    return events


async def test_unsafe_contract_does_not_retry():
    """UNSAFE（非幂等写）失败 → 不重试（calls 恒为 1）。"""
    state = {"calls": 0}

    async def non_idempotent(**kwargs):
        state["calls"] += 1
        raise ConnectionError("transient but unsafe to retry")

    g = ExecutionGraph()
    g.add_node("n1", "pay", {})
    runtime = PlannerRuntime(
        registry=_registry(
            {"pay": non_idempotent},
            {"pay": EffectContract.non_idempotent_write("payment")},
        )
    )

    events = await _collect(runtime, g)

    assert state["calls"] == 1  # 不重试
    errs = [ev for ev in events if ev.type == "error"]
    assert len(errs) == 1
    assert errs[0].payload.get("failure_action") == "no-retry"


async def test_safe_contract_retries():
    """SAFE（幂等）失败 → 重试至成功。"""
    state = {"calls": 0}

    async def flaky(**kwargs):
        state["calls"] += 1
        if state["calls"] == 1:
            raise ConnectionError("transient down")
        return {"ok": True}

    g = ExecutionGraph()
    g.add_node("n1", "order", {})
    runtime = PlannerRuntime(
        registry=_registry(
            {"order": flaky},
            {"order": EffectContract.idempotent_write("order_id")},
        )
    )

    events = await _collect(runtime, g)

    assert state["calls"] == 2  # 首 + 重试
    assert not any(ev.type == "error" for ev in events)


async def test_undeclared_contract_keeps_v2_retry():
    """未声明 effect_contract → 保持 v2 行为（瞬态重试）。"""
    state = {"calls": 0}

    async def flaky(**kwargs):
        state["calls"] += 1
        if state["calls"] == 1:
            raise ConnectionError("transient down")
        return {"ok": True}

    g = ExecutionGraph()
    g.add_node("n1", "flaky", {})
    runtime = PlannerRuntime(registry=_registry({"flaky": flaky}))

    await _collect(runtime, g)
    assert state["calls"] == 2


async def test_effect_key_used_for_side_effect_record():
    """副作用记录的 effect_type 优先用 EffectContract.effect_key。"""
    store = InMemorySideEffectStore()

    async def create(**kwargs):
        return {"order_id": "o-1"}

    g = ExecutionGraph()
    g.add_node("n1", "create_order", {})
    runtime = PlannerRuntime(
        registry=_registry(
            {"create_order": create},
            {"create_order": EffectContract.idempotent_write("order_ref")},
        ),
        side_effect_store=store,
    )

    await _collect(runtime, g, execution_id="exec-1")

    # effect_key = execution_id:step_id:effect_type，effect_type 应为 order_ref
    assert await store.has("exec-1", "n1", "order_ref") is True
    assert await store.has("exec-1", "n1", "skill:create_order") is False