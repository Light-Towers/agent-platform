# -*- coding: utf-8 -*-
"""
OTel 全链路追踪基础设施（框架无关内核，源自 zhiku M4 tracing）。

设计原则：
1. **懒导入 + no-op 降级铁律**：opentelemetry 为**可选依赖**（``pyproject.toml``
   ``[project.optional-dependencies] tracing``）。本模块在 import 时 try 导入 SDK，
   缺包 / 未显式 init（endpoint 为空或未启用）时，所有 span 调用走 no-op，
   **零性能损耗、绝不抛异常** —— 保证本地无 collector、CI 无 OTel 也全绿。
2. **幂等 init**：``init_tracing()`` 可重复调用，只有首次调用会创建 TracerProvider / exporter，
   重复调用直接返回既有 tracer。
3. **统一 span 属性**：``config_hash`` / ``collection``（静态，init 时写入）与
   ``request_id`` / ``user_query_hash``（每请求，经 ``contextvars`` 传递）自动合并到每个 span。
4. **导出器可选**：OTLP gRPC / HTTP exporter 亦为懒导入；未安装时记录警告并降级 no-op。
5. **框架无关**：不 import 任何宿主应用（如 app.core.config / app.conf.*）；
   ``collection`` / ``config_hash`` 的统一属性通过 ``init_tracing`` 参数**注入**，
   默认回退仅读中性环境变量，**不硬编码任何宿主路径**。

环境变量：
    - ``OTEL_EXPORTER_OTLP_ENDPOINT``：OTLP 导出端点，默认空 → no-op；
    - ``AGENT_CORE_SERVICE_NAME``：服务名，默认 ``agent-core``；
    - ``AGENT_CORE_TRACE_ENABLED``：总开关，默认 ``false``（置 true 且 endpoint 非空才真实导出）。
"""

import contextvars
import hashlib
import os
import threading
import uuid
from contextlib import contextmanager
from functools import wraps
from typing import Any, Callable, Dict, Iterator, Optional

from agent_core.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# 环境变量配置项（中性，不绑定任何宿主应用）
# ---------------------------------------------------------------------------
ENV_OTEL_ENDPOINT = "OTEL_EXPORTER_OTLP_ENDPOINT"
ENV_SERVICE_NAME = "AGENT_CORE_SERVICE_NAME"
ENV_TRACE_ENABLED = "AGENT_CORE_TRACE_ENABLED"
DEFAULT_SERVICE_NAME = "agent-core"

# ---------------------------------------------------------------------------
# 运行状态（模块级；init 在启动阶段调用一次，之后只读，线程安全）
# 全仓**唯一**观测状态机：任何宿主（含 agent_runtime.otel 薄门面）都不得自持
# 第二套 enabled/tracer 全局态，否则跨服务传播门（tracing_propagation）与
# 实际初始化脱钩（R6：traceparent 静默断裂的根因）。lint L-3 拦截私起 init。
# 三态语义（运维可区分“显式关”与“启用但坏了”，R5）：
#   UNINITIALIZED 未调 init / DISABLED 显式关闭或未配置 / 
#   DEGRADED      请求启用但初始化失败（reason 记真因）/ ACTIVE 真实导出
# ---------------------------------------------------------------------------
_initialized: bool = False
_enabled: bool = False
_status: str = "UNINITIALIZED"
_status_reason: str = ""
_tracer: Any = None
_provider: Any = None
_base_attrs: Dict[str, Any] = {}
_state_lock = threading.Lock()

# 每请求上下文：request_id / trace_id / span_id / user_query_hash 走 contextvars，
# 使并发请求互不污染。
_request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("agent_core_request_id", default="")
_trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("agent_core_trace_id", default="")
_span_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("agent_core_span_id", default="")
_user_query_hash_var: contextvars.ContextVar[str] = contextvars.ContextVar("agent_core_user_query_hash", default="")

# ---------------------------------------------------------------------------
# 懒导入 OpenTelemetry SDK（缺包自动 no-op）
# ---------------------------------------------------------------------------
_otel_trace: Any = None
_SDK_AVAILABLE: bool = False
try:
    from opentelemetry import trace as _otel_trace
    from opentelemetry.sdk.resources import Resource as _Resource
    from opentelemetry.sdk.trace import TracerProvider as _SDKTracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor as _BatchSpanProcessor
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor as _SimpleSpanProcessor

    _SDK_AVAILABLE = True
