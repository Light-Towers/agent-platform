"""Agent 运行时中间件层（Plan-F）。

定位：双轨共享的运行时基础设施——admission / coordinator / session / checkpoint /
tracing / cache / rate_limit / circuit_breaker / mcp。这些不是"外壳"，是
runtime middleware：横向关注点（重试/超时/熔断/限流/可观测）归此层统一管理，
Planner 只做决策不持有执行语义（契约点 P1）。

演进来源：app/infra/*（2026-08-19 起逐模块迁入，Phase 0 已完成 admission /
cache / circuit_breaker / coordinator / revert / mcp_client / otel / tracing / db
全部 9 个运行时模块，app/infra 已退役）。Phase 1 新增 capabilities/ 注册表：
Function/Agent/Remote 三执行器 + SkillRegistry，能力注册/发现/执行中立化。
"""

from agent_runtime.schemas import (
    AdmissionDecision,
    CoordinationDecision,
    McpServerConfig,
    McpToolResult,
    RevertResult,
)

__all__ = [
    "AdmissionDecision",
    "CoordinationDecision",
    "McpServerConfig",
    "McpToolResult",
    "RevertResult",
]
