"""联邦侧 Planner 实现（Plan-F Phase 2/3）。

``AgenticPlanner``：把 deep_agent 执行适配为统一 Planner 协议（plan -> Plan + execute -> StreamEvent），
供 ``PLANNER=agentic`` 时由 app 侧统一消费；``arun`` 供联邦 run_deep_agent 经 PlannerRuntime 治理复用。
run_deep_agent 的 guard/intent/cache/memory/monitor 副作用链路保持不动，本包只做协议适配 + 治理装配。

``get_planner_runtime()``：联邦侧 ``PlannerRuntime`` 单例（与 app/main.py 对称），组合治理参数
max_skill_depth/max_steps 取环境变量（默认 4 / 20，与 PlannerRuntime 默认值一致）。
"""

import logging
import os

from agent_federation.planners.agentic import AgenticPlanner
from agent_runtime.planner.protocol import PlannerRuntime

logger = logging.getLogger(__name__)

__all__ = ["AgenticPlanner", "get_planner_runtime"]


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except (TypeError, ValueError):
        return default


_runtime_singleton: PlannerRuntime | None = None
_runtime_bridge_flag: bool | None = None


def get_planner_runtime() -> PlannerRuntime:
    """联邦侧 PlannerRuntime 单例（模块级，联邦无 FastAPI app.state 注入先例）。

    组合治理参数取环境变量（与 app/config 对齐）：
      - FED_MAX_SKILL_DEPTH（默认 4）
      - FED_MAX_STEPS（默认 20）
    registry：默认 None（联邦 agentic 执行不经能力注册表查能力，保持与 AgenticPlanner 行为一致）；
    当 ``AGENTIC_RUNTIME_BRIDGE=true``（实验）时改为联邦能力注册表，使 AgenticRuntimeBridge
    的 tool call 能经 ``runtime.delegate`` 落到统一 Runtime 治理（架构不变量 #4）。

    单例在首次调用时构建并缓存；若 ``AGENTIC_RUNTIME_BRIDGE`` 标志相对上次构建发生变化
    （运行时切换实验开关），则重建以反映最新 registry 状态，避免 stale 单例。
    """
    global _runtime_singleton, _runtime_bridge_flag
    bridge = _bridge_enabled()
    if _runtime_singleton is None or _runtime_bridge_flag != bridge:
        registry = None
        if bridge:
            try:
                from agent_federation.planners.agentic_runtime_bridge import (
                    federation_capability_registry,
                )

                registry = federation_capability_registry()
            except Exception as exc:  # noqa: BLE001
                logger.warning("AGENTIC_RUNTIME_BRIDGE 注册表构建失败，回退 None: %s", exc)
        _runtime_singleton = PlannerRuntime(
            registry=registry,
            max_skill_depth=_env_int("FED_MAX_SKILL_DEPTH", 4),
            max_steps=_env_int("FED_MAX_STEPS", 20),
        )
        _runtime_bridge_flag = bridge
    return _runtime_singleton


def reset_planner_runtime() -> None:
    """重置联邦侧 PlannerRuntime 单例（测试 / 运行时切换 AGENTIC_RUNTIME_BRIDGE 后重建）。"""
    global _runtime_singleton, _runtime_bridge_flag
    _runtime_singleton = None
    _runtime_bridge_flag = None


def _bridge_enabled() -> bool:
    from agent_federation.planners.agentic_runtime_bridge import bridge_enabled

    return bridge_enabled()


