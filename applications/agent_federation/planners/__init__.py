"""联邦侧 Planner 实现（Plan-F Phase 2/3）。

``AgenticPlanner``：把 deep_agent 执行适配为统一 Planner 协议（plan -> Plan + execute -> StreamEvent），
供 ``PLANNER=agentic`` 时由 app 侧统一消费；``arun`` 供联邦 run_deep_agent 经 PlannerRuntime 治理复用。
run_deep_agent 的 guard/intent/cache/memory/monitor 副作用链路保持不动，本包只做协议适配 + 治理装配。

``get_planner_runtime()``：联邦侧 ``PlannerRuntime`` 单例（与 app/main.py 对称），组合治理参数
max_skill_depth/max_steps 取环境变量（默认 4 / 20，与 PlannerRuntime 默认值一致）。
B-2 修复：懒构建 PG stores（checkpoint/trajectory/side_effect/ownership）+ llm 注入，
pool 不可用时退化为 None（不崩溃），与 agent_server 的 _build_pg_stores 对称。
"""

import logging
import os

from agent_core.config import env_int
from agent_runtime.planner.agentic import AgenticPlanner
from agent_runtime.planner.protocol import PlannerRuntime

logger = logging.getLogger(__name__)

__all__ = ["AgenticPlanner", "get_planner_runtime"]


_runtime_singleton: PlannerRuntime | None = None
_runtime_bridge_flag: bool | None = None


def _build_pg_stores() -> dict:
    """懒构建 PG stores（B-2）：pool 未初始化时返回空 dict，退化为 InMemory / None。

    与 agent_server main.py 的 _build_pg_stores 对称，复用 agent_runtime.db 单池
    （ADR-0003），不自建 asyncpg 双池。
    """
    stores: dict = {}
    try:
        from agent_runtime.db import get_pool

        pool = get_pool()
        if pool is None:
            logger.debug("PG pool 未初始化，跳过 PG stores 构建")
            return stores
        from agent_runtime.planner.durability_pg import (
            PgCheckpointStore,
            PgExecutionOwnershipStore,
            PgSideEffectStore,
        )
        from agent_runtime.trajectory.store_pg import PgTrajectoryStore

        stores["pool"] = pool
        stores["checkpoint_store"] = PgCheckpointStore(pool)
        stores["trajectory_store"] = PgTrajectoryStore(pool)
        stores["ownership_store"] = PgExecutionOwnershipStore(pool)
        stores["side_effect_store"] = PgSideEffectStore(pool)
    except Exception as exc:  # noqa: BLE001
        logger.warning("PG stores 构建失败，退化为 None: %s", exc)
    return stores


def _build_llm():
    """懒构建 LLM（B-2）：构建失败返回 None（不致命，agentic 执行不依赖 runtime.llm）。"""
    try:
        from agent_core.llm import build_chat_model

        return build_chat_model()
    except Exception:  # noqa: BLE001
        return None


def get_planner_runtime() -> PlannerRuntime:
    """联邦侧 PlannerRuntime 单例（模块级，联邦无 FastAPI app.state 注入先例）。

    组合治理参数取环境变量（与 app/config 对齐）：
      - FED_MAX_SKILL_DEPTH（默认 4）
      - FED_MAX_STEPS（默认 20）
      - FED_MAX_DURATION_SECONDS（默认 60）
    registry：默认 None（联邦 agentic 执行不经能力注册表查能力，保持与 AgenticPlanner 行为一致）；
    当 ``AGENTIC_RUNTIME_BRIDGE=true``（实验）时改为联邦能力注册表，使 AgenticRuntimeBridge
    的 tool call 能经 ``runtime.delegate`` 落到统一 Runtime 治理（架构不变量 #4）。

    B-2 修复：懒构建 PG stores + llm 注入，pool 不可用时退化为 None。
    post_execution_hooks 暂不注入——联邦 agentic 经 _execute_agent_core（deepagents 内部循环），
    hooks 在 execution() 退出时触发但 executor 不感知 hooks，注入后不会被调（待 B-3 修复后接入）。

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

        stores = _build_pg_stores()
        llm = _build_llm()

        _runtime_singleton = PlannerRuntime(
            registry=registry,
            llm=llm,
            pool=stores.get("pool"),
            max_skill_depth=env_int("FED_MAX_SKILL_DEPTH", 4),
            max_steps=env_int("FED_MAX_STEPS", 20),
            max_duration_seconds=env_int("FED_MAX_DURATION_SECONDS", 60),
            checkpoint_store=stores.get("checkpoint_store"),
            trajectory_store=stores.get("trajectory_store"),
            side_effect_store=stores.get("side_effect_store"),
            ownership_store=stores.get("ownership_store"),
            enable_loop_fingerprint=os.getenv("FED_ENABLE_LOOP_FINGERPRINT", "").lower()
            in ("1", "true"),
            replica_id=os.getenv("FED_REPLICA_ID", "federation"),
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


