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
# ---------------------------------------------------------------------------
_initialized: bool = False
_enabled: bool = False
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
    from opentelemetry.sdk.trace import TracerProvider as _SDKTracerProvider
    from opentelemetry.sdk.resources import Resource as _Resource
    from opentelemetry.sdk.trace.export import BatchSpanProcessor as _BatchSpanProcessor
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor as _SimpleSpanProcessor

    _SDK_AVAILABLE = True
except Exception:  # pragma: no cover - 依赖缺失路径（CI / 本地无 OTel）
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
        except Exception:  # pragma: no cover - exporter 未安装路径
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
    """no-op 上下文管理器，保证 ``with start_span(...)`` 可用且不抛异常。"""

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
    """是否处于真实导出模式（SDK 可用 + 总开关开启 + 端点/注入 exporter 就绪）。"""
    return bool(_enabled)


def is_initialized() -> bool:
    """init_tracing 是否已被调用过（无论启用与否）。"""
    return bool(_initialized)


def init_tracing(
    service_name: Optional[str] = None,
    otel_endpoint: Optional[str] = None,
    enabled: Optional[bool] = None,
    *,
    exporter: Any = None,
    config_hash: Optional[str] = None,
    collection: Optional[str] = None,
) -> Any:
    """幂等初始化 OTel 追踪。

    参数：
        service_name: 服务名（默认读 ``AGENT_CORE_SERVICE_NAME``，再默认 ``agent-core``）
        otel_endpoint: OTLP 导出端点（默认读 ``OTEL_EXPORTER_OTLP_ENDPOINT``，空 → no-op）
        enabled: 总开关（默认读 ``AGENT_CORE_TRACE_ENABLED``，默认 False）
        exporter: 显式 span exporter（单测注入 ``InMemorySpanExporter`` 用；生产不传）
        config_hash / collection: 统一 span 属性，由宿主应用**注入**；
            不传则按中性环境变量回退（绝不读取宿主配置路径）。

    返回：tracer（可能为 no-op tracer，绝不抛异常）。
    """
    global _initialized, _enabled, _tracer, _provider

    service_name = service_name or os.getenv(ENV_SERVICE_NAME, DEFAULT_SERVICE_NAME)
    otel_endpoint = otel_endpoint if otel_endpoint is not None else os.getenv(ENV_OTEL_ENDPOINT, "")
    if enabled is None:
        enabled = _as_bool(os.getenv(ENV_TRACE_ENABLED), False)

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
                logger.warning(
                    "OTel SDK 未安装（可选 extra tracing：uv sync --extra tracing），tracing 降级为 no-op"
                )
            elif enabled and not can_export:
                logger.info("OTel 未配置导出端点（OTEL_EXPORTER_OTLP_ENDPOINT 为空），tracing 降级为 no-op")
            return _tracer

        try:
            provider = _SDKTracerProvider(
                resource=_Resource.create({"service.name": service_name})
            )
            if exporter is not None:
                provider.add_span_processor(_SimpleSpanProcessor(exporter))
            else:
                if _OTLP_EXPORTER_CLS is None:
                    logger.warning(
                        "OTLP exporter 未安装（opentelemetry-exporter-otlp-proto-grpc/http），tracing 降级为 no-op"
                    )
                    _initialized = True
                    _enabled = False
                    _tracer = _make_noop_tracer()
                    _provider = None
                    return _tracer
            # 复用已存在的全局 TracerProvider（如 Langfuse SDK 已先设置），
            # 避免 "Overriding of current TracerProvider is not allowed"。
            # 复用后框架层 span 与 SDK observation 共享同一 trace 树（不重复挂载本地 exporter）。
            existing = _otel_trace.get_tracer_provider()
            if not isinstance(existing, _otel_trace.ProxyTracerProvider):
                provider = existing
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
            logger.info("OTel tracing 已启用: service=%s endpoint=%s", service_name, otel_endpoint or "in-memory")
        except Exception as e:  # pragma: no cover - 初始化异常兜底，绝不外抛
            logger.warning("OTel tracing 初始化失败（%s），降级为 no-op", e)
            _initialized = True
            _enabled = False
            _tracer = _make_noop_tracer()
            _provider = None
        return _tracer


def get_tracer() -> Any:
    """返回当前 tracer；未初始化 / 未启用时返回 no-op tracer，绝不抛异常。"""
    with _state_lock:
        if _tracer is not None:
            return _tracer
    return _make_noop_tracer()


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
                        except Exception as e:  # noqa: BLE001 —— 埋点失败不影响业务
                            logger.debug("tracing attributes_fn 执行失败: %s", e)
                    return result
                except Exception as e:  # noqa: BLE001 —— 记录异常后继续抛出
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
    global _initialized, _enabled, _tracer, _provider
    with _state_lock:
        if _provider is not None:
            try:
                _provider.shutdown()
            except Exception:  # pragma: no cover - 防御
                pass
            _provider = None
        _initialized = False
        _enabled = False
        _tracer = None
        _base_attrs.clear()
        _request_id_var.set("")
        _user_query_hash_var.set("")


__all__ = [
    "init_tracing",
    "get_tracer",
    "start_span",
    "traced_span",
    "generate_request_id",
    "set_request_context",
    "get_request_id",
    "user_query_hash",
    "is_tracing_enabled",
    "is_initialized",
    "record_exception",
    "_reset_for_tests",
]
