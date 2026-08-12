from app.agent.router import heuristic_route


def test_sql_priority_over_search_and_rag():
    assert heuristic_route("统计订单表里的销售额").capability == "sql"


def test_search_route():
    assert heuristic_route("最近 GitHub 有什么新项目").capability == "search"


def test_rag_route():
    assert heuristic_route("什么是向量检索，解释一下").capability == "rag"


def test_direct_route_default():
    assert heuristic_route("帮我写一首诗").capability == "direct"


def test_sql_beats_search_on_mixed():
    # 同时含 sql 与 search 特征词时，sql 优先
    assert heuristic_route("最新的订单统计").capability == "sql"
