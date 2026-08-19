# -*- coding: utf-8 -*-
"""进程内可观测性计数器（P3 可观测性补完，零外部依赖）。

设计护栏（遵循 §3 内核零依赖铁律）：
- 仅依赖 stdlib，不硬依赖 prometheus / fastapi，避免给 deepagents 引入新重依赖。
- 维护进程级单调计数器 + 最近状态快照，供 ``api/server.py`` 的 ``GET /metrics``
  端点以 JSON 暴露；同时这些计数在状态变化时也会经 ``agent_core.monitor`` 上报事件。

并发安全：所有累加在 ``_lock`` 下完成（asyncio 下多协程共享同一 counter 实例）。
"""

from __future__ import annotations

import threading
from typing import Any

from agent_core.monitor import monitor

_lock = threading.Lock()

# 熔断相关
circuit_open_total = 0          # 熔断器进入 OPEN 的次数
circuit_half_open_total = 0     # 进入 HALF_OPEN 探测的次数
circuit_closed_total = 0        # 恢复 CLOSED 的次数

# 委派子 Agent 相关
delegation_success_total = 0    # 委派成功（含降级兜底成功）次数
delegation_failure_total = 0    # 委派彻底失败（熔断+兜底均不可用）次数
degrade_total = 0               # 触发降级兜底次数

# 最近一次熔断状态快照（agent_name -> state）
_circuit_state: dict[str, str] = {}


def _inc(name: str, n: int = 1) -> None:
    global circuit_open_total, circuit_half_open_total, circuit_closed_total
    global delegation_success_total, delegation_failure_total, degrade_total
    with _lock:
        if name == "circuit_open_total":
            circuit_open_total += n
        elif name == "circuit_half_open_total":
            circuit_half_open_total += n
        elif name == "circuit_closed_total":
            circuit_closed_total += n
        elif name == "delegation_success_total":
            delegation_success_total += n
        elif name == "delegation_failure_total":
            delegation_failure_total += n
        elif name == "degrade_total":
            degrade_total += n


def record_circuit_state(agent_name: str, state: str) -> None:
    """记录熔断状态变化：更新快照 + 累加计数 + 经 monitor 上报。

    Args:
        agent_name: 子 Agent 名（作为维度）。
        state: ``open`` / ``half_open`` / ``closed``。
    """
    # 同态去重：仅状态真正变化才计数/上报（避免重复打点）。
    with _lock:
        if _circuit_state.get(agent_name) == state:
            return
        _circuit_state[agent_name] = state
    counter = {
        "open": "circuit_open_total",
        "half_open": "circuit_half_open_total",
        "closed": "circuit_closed_total",
    }.get(state)
    if counter:
        _inc(counter)
    monitor.report_circuit(
        state,
        f"熔断器 [{agent_name}] 状态变为 {state}",
        {"agent_name": agent_name},
    )


def record_delegation(success: bool, degraded: bool = False) -> None:
    """记录一次委派结果。

    Args:
        success: 是否最终成功（含降级兜底成功）。
        degraded: 是否走了降级兜底分支。
    """
    if degraded:
        _inc("degrade_total")
    _inc("delegation_success_total" if success else "delegation_failure_total")


def snapshot() -> dict[str, Any]:
    """返回当前指标快照（供 /metrics 端点序列化）。"""
    with _lock:
        return {
            "circuit_open_total": circuit_open_total,
            "circuit_half_open_total": circuit_half_open_total,
            "circuit_closed_total": circuit_closed_total,
            "delegation_success_total": delegation_success_total,
            "delegation_failure_total": delegation_failure_total,
            "degrade_total": degrade_total,
            "circuit_state": dict(_circuit_state),
        }


__all__ = [
    "record_circuit_state",
    "record_delegation",
    "snapshot",
]
