"""基础设施层（已退役，Plan-F Phase 0 完成）。

2026-08-19 起，app/infra 全部运行时模块（admission / cache / circuit_breaker /
coordinator / revert / mcp_client / otel / tracing / db）已迁入共享包
`agent-runtime/`（agent_runtime.*），此处仅保留包占位，避免历史 import 路径
（如 `import app.infra`）产生 ImportError。新代码一律从 `agent_runtime.*` 引用。
"""