except ImportError:  # pragma: no cover - 依赖缺失路径（CI / 本地无 OTel）
    _otel_trace = None
    _SDK_AVAILABLE = False

# OTLP exporter（可选，懒导入；缺包时 _OTLP_EXPORTER_CLS=None → no-op 降级）
_OTLP_EXPORTER_CLS: Optional[type] = None
if _SDK_AVAILABLE:
    for _exporter_module_name in (
        "opentelemetry.exporter.otlp.proto.http.trace_exporter",
        "opentelemetry.exporter.otlp.proto.grpc.trace_exporter",
    ):
        try:
            _exporter_module = __import__(_exporter_module_name, fromlist=["OTLPSpanExporter"])
            _OTLP_EXPORTER_CLS = getattr(_exporter_module, "OTLPSpanExporter")
            break
        except ImportError:  # pragma: no cover - exporter 未安装路径
            continue


# ---------------------------------------------------------------------------
# no-op shim（SDK 不可用 / 未启用时的零开销替身）
# ---------------------------------------------------------------------------
class _NoOpSpan:
    """no-op span：所有方法零开销、绝不抛异常。"""

    __slots__ = ()

    def set_attribute(self, key: str, value: Any) -> None:
        return None

    def set_attributes(self, attributes: Dict[str, Any]) -> None:
        return None

    def record_exception(self, exception: BaseException, attributes: Optional[Dict[str, Any]] = None) -> None:
        return None

    def set_status(self, status: Any, description: Optional[str] = None) -> None:
        return None

    def end(self) -> None:
        return None

    def is_recording(self) -> bool:
        return False


class _NoOpSpanContextManager:
    """no-op 上下文管理器，保证 ``with start_span(...)`` 可用且不抛异常。

    注：不提供 ``__getattr__`` 向 span 方法的兜底转发——该兼容 hack 曾掩盖
    app 层“手动 CM 上调 span.set_attribute”的误用（NoOp 态隐形、真 SDK 态 500，
    复盘 R7/R8）。误用应被 L-1 lint 拦截，替身必须与真实现同样报错。
    """

    __slots__ = ("_span",)

    def __init__(self) -> None:
        self._span = _NoOpSpan()

    def __enter__(self) -> _NoOpSpan:
        return self._span

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> bool:
        return False  # 不吞异常


class _NoOpTracer:
    """no-op tracer：start_span / start_as_current_span 均可用。"""

    __slots__ = ()

    def start_span(self, name: str, *args: Any, **kwargs: Any) -> _NoOpSpan:
        return _NoOpSpan()

    def start_as_current_span(self, name: str, *args: Any, **kwargs: Any) -> _NoOpSpanContextManager:
        return _NoOpSpanContextManager()


def _make_noop_tracer() -> Any:
    """构造 no-op tracer（不依赖 OTel 全局 provider 状态，确定性零开销）。"""
    return _NoOpTracer()


def noop_tracer() -> Any:
    """公开 no-op tracer 工厂：供下游包（agent-runtime 等）复用，避免各自再造 shim。

    语义与 :func:`_make_noop_tracer` 一致：零开销、绝不抛异常。
    """
    return _make_noop_tracer()


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
def _as_bool(value: Optional[str], default: bool = False) -> bool:
    """将环境变量字符串解析为 bool；None 时返回默认值。"""
    if value is None:
        return default
    return str(value).strip().lower() in ("true", "1")


# 统一 span 属性（collection / config_hash）的默认回退解析器。
# 框架无关：仅读中性环境变量；宿主应用应通过 init_tracing(collection=, config_hash=)
# 注入自己的真实值，而不要依赖此处回退。
def _default_collection() -> str:
    """默认集合名：中性环境变量回退（不硬编码任何宿主路径）。"""
    return os.getenv("AGENT_CORE_COLLECTION", "")


def _default_config_hash() -> str:
    """默认 config_hash：中性环境变量回退（不硬编码任何宿主路径）。"""
    return os.getenv("AGENT_CORE_CONFIG_HASH", "")


