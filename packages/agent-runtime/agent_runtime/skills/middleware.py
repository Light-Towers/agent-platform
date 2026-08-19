"""Skill Execution Middleware：SkillRegistry.execute 的洋葱链边界（Plan-F 架构审核 P1）。

演进方向：retry / 熔断 / rate limit / tracing 等 Runtime 边界从「各能力实现内散落」
收敛为 SkillRegistry.execute 的统一洋葱链——Planner 只决策，能力实现只做本职，
Runtime 边界在链上即插即用。

当前已收敛：``CircuitBreakerMiddleware``（熔断）。
演进中：retry（Planner 编排循环的"证据为空重新路由"属编排语义，不迁移；
执行级异常重试待真实需求出现再挂链）、rate limit（admission 队列待接入）。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from agent_runtime.circuit_breaker import CircuitBreaker

# 洋葱模型：call_next 是下一层（另一中间件或最终执行器）
CallNext = Callable[[str, dict[str, Any]], Awaitable[Any]]


class SkillMiddleware(Protocol):
    """Skill 执行中间件：包装 name 技能的调用，按需委托 call_next。

    中间件按注册顺序外层→内层包裹，最先注册的最外层（先执行前置逻辑，
    最后拿结果）。不调用 call_next 即短路（拦截/降级）。
    """

    async def around(self, name: str, kwargs: dict[str, Any], call_next: CallNext) -> Any: ...


class CircuitBreakerMiddleware:
    """熔断中间件：上游故障/连续失败达阈值后直接短路降级，不再触发真实调用。

    ``skill_names`` 为 None 时作用于全部技能（默认）；否则仅包裹指定技能
    （隔离故障域——search 熔断不应波及 rag/sql）。

    降级语义与 search.py 内嵌实现保持一致：fallback 返回 None 时产出
    明确的"暂时不可用"提示，而非静默空结果（供 Planner 合成时明示降级）。
    """

    def __init__(
        self,
        breaker: CircuitBreaker,
        *,
        skill_names: tuple[str, ...] | None = None,
        degraded_message: str = "联网搜索暂时不可用（熔断或请求失败）",
    ) -> None:
        self._breaker = breaker
        self._skill_names = skill_names
        self._degraded_message = degraded_message

    async def around(self, name: str, kwargs: dict[str, Any], call_next: CallNext) -> Any:
        if self._skill_names is not None and name not in self._skill_names:
            return await call_next(name, kwargs)
        result = await self._breaker.call(lambda: call_next(name, kwargs), fallback=None)
        if result is None:
            return [self._degraded_message]
        return result