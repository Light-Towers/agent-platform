# -*- coding: utf-8 -*-
"""P3 可观测性：进程内指标计数器单测（防回归）。

覆盖 deepagents/agent/metrics.py：
- record_circuit_state 状态转换计数 + 快照
- record_delegation 成功/失败/降级计数
- snapshot 字段完整性
- 全局计数跨调用累加（进程级）
"""

import pytest

from agent import metrics as M


@pytest.fixture(autouse=True)
def _reset_counters():
    """每个用例前重置全局计数器，避免跨用例串扰。"""
    M.circuit_open_total = 0
    M.circuit_half_open_total = 0
    M.circuit_closed_total = 0
    M.delegation_success_total = 0
    M.delegation_failure_total = 0
    M.degrade_total = 0
    M._circuit_state.clear()
    yield


def test_record_circuit_state_counts_and_snapshot():
    M.record_circuit_state("svc-a", "open")
    M.record_circuit_state("svc-a", "half_open")
    M.record_circuit_state("svc-a", "closed")

    snap = M.snapshot()
    assert snap["circuit_open_total"] == 1
    assert snap["circuit_half_open_total"] == 1
    assert snap["circuit_closed_total"] == 1
    # 同一 agent 的最终状态快照为 closed
    assert snap["circuit_state"]["svc-a"] == "closed"


def test_record_circuit_state_no_double_count_same_state():
    M.record_circuit_state("svc-b", "open")
    M.record_circuit_state("svc-b", "open")  # 同态不重复计数
    assert M.snapshot()["circuit_open_total"] == 1


def test_record_delegation_success_failure_degrade():
    M.record_delegation(success=True)
    M.record_delegation(success=False)
    M.record_delegation(success=True, degraded=True)

    snap = M.snapshot()
    assert snap["delegation_success_total"] == 2
    assert snap["delegation_failure_total"] == 1
    assert snap["degrade_total"] == 1


def test_snapshot_is_isolated_copy():
    M.record_circuit_state("svc-c", "open")
    snap1 = M.snapshot()
    snap1["circuit_state"]["svc-c"] = "tampered"  # 改副本不应影响内部状态
    snap2 = M.snapshot()
    assert snap2["circuit_state"]["svc-c"] == "open"
