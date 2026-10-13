from agent_server.agent.router import RouteDecision, decide_route, heuristic_route


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


class _StructuredDouble:
    """镜像真实 ChatOpenAI 的结构化出口：schema 位置参 + method 等关键字参。

    写成 `with_structured_output(self, schema)` 就会和当年 `_FakeCheckpointer` 一样，
    把"参数被中间层吞掉"这个缺陷盖成绿灯（2026-10-13 126 现网即如此）。
    """

    def __init__(self, decision: RouteDecision | None = None, raises: Exception | None = None):
        self.decision = decision
        self.raises = raises
        self.seen_kwargs: dict | None = None
        self.seen_messages = None

    def with_structured_output(self, schema, **kwargs):
        self.seen_kwargs = kwargs
        return self

    async def ainvoke(self, messages):
        self.seen_messages = messages
        if self.raises is not None:
            raise self.raises
        return self.decision


async def test_decide_route_requests_function_calling_not_default_json_schema():
    """langchain-openai 的默认 method 是 json_schema，而提供方是否支持它**按模型**不同
    （现网 DeepSeek 稳定 400）⇒ 路由器必须显式要 function_calling，且 tool_choice 留默认 auto。"""
    double = _StructuredDouble(RouteDecision(capability="rag", sub_query="q", reason="模型写的理由"))
    decision = await decide_route(double, "为什么特装展台施工必须先报馆才能进场？")

    assert double.seen_kwargs == {"method": "function_calling"}
    assert decision.capability == "rag"


async def test_llm_decision_not_overridden_by_keyword_table():
    """无特征词的因果问法：词表会判 direct（检索压根不发生）。LLM 主判必须原样生效，
    否则 R1 修了 method 也白修。"""
    assert heuristic_route("为什么特装展台施工必须先报馆才能进场？").capability == "direct"

    double = _StructuredDouble(RouteDecision(capability="rag", sub_query="报馆流程", reason="属本地知识库内容"))
    decision = await decide_route(double, "为什么特装展台施工必须先报馆才能进场？")
    assert decision.capability == "rag"
    # 路由器文案保持不变（eval golden 基线依赖它）
    assert double.seen_messages[0]["role"] == "system"
    assert "rag=本地知识库" in double.seen_messages[0]["content"]


async def test_provider_rejection_still_falls_back_to_heuristic():
    double = _StructuredDouble(raises=RuntimeError("400 This response_format type is unavailable now"))
    decision = await decide_route(double, "什么是向量检索，解释一下")
    assert decision.capability == "rag"
    assert decision.reason == "命中知识库特征词"  # 回退仍走词表，且 reason 可据此判别走了哪条
