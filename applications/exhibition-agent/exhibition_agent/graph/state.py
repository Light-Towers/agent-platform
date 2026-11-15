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
    # select_skill 检出"显式传了但不在册的 skill"时写下，run_skill 据此 fail-closed。
    # 必须在这里声明：LangGraph 只保留 schema 声明过的键，未声明的跨边界写入被静默丢弃
    # ——此前正是因此丢了，非法 skill 会静默回退成默认 venue skill 并真的执行。
    skill_error: str
    answer: str
    error: str | None

    sql_statements: list[str]
    trace: Any
    latency_start_ms: float
