# -*- coding: utf-8 -*-
"""通用可靠性原语（框架无关内核，零依赖）。

生产环境常用的降级 / 容错工具，全部仅依赖 stdlib，可独立 import：

- ``retry``：带指数退避的同步重试装饰器；
- ``retry_async``：带指数退避的异步重试（直接函数式调用，供 async 调用点复用）；
- ``timeout``：函数调用超时包装（基于线程池，跨平台）；
- ``CircuitBreaker``：熔断开关（失败率超阈值后短时拒绝，恢复期半开探测）；
- ``validate_config``：轻量配置校验与默认值填充。

无 RAG / 无宿主依赖；可作为 agent_core 之外独立复用的可靠性层。
"""

from __future__ import annotations

import asyncio
import inspect
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from functools import wraps
from typing import Any, Awaitable, Callable, Iterable, Optional, Type, TypeVar

F = TypeVar("F", bound=Callable[..., Any])


# ---------------------------------------------------------------------------
# retry
# ---------------------------------------------------------------------------
def retry(
    max_attempts: int = 3,
    backoff_base: float = 0.5,
    backoff_factor: float = 2.0,
    exceptions: "Iterable[Type[BaseException]] | Type[BaseException]" = Exception,
    sleep: Callable[[float], None] = time.sleep,
) -> Callable[[F], F]:
    """同步函数重试装饰器：失败按指数退避重试，直到成功或达到 max_attempts。

    :param max_attempts: 最大尝试次数（含首次），>= 1。
    :param backoff_base: 首次退避秒数。
    :param backoff_factor: 退避乘数（第 n 次等待 = backoff_base * backoff_factor ** (n-1)）。
    :param exceptions: 触发重试的异常类型（单个或元组）；其它异常直接抛出。
    :param sleep: 退避用的 sleep 函数（默认 time.sleep，可注入以便测试）。
    """
    if max_attempts < 1:
        raise ValueError("max_attempts 必须 >= 1")
    exc_types = exceptions if isinstance(exceptions, tuple) else (exceptions,)

    def decorator(fn: F) -> F:
        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exc: Optional[BaseException] = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except exc_types as exc:  # type: ignore[misc]
                    last_exc = exc
                    if attempt >= max_attempts:
                        break
                    wait = backoff_base * (backoff_factor ** (attempt - 1))
                    sleep(wait)
            assert last_exc is not None
            raise last_exc

        return wrapper  # type: ignore[return-value]

    return decorator


# ---------------------------------------------------------------------------
# retry_async
# ---------------------------------------------------------------------------
async def retry_async(
    fn: Callable[..., Awaitable[Any]],
    *args: Any,
    max_attempts: int = 3,
    backoff_base: float = 0.5,
    backoff_factor: float = 2.0,
    exceptions: "Iterable[Type[BaseException]] | Type[BaseException]" = Exception,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    on_retry: "Optional[Callable[[BaseException, int], Any]]" = None,
    **kwargs: Any,
) -> Any:
    """异步函数重试：失败按指数退避重试，直到成功或达到 max_attempts。

    与同步 ``retry`` 语义一致，但面向 async/await 调用点：
    ``sleep`` 默认为 ``asyncio.sleep``（不阻塞事件循环），并可注入以便测试。

    :param fn: 异步可调用对象（返回 awaitable），支持位置/关键字参数透传。
    :param max_attempts: 最大尝试次数（含首次），>= 1。
    :param backoff_base: 首次退避秒数。
    :param backoff_factor: 退避乘数（第 n 次等待 = backoff_base * backoff_factor ** (n-1)）。
    :param exceptions: 触发重试的异常类型（单个或元组）；其它异常直接抛出。
    :param sleep: 退避用的异步 sleep 函数（默认 asyncio.sleep，可注入以便测试）。
    :param on_retry: 每次重试前的回调 (exc, attempt)，attempt 从 1 开始；
        支持同步与异步回调（返回 coroutine 时自动 await）。
    :return: fn 的成功返回值；全部尝试失败则抛出最后一次异常。
    """
    if max_attempts < 1:
        raise ValueError("max_attempts 必须 >= 1")
    exc_types = exceptions if isinstance(exceptions, tuple) else (exceptions,)
    last_exc: Optional[BaseException] = None
    for attempt in range(1, max_attempts + 1):
        try:
            return await fn(*args, **kwargs)
        except exc_types as exc:  # type: ignore[misc]
            last_exc = exc
            if attempt >= max_attempts:
                break
            if on_retry is not None:
                result = on_retry(exc, attempt)
                if inspect.isawaitable(result):
                    await result
            await sleep(backoff_base * (backoff_factor ** (attempt - 1)))
    assert last_exc is not None
    raise last_exc


