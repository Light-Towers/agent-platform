"""Skill Execution Middleware：SkillRegistry.execute 的洋葱链边界（Plan-F 架构审核 P1）。

演进方向：retry / 熔断 / rate limit / tracing 等 Runtime 边界从「各能力实现内散落」
收敛为 SkillRegistry.execute 的统一洋葱链——Planner 只决策，能力实现只做本职，
Runtime 边界在链上即插即用。

当前已收敛：``CircuitBreakerMiddleware``（熔断）、``GuardMiddleware``（超时 +
失败降级，WS-7）、``ToolResultCompressionMiddleware``（结果外置）。
演进中：retry（Planner 编排循环的"证据为空重新路由"属编排语义，不迁移；
执行级异常重试待真实需求出现再挂链）、rate limit（admission 队列待接入）。
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from agent_runtime.circuit_breaker import CircuitBreaker
from agent_runtime.context.tool_result import ToolResultCompressor

logger = logging.getLogger(__name__)

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


class GuardMiddleware:
    """超时隔离 + 失败降级中间件（WS-7：``agent_core.tools.guarded_invoke`` 的
    async-native 等价物，语义对齐：超时/异常 → fallback，**绝不向上抛**）。

    与内核 guarded_invoke 的差异：async-native（``asyncio.wait_for`` 真正取消
    等待，不占线程池）；新代码应优先挂本中间件而非再包 ``wrap_tool``。

    - ``timeout_s``：单次 Skill 调用超时上界；
    - ``fallback``：超时/异常时的降级返回值（默认 ``{}``，等价该路未产出，
      与 guarded_invoke 一致；evidence 型 Skill 可传降级提示列表）；
    - ``skill_names``：None 时作用于全部技能，否则仅包裹指定技能。
    """

    def __init__(
        self,
        timeout_s: float = 3.0,
        fallback: Any = None,
        *,
        skill_names: tuple[str, ...] | None = None,
    ) -> None:
        self._timeout_s = timeout_s
        self._fallback = {} if fallback is None else fallback
        self._skill_names = skill_names

    async def around(self, name: str, kwargs: dict[str, Any], call_next: CallNext) -> Any:
        if self._skill_names is not None and name not in self._skill_names:
            return await call_next(name, kwargs)
        try:
            return await asyncio.wait_for(call_next(name, kwargs), timeout=self._timeout_s)
        except asyncio.TimeoutError:
            logger.warning("skill %s 超时（> %.1fs），降级返回 fallback", name, self._timeout_s)
            return self._fallback
        except Exception:  # noqa: BLE001 —— 单路失败降级，绝不向上抛
            logger.exception("skill %s 执行失败，降级返回 fallback", name)
            return self._fallback


class ToolResultCompressionMiddleware:
    """工具结果压缩中间件（Plan-F Context Pipeline P1）：超预算结果外置 + 截断视图。

    挂在本洋葱链上，工具本身不感知：``around`` 在 call_next 之后把结果交给
    ``ToolResultCompressor``，返回 ``{text, ref, full_path, truncated}`` 结构
    （text 是上下文可用的视图，完整结果已外置到 store_dir）。

    ``skill_names`` 为 None 时作用于全部技能（默认）；否则仅包裹指定技能。
    """

    def __init__(
        self,
        max_tokens: int = 8192,
        store_dir=None,
        model: str | None = None,
        *,
        skill_names: tuple[str, ...] | None = None,
    ) -> None:
        self._compressor = ToolResultCompressor(
            max_tokens=max_tokens, store_dir=store_dir, model=model
        )
        self._skill_names = skill_names

    async def around(self, name: str, kwargs: dict[str, Any], call_next: CallNext) -> Any:
        if self._skill_names is not None and name not in self._skill_names:
            return await call_next(name, kwargs)
        result = await call_next(name, kwargs)
        return self._compressor.compress(result)


class RetryMiddleware:
    """执行级瞬态重试中间件（§9.2：与 Planner 级重规划区分——只重试瞬态故障）。

    与 GuardMiddleware 互补：Guard 负责失败降级，Retry 负责在仍有成功机会时
    把瞬时错误（超时 / 限流 429 / 网络抖动）重试 N 次后再交给下游。
    注意：调用方（Planner）可观测性仍以最终成功/失败为准——重试对调用方透明。

    ``is_transient`` 为 None 时默认对 ``asyncio.TimeoutError`` 与名字含
    "RateLimit"/"Timeout"/"Transient"/"Unavailable" 的异常重试。
    """

    def __init__(
        self,
        max_retries: int = 2,
        backoff_s: float = 0.0,
        *,
        skill_names: tuple[str, ...] | None = None,
        is_transient=None,
    ) -> None:
        self._max_retries = max(0, max_retries)
        self._backoff_s = backoff_s
        self._skill_names = skill_names
        self._is_transient = is_transient

    @staticmethod
    def _default_transient(exc: Exception) -> bool:
        if isinstance(exc, asyncio.TimeoutError):
            return True
        name = type(exc).__name__
        return any(
            k in name for k in ("RateLimit", "Timeout", "Transient", "Unavailable")
        )

    async def around(self, name: str, kwargs: dict[str, Any], call_next: CallNext) -> Any:
        if self._skill_names is not None and name not in self._skill_names:
            return await call_next(name, kwargs)
        is_transient = self._is_transient or self._default_transient
        for attempt in range(self._max_retries + 1):
            try:
                return await call_next(name, kwargs)
            except Exception as exc:  # noqa: BLE001 —— 由 is_transient 判定是否重试
                if attempt < self._max_retries and is_transient(exc):
                    if self._backoff_s:
                        await asyncio.sleep(self._backoff_s)
                    continue
                raise


class RateLimitMiddleware:
    """技能级滑动窗口限流中间件（§9.2 Middleware：rate）。

    与 Admission 的三维（user/session/global）入口限流不同，本中间件是
    **执行级**单技能限流，保护易被打挂的下游（如联网搜索/LLM 网关），避免
    单技能在并发 Planner 下被压垮。``limiter.allow(key)`` 返回 False 时
    直接抛 ``SkillExecutionError``（透明失败，交由上游 Guard/Planner 降级或重规划）。

    ``limiter`` 需实现 ``allow(key: str) -> bool``（见 ``SimpleTokenBucket``）。
    """

    def __init__(
        self,
        limiter,
        *,
        skill_names: tuple[str, ...] | None = None,
        key_fn=None,
    ) -> None:
        self._limiter = limiter
        self._skill_names = skill_names
        self._key_fn = key_fn or (lambda name: name)

    async def around(self, name: str, kwargs: dict[str, Any], call_next: CallNext) -> Any:
        if self._skill_names is not None and name not in self._skill_names:
            return await call_next(name, kwargs)
        if not self._limiter.allow(self._key_fn(name)):
            from agent_runtime.skills.registry import SkillExecutionError

            raise SkillExecutionError(f"skill {name} 触发执行级限流")
        return await call_next(name, kwargs)


class SimpleTokenBucket:
    """进程内令牌桶（RateLimitMiddleware 的默认 limiter）。

    非线程安全；async 单进程内足够。``rate`` 为每秒补充令牌数，
    ``capacity`` 为桶容量。``allow`` 原子扣减并返回是否放行。
    """

    def __init__(self, rate: float, capacity: int) -> None:
        self._rate = rate
        self._capacity = capacity
        self._tokens = float(capacity)
        self._last = time.monotonic()

    def allow(self, key: str = "") -> bool:  # key 仅占位，单桶语义
        now = time.monotonic()
        self._tokens = min(
            self._capacity, self._tokens + (now - self._last) * self._rate
        )
        self._last = now
        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return True
        return False


class AuditMiddleware:
    """审计中间件（§9.2 Middleware：audit）——记录每次技能调用的审计事件。

    ``sink`` 为 ``async def record(name, kwargs, result, error, latency_s)``。
    无论成功/失败均落审计（finally 保证），但**不吞异常/不降级**——审计是旁路观察。

    用途：合规留痕、攻击溯源（谁调了什么 skill、输入/输出/耗时/是否报错）。
    与 tracing 不同：tracing 关注链路，audit 关注不可变记录留存。
    """

    def __init__(
        self,
        sink,
        *,
        skill_names: tuple[str, ...] | None = None,
        redact: bool = False,
    ) -> None:
        self._sink = sink
        self._skill_names = skill_names
        self._redact = redact

    async def around(self, name: str, kwargs: dict[str, Any], call_next: CallNext) -> Any:
        if self._skill_names is not None and name not in self._skill_names:
            return await call_next(name, kwargs)
        t0 = time.monotonic()
        result: Any = None
        error: str | None = None
        try:
            result = await call_next(name, kwargs)
            return result
        except Exception as exc:
            error = str(exc)
            raise
        finally:
            logged_kwargs = {"<redacted>": True} if self._redact else kwargs
            try:
                await self._sink(name, logged_kwargs, result, error, time.monotonic() - t0)
            except Exception:  # noqa: BLE001 —— 审计旁路故障不影响主链路
                logger.warning("audit sink 失败（已忽略）", exc_info=True)
