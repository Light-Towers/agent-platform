"""Supervisor 图状态定义。"""

from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages


class AgentState(TypedDict, total=False):
    messages: Annotated[list, add_messages]  # 对话历史（checkpoint 持久化）
    question: str
    user_id: str
    route: str  # search | rag | sql | direct | mcp
    sub_query: str
    route_reason: str
    memory_notes: list[str]
    evidence: list[str]
    answer: str
    iterations: int
    mcp_server: str
    mcp_tool: str
    mcp_params: dict
