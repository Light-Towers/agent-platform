"""build_graph：异步 StateGraph 构建，5 节点对话循环。

编排：understand → policy → action → guard →(条件)→ response →(条件)→ END/understand
对齐生产栈 LangGraph 语义（与 app/agent/graph.py 风格一致）。
"""


from langgraph.graph import END, START, StateGraph

from dialogue_framework.agent.graph.edges import route_after_guard, route_after_response
from dialogue_framework.agent.graph.nodes.action import action
from dialogue_framework.agent.graph.nodes.guard import guard
from dialogue_framework.agent.graph.nodes.policy import policy
from dialogue_framework.agent.graph.nodes.response import response
from dialogue_framework.agent.graph.nodes.understand import understand
from dialogue_framework.agent.graph.state import DialogueState


def build_graph():
    """构建并编译 5 节点对话图。"""
    graph = StateGraph(DialogueState)

    graph.add_node("understand", understand)
    graph.add_node("policy", policy)
    graph.add_node("action", action)
    graph.add_node("guard", guard)
    graph.add_node("response", response)

    graph.add_edge(START, "understand")
    graph.add_edge("understand", "policy")
    graph.add_edge("policy", "action")
    graph.add_edge("action", "guard")
    graph.add_conditional_edges("guard", route_after_guard, {"policy": "policy", "response": "response"})
    graph.add_conditional_edges(
        "response", route_after_response, {"understand": "understand", END: END}
    )

    return graph.compile()
