"""OpenTelemetry 分布式追踪集成 —— **薄门面**（委托 agent_core.tracing 唯一状态机）。

S1 收敛（docs/plans/plan-observability-global-remediation-2026-09-29.md §3.1）：
- 本模块**不再自持** ``_tracer`` / ``_OTEL_AVAILABLE`` 全局态——历史"双状态机"
  （kernel ``_enabled`` vs 本模块 ``_tracer``）导致 tracing_propagation 的
  traceparent 透传门读错状态机、agent_server 链路静默断裂（复盘 R6），已销毁。
- ``init_otel`` 仅做**参数映射 + 委托** ``agent_core.tracing.init_tracing``；
  开关/降级/三态状态（DISABLED/DEGRADED/ACTIVE）全部由 kernel 唯一持有。
- 与 Langfuse 共存（kernel 复用全局 TracerProvider 路径），不替代。

DEPRECATED 路径：新代码请直接引用 ``agent_core.tracing``；当 lint L-2 白名单
（app.state.tracer 散点取用）清零后，本门面随之退役删除。
"""

import logging
from typing import Literal

from agent_core.tracing import force_flush as _kernel_force_flush
from agent_core.tracing import get_tracer, get_tracing_status, init_tracing
from agent_core.tracing import user_query_hash as _user_query_hash

logger = logging.getLogger(__name__)


def init_otel(
    exporter: Literal["otlp", "jaeger", "console", "none"] = "otlp",
    endpoint: str = "",
    sampling_rate: float = 1.0,
    service_name: str = "agent-platform",
) -> None:
    """初始化 OTel tracer（参数映射后委托 kernel 唯一状态机，幂等）。

    签名保持历史调用方（agent_server/main.py）兼容；状态与降级语义全部由
    ``agent_core.tracing.init_tracing`` 决定：
      - exporter="none"        → 显式关闭（kernel status=DISABLED）
      - exporter="console"     → 注入 ConsoleSpanExporter（kernel 统一挂载）
      - exporter="otlp"/"jaeger" → OTLP 端点导出（jaeger thrift exporter 已归档，
        自动映射 OTLP，endpoint 指向 Jaeger OTLP 接收端即可，无需安装停更包）
      - 启用但 SDK/exporter 缺失或端点为空 → kernel 记 DEGRADED+真因（R5：
        运维可区分"显式关"与"启用但坏了"），本模块不再吞成因。
    """
    if exporter == "none":
        init_tracing(service_name=service_name, enabled=False)
        return

    if exporter == "console":
        exporter_obj = None
        try:
            from opentelemetry.sdk.trace.export import ConsoleSpanExporter

            exporter_obj = ConsoleSpanExporter()
        except ImportError:
            logger.warning(
                "OTEL_INIT_FAILED: opentelemetry SDK 未安装，console exporter 无法构造"
                "（kernel 将记 DEGRADED）"
            )
        init_tracing(
            service_name=service_name,
            enabled=True,
            exporter=exporter_obj,
            sampling_rate=sampling_rate,
        )
        return

    if exporter == "jaeger":
        # 弃用：opentelemetry-exporter-jaeger 在 OTel SDK 1.x 后已归档（thrift 协议停更）。
        # 不再导入归档的 JaegerExporter，自动映射为 OTLP（Jaeger 现推荐 OTLP 接收端），
        # 旧配置 exporter="jaeger" 仍可工作（endpoint 指向 Jaeger OTLP 端口即可）。
        logger.warning(
            "OTEL_EXPORTER=jaeger 已弃用（JaegerExporter 归档），已自动映射为 OTLP；"
            "建议显式配置 exporter='otlp'"
        )

    # otlp / jaeger→otlp：endpoint 为空时传 None 让 kernel 回退标准 env
    # （OTEL_EXPORTER_OTLP_ENDPOINT）；仍为空则 kernel 记 DEGRADED=no_export_endpoint。
    init_tracing(
        service_name=service_name,
        otel_endpoint=endpoint or None,
        enabled=True,
        sampling_rate=sampling_rate,
    )


def get_otel_tracer():
    """返回 kernel 当前 tracer（未初始化/未启用时 no-op；本模块不持状态）。"""
    return get_tracer()


def get_otel_status() -> dict:
    """观测三态（供装配点/health 查询初始化**结果**而非配置意图，R11）。

    返回 {"status": UNINITIALIZED|DISABLED|DEGRADED|ACTIVE, "reason": str}。
    """
    return get_tracing_status()


def parse_traceparent(header: str | None):
    """解析 W3C traceparent header，返回 OTel Context 或 None。

    修复（复盘 R18，门面化时发现）：旧实现 import 了不存在的类名
    ``TraceContextFormat``（真名 ``TraceContextTextMapPropagator``），ImportError
    被 ``except Exception`` 吞掉 → 该函数从诞生起从未成功解析过任何 header。
    生产零调用点（仅历史 API 兼容保留）；跨服务传播请用
    ``agent_core.tracing_propagation.extract_traceparent``（读 kernel 唯一状态机）。
    """
    if not header:
        return None
    try:
        from opentelemetry.trace.propagation.tracecontext import (
            TraceContextTextMapPropagator,
        )

        return TraceContextTextMapPropagator().extract({"traceparent": header})
    except Exception:
        return None


def redact_question(question: str) -> dict:
    """脱敏：返回问题长度 + 哈希摘要，不含全文。复用 agent_core.tracing.user_query_hash。"""
    return {
        "question_length": len(question),
        "question_hash": _user_query_hash(question),
    }


def force_flush() -> None:
    """关闭前 flush 所有 span（委托 kernel；无 provider 时 no-op）。"""
    _kernel_force_flush()
