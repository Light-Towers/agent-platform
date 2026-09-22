"""data_analysis/：数据分析 Agent skill（P1 骨架）。

链路：NL → Metric Registry 校验（INV-10）→ HTTP 调 nl2sql-service（端点 TODO）→ 返回结果。
nl2sql-service 通用化（wenda-data-agent 12 节点 LangGraph 抽通用服务）是后续步骤。
"""

from exhibition_agent.skills.data_analysis.skill import DataAnalysisQuerySkill

__all__ = ["DataAnalysisQuerySkill"]