# ---------------------------------------------------------------------------
# timeout
# ---------------------------------------------------------------------------
def timeout(seconds: float, executor: Optional[ThreadPoolExecutor] = None) -> Callable[[F], F]:
    """同步函数超时装饰器：超时则抛出 TimeoutError（在独立线程执行，跨平台）。

    :param seconds: 超时秒数（> 0）。
    :param executor: 可选线程池；缺省每次调用新建一个单线程池（调用后关闭）。
    """
    if seconds <= 0:
        raise ValueError("seconds 必须 > 0")

    def decorator(fn: F) -> F:
        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            ex = executor or ThreadPoolExecutor(max_workers=1)
            try:
                future = ex.submit(fn, *args, **kwargs)
                try:
                    return future.result(timeout=seconds)
                except FuturesTimeoutError:
                    raise TimeoutError(
                        f"调用 {getattr(fn, '__name__', '<func>')} 超时（> {seconds}s）"
                    ) from None
            finally:
                if executor is None:
                    ex.shutdown(wait=False)

        return wrapper  # type: ignore[return-value]

    return decorator


# ---------------------------------------------------------------------------
# CircuitBreaker
# ---------------------------------------------------------------------------
class CircuitBreaker:
    """简单熔断器：连续失败达到阈值后进入 OPEN（拒绝调用），冷却后转 HALF_OPEN 探测，
    探测成功则回 CLOSED，失败则回到 OPEN。

    状态：CLOSED（正常） / OPEN（熔断拒绝） / HALF_OPEN（探测中）。
    """

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(
        self,
        failure_threshold: int = 5,
        reset_timeout: float = 30.0,
        max_half_open_probe: int = 1,
        clock: Callable[[], float] = time.monotonic,
        exceptions: "Iterable[Type[BaseException]] | Type[BaseException]" = Exception,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold 必须 >= 1")
        if max_half_open_probe < 1:
            raise ValueError("max_half_open_probe 必须 >= 1")
        self._failure_threshold = failure_threshold
        self._reset_timeout = reset_timeout
        self._max_half_open_probe = max_half_open_probe
        self._clock = clock
        self._exc_types = exceptions if isinstance(exceptions, tuple) else (exceptions,)
        self._state = self.CLOSED
        self._failures = 0
        self._opened_at: Optional[float] = None
        # HALF_OPEN 期间在飞的探测请求数；超过上限的并发 probe 被拒绝，
        # 否则 OPEN→HALF_OPEN 后所有并发请求都会成为 probe（审计 P1 #六）。
        self._half_open_inflight = 0

    @property
    def state(self) -> str:
        return self._state

    def _maybe_transition(self) -> None:
        if self._state == self.OPEN and self._opened_at is not None:
            if self._clock() - self._opened_at >= self._reset_timeout:
                self._state = self.HALF_OPEN

    def allow(self) -> bool:
        """调用前查询：是否允许执行（OPEN 且冷却未到则拒绝）。

        HALF_OPEN 时限制并发探测数（max_half_open_probe）：已达到上限的
        并发请求会被拒绝（视为仍 OPEN），避免 100 个并发请求同时成为 probe。
        """
        self._maybe_transition()
        if self._state == self.OPEN:
            return False
        if self._state == self.HALF_OPEN:
            if self._half_open_inflight < self._max_half_open_probe:
                self._half_open_inflight += 1
                return True
            return False
        return True

    def _end_half_open_probe(self) -> None:
        if self._half_open_inflight > 0:
            self._half_open_inflight -= 1

    def record_success(self) -> None:
        if self._state == self.HALF_OPEN:
            self._end_half_open_probe()
        self._failures = 0
        self._state = self.CLOSED

    def record_failure(self) -> None:
        if self._state == self.HALF_OPEN:
            self._end_half_open_probe()
            self._state = self.OPEN
            self._opened_at = self._clock()
            return
        self._failures += 1
        if self._failures >= self._failure_threshold:
            self._state = self.OPEN
            self._opened_at = self._clock()

    def call(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """受熔断保护地执行 fn：拒绝时抛 RuntimeError；否则按结果记录成功/失败。"""
        if not self.allow():
            raise RuntimeError("熔断器处于 OPEN 状态，暂时拒绝调用")
        try:
            result = fn(*args, **kwargs)
        except self._exc_types:  # type: ignore[misc]
            self.record_failure()
            raise
        self.record_success()
        return result


# ---------------------------------------------------------------------------
# config validation
# ---------------------------------------------------------------------------
def validate_config(
    config: dict,
    *,
    required: Iterable[str] = (),
    types: Optional[dict] = None,
    defaults: Optional[dict] = None,
) -> dict:
    """轻量配置校验与默认值填充。

    :param config: 用户配置 dict。
    :param required: 必填键集合；缺失抛 ValueError。
    :param types: {key: type}，类型不符抛 TypeError。
    :param defaults: {key: value}，缺失时填充。
    :return: 合并默认值后的新 dict（不修改入参）。
    """
    out = dict(defaults or {})
    out.update(config)
    types = types or {}
    for key in required:
        if key not in out or out[key] is None:
            raise ValueError(f"配置缺少必填项: {key}")
    for key, expected in types.items():
        if key in out and out[key] is not None and not isinstance(out[key], expected):
            raise TypeError(
                f"配置项 {key} 类型错误：期望 {expected.__name__}，实际 {type(out[key]).__name__}"
            )
    return out


__all__ = ["retry", "retry_async", "timeout", "CircuitBreaker", "validate_config"]
