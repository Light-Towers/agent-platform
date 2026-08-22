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
import threading
import time
import urllib.error
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from enum import Enum
from functools import wraps
from typing import Any, Awaitable, Callable, Iterable, Optional, Protocol, Type, TypeVar, List

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
        重试边界指引：transport 层（SDK/HTTP 客户端）已有 1–2 次短重试，此处业务重试
        应仅对 ``agent_core.resilience.RetryableError`` 等**已判定可重试**的异常重试，
        避免 ``exceptions=Exception`` 式全量重试与底层叠加成指数级重试风暴。
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
# 异常分类（M1.1：记录异常 ≠ 正确处理异常；作为 Execution HA 前置能力）
# ---------------------------------------------------------------------------
class ErrorClass(Enum):
    """异常三类执行控制语义：执行层据此决定 重试 / 降级 / 终止。

    不做大型异常继承树，仅一个枚举表达「控制意图」。
    """

    RETRYABLE = "retryable"  # 瞬态故障：有限次业务重试
    RECOVERABLE = "recoverable"  # 可降级：fallback/skip，继续执行
    FATAL = "fatal"  # 致命：立即终止当前 execution，不重试


class RetryableError(Exception):
    """显式标记：瞬态可重试（新代码主动 raise 用；类名含 Retryable 亦被启发式命中）。"""


class FatalError(Exception):
    """显式标记：致命不可恢复（checkpoint 损坏 / 状态不一致 / 编程错误包装）。"""


# 白名单（优先级低于标记异常，高于默认）
_RETRYABLE_TYPES: tuple[type[BaseException], ...] = (
    asyncio.TimeoutError,
    TimeoutError,
    ConnectionError,
    urllib.error.URLError,
)
_FATAL_TYPES: tuple[type[BaseException], ...] = (
    TypeError,
    ValueError,
    KeyError,
    AttributeError,
    AssertionError,
    ArithmeticError,
    RecursionError,
)
_TRANSIENT_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
_TRANSIENT_NAME_KEYS = ("RateLimit", "Timeout", "Transient", "Unavailable", "Retryable")


def classify_exception(exc: BaseException) -> ErrorClass:
    """把异常归入三类执行控制语义（最小分类层，不做大型异常体系）。

    优先级：标记异常 > 类型白名单 > ``status_code`` 属性 > 类名启发式 > 默认。

    - RETRYABLE：瞬态信号（超时 / 连接失败 / 429|5xx / 名字启发式 / ``RetryableError``）；
    - FATAL：编程错误与状态不一致（``TypeError``/``ValueError``/... 或 ``FatalError``）；
    - RECOVERABLE：未归类的第三方异常默认降级继续（保守可用性，已知错误均已显式归类）。

    ``KeyboardInterrupt`` / ``SystemExit`` 属 ``BaseException``，调用方不应捕获，
    此处一律判 FATAL 以阻止其被静默降级。
    """
    if isinstance(exc, (KeyboardInterrupt, SystemExit)):
        return ErrorClass.FATAL
    if isinstance(exc, (RetryableError, FatalError)):
        return ErrorClass.RETRYABLE if isinstance(exc, RetryableError) else ErrorClass.FATAL
    if isinstance(exc, _FATAL_TYPES):
        return ErrorClass.FATAL
    if isinstance(exc, _RETRYABLE_TYPES):
        return ErrorClass.RETRYABLE
    status = getattr(exc, "status_code", None)
    if isinstance(status, int) and status in _TRANSIENT_STATUS_CODES:
        return ErrorClass.RETRYABLE
    name = type(exc).__name__
    if any(k in name for k in _TRANSIENT_NAME_KEYS):
        return ErrorClass.RETRYABLE
    return ErrorClass.RECOVERABLE


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
# CircuitBreaker Engine + Policy Strategy (WS-3: 统一引擎 + 策略分离)
# ---------------------------------------------------------------------------
# 状态常量（内核单一真相，适配层不再各自定义字符串）
STATE_CLOSED = "closed"
STATE_OPEN = "open"
STATE_HALF_OPEN = "half_open"


class _Policy(Protocol):
    """熔断策略协议：定义如何根据执行结果判断状态转换。"""

    def on_success(self, breaker: "CircuitBreaker") -> None:
        """成功时的状态更新逻辑。"""
        ...

    def on_failure(self, breaker: "CircuitBreaker") -> None:
        """失败时的状态更新逻辑。"""
        ...

    def check_transition(self, breaker: "CircuitBreaker") -> None:
        """检查是否需要自动转换状态（如 OPEN→HALF_OPEN 冷却期到期）。"""
        ...


