"""AgentState（Pydantic）契约测试：默认值 + LangGraph add_messages reducer 累加。

验证优化 A：AgentState 从 TypedDict 迁移为 Pydantic BaseModel 后，
LangGraph 能识别字段上的 Annotated[list, add_messages] reducer 并正确累加。
"""

from agent_server.agent.state import AgentState
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, START, StateGraph


def test_state_is_pydantic_with_defaults():
    s = AgentState()
    assert isinstance(s, AgentState)
    # 所有原 total=False 字段迁移为带默认值的 Pydantic 字段
    assert s.messages == []
    assert s.question == ""
    assert s.route == "direct"
    assert s.iterations == 0
    assert s.mcp_params == {}


async def test_add_messages_reducer_accumulates_in_graph():
    """真实 StateGraph 以 AgentState 为 schema，验证 messages 经 reducer 累加。"""

    async def inject(state: AgentState) -> dict:
        # 返回一个 AIMessage，应被 add_messages reducer 追加到已有 messages
        return {"messages": [AIMessage(content="reply")]}

    def done(state: AgentState) -> str:
        return END

    builder = StateGraph(AgentState)
    builder.add_node("inject", inject)
    builder.add_edge(START, "inject")
    builder.add_conditional_edges("inject", done, {END: END})
    graph = builder.compile()

    initial = {"messages": [HumanMessage(content="hi")], "question": "q"}
    result = await graph.ainvoke(initial)

    # 输入 1 条 + 节点返回 1 条 = reducer 累加为 2 条
    assert len(result["messages"]) == 2
    assert isinstance(result["messages"][0], HumanMessage)
    assert isinstance(result["messages"][1], AIMessage)
    # 非 reducer 字段透传
    assert result["question"] == "q"


def test_route_enum_rejects_invalid_value():
    """优化 A 要点2：route 已枚举化，写入非法分支键应由 Pydantic 校验拦截。"""
    import pytest

    with pytest.raises(Exception):  # ValidationError（pydantic v2）
        AgentState(route="serach")  # 拼写错误，非合法分支键


def test_validate_state_rejects_empty_question():
    """优化 A 要点2：_validate_state 入口断言拦截空 question。"""
    import pytest
    from agent_server.agent.state import _validate_state

    with pytest.raises(ValueError):
        _validate_state(AgentState(question=""))


def test_validate_state_accepts_valid_state():
    """优化 A 要点2：合法 state 通过 _validate_state。"""
    from agent_server.agent.state import _validate_state

    _validate_state(AgentState(question="q", route="direct"))  # 不抛异常

