"""联邦侧 Planner 实现（Plan-F Phase 2）。

``AgenticPlanner``：把 deep_agent 执行适配为统一 Planner 协议（plan -> Plan + execute -> StreamEvent），
供 ``PLANNER=agentic`` 时由 app 侧统一消费。run_deep_agent 的 guard/intent/cache/memory/monitor
副作用链路保持不动，本包只做协议适配。
"""

from agent_federation.planners.agentic import AgenticPlanner

__all__ = ["AgenticPlanner"]
