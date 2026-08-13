"""12 节点图编排测试。"""


from wenda_data_agent.agent.graph import build_graph


def test_graph_builds():
    graph = build_graph()
    nodes = list(graph.get_graph().nodes.keys())
    expected = [
        "extract_keywords",
        "recall_column",
        "recall_metric",
        "recall_value",
        "merge_retrieved_info",
        "filter_table",
        "filter_metric",
        "add_extra_context",
        "generate_sql",
        "validate_sql",
        "execute_sql",
        "correct_sql",
    ]
    for node in expected:
        assert node in nodes, f"missing node: {node}"


async def test_graph_invocation_no_llm():
    graph = build_graph()
    state = {"query": "统计上个月销售额"}
    result = await graph.ainvoke(state)
    assert "sql" in result
    assert "error" in result
