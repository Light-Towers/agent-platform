"""5 节点图编排测试。"""


from dialogue_framework.agent.graph.builder import build_graph
from dialogue_framework.core.tracker import Tracker


def test_graph_builds():
    graph = build_graph()
    nodes = list(graph.get_graph().nodes.keys())
    assert "understand" in nodes
    assert "policy" in nodes
    assert "action" in nodes
    assert "guard" in nodes
    assert "response" in nodes


async def test_graph_invocation():
    graph = build_graph()
    state = {"tracker": Tracker(session_id="test"), "user_message": "你好"}
    result = await graph.ainvoke(state)
    assert "response" in result
    assert "intent" in result


async def test_graph_with_sql_guard_rejection():
    from dialogue_framework.agent.graph.nodes.guard import guard

    state = {"action_result": "DELETE FROM users", "action_type": "search"}
    result = await guard(state)
    assert result["guard_passed"] is False


async def test_graph_with_sensitive_filter():
    from dialogue_framework.agent.graph.nodes.guard import guard

    state = {"action_result": "your password is 123", "action_type": "answer"}
    result = await guard(state)
    assert result["guard_passed"] is True
    assert "已过滤" in result["action_result"]