def _merge_attrs(attrs: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """合并统一 span 属性（config_hash / collection / request_id / user_query_hash）与显式 attrs。"""
    merged = dict(_base_attrs)
    request_id = _request_id_var.get()
    if request_id:
        merged["request_id"] = request_id
    user_query_hash = _user_query_hash_var.get()
    if user_query_hash:
        merged["user_query_hash"] = user_query_hash
    if attrs:
        merged.update(attrs)
    return merged


# OTel API 缺失时的恒定无效 span（current_span 降级替身，写操作静默）。
try:  # pragma: no cover - 取决于可选依赖
    from opentelemetry.trace import INVALID_SPAN as _INVALID_SPAN
except ImportError:
    class _InvalidSpanShim:
        def is_recording(self) -> bool:
            return False

        def set_attribute(self, key: str, value: Any) -> None:
            return None

        def set_attributes(self, attributes: Dict[str, Any]) -> None:
            return None

        def record_exception(self, exception: BaseException, attributes: Optional[Dict[str, Any]] = None) -> None:
            return None

        def set_status(self, status: Any, description: Optional[str] = None) -> None:
            return None

        def update_name(self, name: str) -> None:
            return None

        def end(self) -> None:
            return None

    _INVALID_SPAN: Any = _InvalidSpanShim()


# ---------------------------------------------------------------------------
# 对外 API
# ---------------------------------------------------------------------------
def generate_request_id() -> str:
    """生成请求级 trace id：uuid4 hex 短格式（前 12 位）。"""
    return uuid.uuid4().hex[:12]


def user_query_hash(query: str) -> str:
    """生成用户 query 的稳定哈希：sha256(query) 前 16 位 hex；同 query 同 hash。"""
    return hashlib.sha256((query or "").encode("utf-8")).hexdigest()[:16]


def set_request_context(request_id: Optional[str] = None, user_query_hash: Optional[str] = None) -> None:
    """每请求开始时写入 request_id / user_query_hash 到当前上下文（contextvars，并发安全）。"""
    if request_id is not None:
        _request_id_var.set(request_id)
    if user_query_hash is not None:
        _user_query_hash_var.set(user_query_hash)


def get_request_id() -> str:
    """读取当前上下文中的 request_id（无则空串）。"""
    return _request_id_var.get()


def get_trace_id() -> str:
    """读取当前上下文中的 trace_id（无则空串）。"""
    return _trace_id_var.get()


def get_span_id() -> str:
    """读取当前上下文中的 span_id（无则空串）。"""
    return _span_id_var.get()


def set_trace_context(trace_id: Optional[str] = None, span_id: Optional[str] = None) -> None:
    """设置 trace_id / span_id 到当前上下文（contextvars）。"""
    if trace_id is not None:
        _trace_id_var.set(trace_id)
    if span_id is not None:
        _span_id_var.set(span_id)


def get_traceparent() -> str:
    """生成 W3C traceparent 头部值：version-trace-id-span-id-flags。
    
    格式: 00-trace_id-span_id-01
    trace_id: 32 hex chars (16 bytes)
    span_id: 16 hex chars (8 bytes)
    flags: 01 = sampled
    """
    trace_id = _trace_id_var.get()
    span_id = _span_id_var.get()
    
    # 如果没有 trace_id，生成一个新的 32 字符 trace_id
    if not trace_id:
        trace_id = uuid.uuid4().hex  # 32 hex chars
        _trace_id_var.set(trace_id)
    
    # 如果没有 span_id，生成一个新的 16 字符 span_id
    if not span_id:
        span_id = uuid.uuid4().hex[:16]  # 16 hex chars
        _span_id_var.set(span_id)
    
    return f"00-{trace_id}-{span_id}-01"


def is_tracing_enabled() -> bool:
    """是否处于真实导出模式（SDK 可用 + 总开关开启 + 端点/注入 exporter 就绪）。

    全仓唯一的传播门开关（tracing_propagation 读此处）；宿主经任何入口 init
    （含 agent_runtime.otel 门面）最终都落到本状态机，R6 型断裂不再可能。
    """
    return bool(_enabled)


def get_tracing_status() -> Dict[str, str]:
    """当前观测状态（供 /health 与排障）：UNINITIALIZED / DISABLED / DEGRADED / ACTIVE。

    DEGRADED = 请求启用但初始化失败（reason 记真因）；与“显式关闭”可区分（R5）。
    """
    with _state_lock:
        return {"status": _status, "reason": _status_reason}


def is_initialized() -> bool:
    """init_tracing 是否已被调用过（无论启用与否）。"""
    return bool(_initialized)


def init_tracing(
    service_name: Optional[str] = None,
    otel_endpoint: Optional[str] = None,
    enabled: Optional[bool] = None,
    *,
    exporter: Any = None,
    sampling_rate: Optional[float] = None,
    config_hash: Optional[str] = None,
    collection: Optional[str] = None,
) -> Any:
    """幂等初始化 OTel 追踪（全仓唯一观测状态机，lint L-3 保证只在装配点调用）。

    参数：
        service_name: 服务名（默认读 ``AGENT_CORE_SERVICE_NAME``，再默认 ``agent-core``）
        otel_endpoint: OTLP 导出端点（默认读 ``OTEL_EXPORTER_OTLP_ENDPOINT``，空 → no-op）
        enabled: 总开关（默认读 ``AGENT_CORE_TRACE_ENABLED``，默认 False）
        exporter: 显式 span exporter（单测注入 ``InMemorySpanExporter`` 用；
            宿主门面也可注入 ConsoleSpanExporter 映射 console 导出；生产不传）
        sampling_rate: TraceIdRatioBased 采样率（None/>=1.0 → ALWAYS_ON；非法值钳制 1.0；
            仅在自建 provider 路径生效，复用全局 provider 时采样由宿主决定）
        config_hash / collection: 统一 span 属性，由宿主应用**注入**；
            不传则按中性环境变量回退（绝不读取宿主配置路径）。

    返回：tracer（可能为 no-op tracer，绝不抛异常）。
    """
    global _initialized, _enabled, _tracer, _provider, _status, _status_reason

    service_name = service_name or os.getenv(ENV_SERVICE_NAME, DEFAULT_SERVICE_NAME)
    otel_endpoint = otel_endpoint if otel_endpoint is not None else os.getenv(ENV_OTEL_ENDPOINT, "")
    if enabled is None:
        enabled = _as_bool(os.getenv(ENV_TRACE_ENABLED), False)

    # 采样率校验（与历史门面行为一致：非法钳制 1.0 + 告警）
    sampler = None
    if sampling_rate is not None:
        if not 0.0 <= sampling_rate <= 1.0:
            logger.warning("OTEL_SAMPLING_INVALID: %s, using 1.0", sampling_rate)
            sampling_rate = 1.0
        if sampling_rate < 1.0:
            try:
                from opentelemetry.sdk.trace.sampling import TraceIdRatioBased

                sampler = TraceIdRatioBased(sampling_rate)
            except ImportError:  # pragma: no cover - SDK 缺失路径，后续分支统一降级
                sampler = None

    with _state_lock:
        if _initialized:
            return _tracer

        # 统一 span 属性：优先调用方注入，否则中性环境变量回退。
        _base_attrs["config_hash"] = config_hash if config_hash is not None else _default_config_hash()
        _base_attrs["collection"] = collection if collection is not None else _default_collection()

        can_export = bool(otel_endpoint) or exporter is not None
        if not (_SDK_AVAILABLE and enabled and can_export):
            _initialized = True
            _enabled = False
            _tracer = _make_noop_tracer()
            _provider = None
            if enabled and not _SDK_AVAILABLE:
                # 请求启用但包缺失 → DEGRADED（与“显式关”可区分，R5）
                _status, _status_reason = "DEGRADED", "sdk_not_installed"
                logger.warning(
                    "OTel 启用失败：SDK 未安装（可选 extra tracing：uv sync --extra tracing），"
                    "tracing 降级为 no-op（非‘显式关闭’，status=DEGRADED）"
                )
            elif enabled and not can_export:
                _status, _status_reason = "DEGRADED", "no_export_endpoint"
                logger.warning(
                    "OTel 已启用但未配置导出端点（OTEL_EXPORTER_OTLP_ENDPOINT 为空且未注入 exporter），"
                    "tracing 降级为 no-op，status=DEGRADED"
                )
            else:
                _status, _status_reason = "DISABLED", ""
            return _tracer

        try:
            provider_kwargs: Dict[str, Any] = {
                "resource": _Resource.create({"service.name": service_name})
            }
            if sampler is not None:
                provider_kwargs["sampler"] = sampler
            provider = _SDKTracerProvider(**provider_kwargs)
            if exporter is not None:
                provider.add_span_processor(_SimpleSpanProcessor(exporter))
            else:
                if _OTLP_EXPORTER_CLS is None:
                    logger.warning(
                        "OTLP exporter 未安装（opentelemetry-exporter-otlp-proto-grpc/http），tracing 降级为 no-op"
                    )
                    _initialized = True
                    _enabled = False
                    _status, _status_reason = "DEGRADED", "otlp_exporter_not_installed"
                    _tracer = _make_noop_tracer()
                    _provider = None
                    return _tracer
            # 复用已存在的全局 TracerProvider（如 Langfuse SDK 已先设置），
            # 避免 "Overriding of current TracerProvider is not allowed"。
            # 复用后框架层 span 与 SDK observation 共享同一 trace 树（不重复挂载本地 exporter）。
            existing = _otel_trace.get_tracer_provider()
            if not isinstance(existing, _otel_trace.ProxyTracerProvider):
                provider = existing
                if sampler is not None:
                    logger.info("复用全局 TracerProvider，sampling_rate 不生效（采样由宿主 provider 决定）")
                logger.info("复用已存在的全局 TracerProvider（如 Langfuse SDK），不覆盖")
            else:
                # 仅在本模块自建 provider 时挂 OTLP 导出；复用路径依赖宿主 exporter，避免白挂/重复导出。
                if exporter is None:
                    provider.add_span_processor(_BatchSpanProcessor(_OTLP_EXPORTER_CLS(endpoint=otel_endpoint)))
                try:
                    _otel_trace.set_tracer_provider(provider)
                except Exception:  # pragma: no cover - 防御：全局 provider 设置失败不影响本地 tracer
                    pass
            _provider = provider
            _tracer = provider.get_tracer(service_name)
            _initialized = True
            _enabled = True
            _status, _status_reason = "ACTIVE", ""
            logger.info("OTel tracing 已启用: service=%s endpoint=%s",
                        service_name, otel_endpoint or "injected-exporter")
        except Exception as e:  # pragma: no cover - 初始化异常兜底，绝不外抛；真因进 status（R5）
            logger.warning("OTel tracing 初始化失败（%s），降级为 no-op，status=DEGRADED", e)
            _initialized = True
            _enabled = False
            _status, _status_reason = "DEGRADED", f"init_failed: {e}"
            _tracer = _make_noop_tracer()
            _provider = None
        return _tracer


def get_tracer() -> Any:
    """返回当前 tracer；未初始化 / 未启用时返回 no-op tracer，绝不抛异常。"""
    with _state_lock:
        if _tracer is not None:
            return _tracer
    return _make_noop_tracer()


def force_flush() -> None:
    """关闭/退出前 flush 全部 span（无 provider 或未启用时 no-op，绝不抛异常）。

    BatchSpanProcessor 默认 ~5s 周期导出，短生命周期进程/验证脚本需显式 flush。
    """
    with _state_lock:
        provider = _provider
    if provider is None:
        return
    try:
        if hasattr(provider, "force_flush"):
            provider.force_flush()
    except Exception:  # pragma: no cover - 防御：flush 失败不影响退出流程
        logger.warning("tracing force_flush failed", exc_info=True)


def shutdown_tracing() -> None:
    """统一 lifespan 退出入口：flush + shutdown provider。

    取代各 app 手写 force_flush（方案 §3.2）；BatchSpanProcessor 未 flush 会丢
    尾批 span，所有经 init_tracing（含门面）装配的应用都应在 lifespan 末尾调本函数。
    """
    with _state_lock:
        provider = _provider
    if provider is None:
        return
    try:
        if hasattr(provider, "force_flush"):
            provider.force_flush()
        provider.shutdown()
    except Exception:  # pragma: no cover - 防御：退出不影响主流程
        logger.warning("tracing shutdown failed", exc_info=True)


def current_span() -> Any:
    """当前上下文中的 span（TracingMiddleware 创建的请求级 server span）。

    未启用/无 SDK 返回 InvalidSpan（写属性静默无效、绝不抛异常）；业务层补属性
    的正规入口，取代 handler 内手写 span / app.state 取 tracer（方案 §3.2 L-2）。
    """
    if not _enabled or _otel_trace is None:
        return _INVALID_SPAN
    try:
        return _otel_trace.get_current_span()
    except Exception:  # pragma: no cover - 防御
        return _INVALID_SPAN


def record_request_attributes(attrs: Dict[str, Any]) -> None:
    """向当前请求 span 补业务属性（thread_id/priority/脱敏 question 等）。

    放在 handler 早段即可覆盖 cache_hit/429/409/断连全部旁路路径（R10）；
    未启用时静默 no-op（opt-in 铁律零开销）。
    """
    if not _enabled or not attrs:
        return
    try:
        span = current_span()
        if span is not None and span.is_recording():
            span.set_attributes(attrs)
    except Exception:  # pragma: no cover - 防御：观测不得影响业务主流程
        logger.debug("record_request_attributes failed", exc_info=True)


@contextmanager
def start_span(name: str, attrs: Optional[Dict[str, Any]] = None) -> Iterator[Any]:
    """启动一个 span 的 context manager（``with start_span("retrieval.embedding") as span:``）。"""
    if not _enabled or _tracer is None:
        with _NoOpSpanContextManager() as span:
            yield span
        return
    merged = _merge_attrs(attrs)
    with _tracer.start_as_current_span(name, attributes=merged) as span:
        yield span


def traced_span(
    name: str,
    attributes: Optional[Dict[str, Any]] = None,
    attributes_fn: Optional[Callable[..., Dict[str, Any]]] = None,
) -> Callable:
    """装饰器：将函数调用包裹为一个 span。未启用时直接执行原函数，零开销、绝不抛异常。

    参数：
        name: span 名（如 ``"retrieval.embedding"``）
        attributes: 静态属性（创建 span 时写入）
        attributes_fn: 动态属性回调 ``fn(*args, result=result, **kwargs) -> dict``，
                       在函数**正常返回后**写入 span。
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if not _enabled or _tracer is None:
                return func(*args, **kwargs)
            merged = _merge_attrs(attributes)
            with _tracer.start_as_current_span(name, attributes=merged) as span:
                try:
                    result = func(*args, **kwargs)
                    if attributes_fn is not None:
                        try:
                            extra = attributes_fn(*args, result=result, **kwargs)
                            if extra:
                                span.set_attributes(extra)
                        except Exception as e:
                            logger.debug("tracing attributes_fn 执行失败: %s", e)
                    return result
                except Exception as e:
                    try:
                        span.record_exception(e)
                    except Exception:  # pragma: no cover - 防御
                        pass
                    raise

        return wrapper

    return decorator


def record_exception(exception: BaseException) -> None:
    """将异常记录到当前激活 span（若启用）；未启用时 no-op。"""
    if not _enabled or _otel_trace is None:
        return
    try:
        current_span = _otel_trace.get_current_span()
        if current_span is not None and current_span.is_recording():
            current_span.record_exception(exception)
    except Exception:  # pragma: no cover - 防御
        pass


def _reset_for_tests() -> None:
    """重置模块状态，供单元测试隔离使用（shutdown provider 并清空全部状态）。"""
    global _initialized, _enabled, _tracer, _provider, _status, _status_reason
    with _state_lock:
        if _provider is not None:
            try:
                _provider.shutdown()
            except Exception:  # pragma: no cover - 防御
                pass
            _provider = None
        _initialized = False
        _enabled = False
        _status = "UNINITIALIZED"
        _status_reason = ""
        _tracer = None
        _base_attrs.clear()
        _request_id_var.set("")
        _user_query_hash_var.set("")


__all__ = [
    "init_tracing",
    "get_tracer",
    "get_tracing_status",
    "start_span",
    "traced_span",
    "generate_request_id",
    "set_request_context",
    "get_request_id",
    "user_query_hash",
    "is_tracing_enabled",
    "is_initialized",
    "record_exception",
    "noop_tracer",
    "force_flush",
    "shutdown_tracing",
    "current_span",
    "record_request_attributes",
    "_reset_for_tests",
]
