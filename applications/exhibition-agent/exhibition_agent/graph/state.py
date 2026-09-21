"""Supervisor 状态（LangGraph TypedDict）。

sql_statements 字段是 INV-10 回归测试的断言锚点：
L3 text2sql 路径会 append SQL；MetricPendingError 路径不 append，测试断言为空。
"""

from __future__ import annotations

from typing import Any, TypedDict

from exhibition_agent.client.warehouse_client import WarehouseClient
from exhibition_agent.contract.execution_context import ExecutionContext
from exhibition_agent.observability.metrics import MetricsRegistry
from exhibition_agent.observability.trace import TraceRecorder


class ExhibitionAgentState(TypedDict, total=False):
    """Supervisor 图状态。"""

    query: str
    params: dict[str, Any]
    execution_context: ExecutionContext
    execution_context_header: str
    context_mode: str
    warehouse_client: WarehouseClient
    trace_recorder: TraceRecorder
    metrics_registry: MetricsRegistry
    extra_headers: dict[str, str]

    skill_name: str
    skill_result: Any
    answer: str
    error: str | None

    sql_statements: list[str]
    trace: Any
    latency_start_ms: float