class ConsecutiveFailurePolicy:
    """连续失败计数策略（原 CircuitBreaker 行为）。

    连续失败达到阈值 → OPEN；冷却后 HALF_OPEN；连续成功 → CLOSED。
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        reset_timeout: float = 30.0,
        max_half_open_probe: int = 1,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold 必须 >= 1")
        if max_half_open_probe < 1:
            raise ValueError("max_half_open_probe 必须 >= 1")
        self._failure_threshold = failure_threshold
        self._reset_timeout = reset_timeout
        self._max_half_open_probe = max_half_open_probe
        self._clock = clock

    def on_success(self, breaker: "CircuitBreaker") -> None:
        with breaker._lock:
            if breaker._state == breaker.HALF_OPEN:
                breaker._half_open_inflight = max(0, breaker._half_open_inflight - 1)
            breaker._failures = 0
            breaker._state = breaker.CLOSED

    def on_failure(self, breaker: "CircuitBreaker") -> None:
        with breaker._lock:
            if breaker._state == breaker.HALF_OPEN:
                breaker._half_open_inflight = max(0, breaker._half_open_inflight - 1)
                breaker._state = breaker.OPEN
                breaker._opened_at = breaker._clock()
                return
            breaker._failures += 1
            if breaker._failures >= breaker._failure_threshold:
                breaker._state = breaker.OPEN
                breaker._opened_at = breaker._clock()

    def check_transition(self, breaker: "CircuitBreaker") -> None:
        with breaker._lock:
            if breaker._state == breaker.OPEN and breaker._opened_at is not None:
                if breaker._clock() - breaker._opened_at >= breaker._reset_timeout:
                    breaker._state = breaker.HALF_OPEN


class SlidingWindowPolicy:
    """滑动窗口失败率策略（agent_federation 原行为）。

    滑动窗口内失败率超过阈值 → OPEN；冷却后 HALF_OPEN；连续探测成功 → CLOSED。
    """

    def __init__(
        self,
        failure_ratio: float = 0.5,
        min_requests: int = 5,
        window_size: int = 20,
        cooldown_seconds: float = 30.0,
        half_open_probes: int = 3,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not 0 <= failure_ratio <= 1:
            raise ValueError("failure_ratio 必须在 [0, 1] 范围内")
        if min_requests < 1:
            raise ValueError("min_requests 必须 >= 1")
        if half_open_probes < 1:
            raise ValueError("half_open_probes 必须 >= 1")
        self._failure_ratio = failure_ratio
        self._min_requests = min_requests
        self._window_size = window_size
        self._cooldown_seconds = cooldown_seconds
        self._half_open_probes = half_open_probes
        self._clock = clock

    def on_success(self, breaker: "CircuitBreaker") -> None:
        with breaker._lock:
            if breaker._state == breaker.HALF_OPEN:
                breaker._half_open_successes += 1
                if breaker._half_open_successes >= breaker._half_open_probes:
                    breaker._successes.clear()
                    breaker._failures_list.clear()
                    breaker._state = breaker.CLOSED
                return
            breaker._successes.append(breaker._clock())
            breaker._trim()

    def on_failure(self, breaker: "CircuitBreaker") -> None:
        with breaker._lock:
            if breaker._state == breaker.HALF_OPEN:
                breaker._opened_at = breaker._clock()
                breaker._half_open_successes = 0
                breaker._state = breaker.OPEN
                return
            breaker._failures_list.append(breaker._clock())
            breaker._trim()
            breaker._evaluate_locked()

    def check_transition(self, breaker: "CircuitBreaker") -> None:
        with breaker._lock:
            if breaker._state == breaker.OPEN and breaker._opened_at is not None:
                if breaker._clock() - breaker._opened_at >= breaker._cooldown_seconds:
                    breaker._half_open_successes = 0
                    breaker._state = breaker.HALF_OPEN


class CircuitBreaker:
    """统一熔断器引擎（WS-3: Engine + Policy 分离）。

    - 支持同步/异步调用
    - 策略可插拔：ConsecutiveFailurePolicy / SlidingWindowPolicy
    - 线程/协程安全：内部锁保护所有状态变更
    - 状态常量：CLOSED / OPEN / HALF_OPEN (内核用下划线，适配层自行转连字符)
    """

    CLOSED = STATE_CLOSED
    OPEN = STATE_OPEN
    HALF_OPEN = STATE_HALF_OPEN

    def __init__(
        self,
        policy=None,
        *,
        exceptions: "Iterable[Type[BaseException]] | Type[BaseException]" = Exception,
        clock: Callable[[], float] = time.monotonic,
        # ConsecutiveFailurePolicy 配置
        failure_threshold: int = 5,
        reset_timeout: float = 30.0,
        max_half_open_probe: int = 1,
        # SlidingWindowPolicy 配置
        failure_ratio: float = 0.5,
        min_requests: int = 5,
        window_size: int = 20,
        cooldown_seconds: float = 30.0,
        half_open_probes: int = 3,
    ) -> None:
        # 判断策略类型
        if isinstance(policy, ConsecutiveFailurePolicy):
            self._policy = policy
        elif isinstance(policy, SlidingWindowPolicy):
            self._policy = policy
        elif isinstance(policy, type) and issubclass(policy, ConsecutiveFailurePolicy):
            self._policy = policy(
                failure_threshold=failure_threshold,
                reset_timeout=reset_timeout,
                max_half_open_probe=max_half_open_probe,
            )
        elif isinstance(policy, type) and issubclass(policy, SlidingWindowPolicy):
            self._policy = policy(
                failure_ratio=failure_ratio,
                min_requests=min_requests,
                window_size=window_size,
                cooldown_seconds=cooldown_seconds,
                half_open_probes=half_open_probes,
            )
        else:
            # 默认 ConsecutiveFailurePolicy
            self._policy = ConsecutiveFailurePolicy(
                failure_threshold=failure_threshold,
                reset_timeout=reset_timeout,
                max_half_open_probe=max_half_open_probe,
            )

        self._exc_types = Exception
        self._lock = threading.RLock()

        # 运行时状态（兼容两种策略所需字段）
        self._state = self.CLOSED
        self._failures: int = 0
        self._failures_list: List[float] = []
        self._successes: List[float] = []
        self._opened_at: Optional[float] = None
        self._half_open_inflight = 0
        self._half_open_successes = 0
        # 兼容旧参数名：max_half_open_probe 映射到 half_open_probes
        self._half_open_probes = half_open_probes if half_open_probes != 3 else max_half_open_probe
        self._successes: List[float] = []
        self._failures_list: List[float] = []
        self._window_size = window_size
        self._cooldown_seconds = cooldown_seconds
        self._failure_threshold = failure_threshold
        self._reset_timeout = reset_timeout
        self._max_half_open_probe = max_half_open_probe
        self._clock = clock
        self._failure_ratio = failure_ratio
        self._min_requests = min_requests
        self._window_size = window_size
        self._cooldown_seconds = cooldown_seconds
        # self._half_open_probes = half_open_probes  # 已在上方设置，避免重复覆盖

        self._lock = threading.RLock()
        self._clock = clock
        self._exc_types = Exception
        self._state = self.CLOSED

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    def resolved_state(self) -> str:
        """返回计入冷却期后的等效状态（OPEN 且冷却到期 → HALF_OPEN）。"""
        with self._lock:
            self._policy.check_transition(self)
            return self._state

    def allow(self) -> bool:
        """调用前查询：是否允许执行（OPEN 且冷却未到则拒绝）。"""
        with self._lock:
            self._policy.check_transition(self)
            if self._state == self.OPEN:
                return False
            if self._state == self.HALF_OPEN:
                if self._half_open_inflight < self._half_open_probes:
                    self._half_open_inflight += 1
                    return True
                return False
            return True

    def _end_half_open_probe(self) -> None:
        if self._half_open_inflight > 0:
            self._half_open_inflight -= 1

    def record_success(self) -> None:
        with self._lock:
            self._policy.on_success(self)

    def record_failure(self) -> None:
        with self._lock:
            self._policy.on_failure(self)

    def call(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """受熔断保护地执行 fn：拒绝时抛 RuntimeError；否则按结果记录成功/失败。"""
        if not self.allow():
            raise RuntimeError("熔断器处于 OPEN 状态，暂时拒绝调用")
        try:
            result = fn(*args, **kwargs)
        except Exception:
            self.record_failure()
            raise
        self.record_success()
        return result

    # SlidingWindowPolicy 需要的辅助方法
    def _trim(self) -> None:
        for bucket in (self._successes, self._failures_list):
            while len(bucket) > self._window_size:
                bucket.pop(0)

    def _evaluate_locked(self) -> None:
        if self._state != self.CLOSED:
            return
        total = len(self._successes) + len(self._failures_list)
        if total < self._window_size:
            return
        failures = len(self._failures_list)
        if failures / total >= self._failure_ratio:
            self._opened_at = self._clock()
            self._state = self.OPEN


# 向后兼容：保留原 CircuitBreaker 类名，默认使用 ConsecutiveFailurePolicy
class _LegacyCircuitBreaker(CircuitBreaker):
    """向后兼容的旧接口：默认使用 ConsecutiveFailurePolicy。"""

    def __init__(
        self,
        failure_threshold: int = 5,
        reset_timeout: float = 30.0,
        max_half_open_probe: int = 1,
        clock: Callable[[], float] = time.monotonic,
        exceptions: "Iterable[Type[BaseException]] | Type[BaseException]" = Exception,
    ) -> None:
        policy = ConsecutiveFailurePolicy(
            failure_threshold=failure_threshold,
            reset_timeout=reset_timeout,
            max_half_open_probe=max_half_open_probe,
        )
        super().__init__(policy=policy, exceptions=exceptions)
        # 同步旧字段名供旧代码读取
        self._failure_threshold = failure_threshold
        self._reset_timeout = reset_timeout
        self._max_half_open_probe = max_half_open_probe
        self._clock = time.monotonic