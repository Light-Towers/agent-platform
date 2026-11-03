"""状态键跨 LangGraph 边界的接线用例（2026-10-27）。

**起因**：`examples`（recall_example 写、generate_sql 读）与 `filter_table_enabled`
（QueryService 注入、filter_table 读）都不在 `DataAgentState` 里声明。StateGraph 只保留
schema 声明过的键 ⇒ 这两处跨边界的值被**静默丢弃**：few-shot 范例召回跑完就蒸发（生成
prompt 恒渲染"（无历史范例）"），#109 的表过滤开关无论怎么配都是关。

本文件钉三层：

1. **机制前提**（正控）：未声明键确实被丢弃——没有这条，下面两条可能只是"恰好没坏"。
2. **真图回归**：值穿过 `build_graph()` 编译出的真图，被消费方读到（不是直调节点的替身）。
3. **常驻门禁**：任何跨图边界的写入（节点 return / QueryService 注入）都必须先在 schema
   声明；另有"有读无写"键的在册清单，清单与现实不符即红。

第 2 层的形状是刻意的：`tests/test_example_corpus.py` 直调节点函数、手递一个普通 dict，
所以它断言的 `top_k == 5` 在真图上根本不成立——替身没镜像真实协作者，这是本仓复发过多次
的失效形状（见 `docs/operations/testing-playbook.md`）。
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest
from nl2sql_service.agent.context import DataAgentContext
from nl2sql_service.agent.graph import build_graph
from nl2sql_service.agent.state import DataAgentState

_SERVICE_ROOT = Path(__file__).resolve().parents[2] / "applications" / "nl2sql-service" / "nl2sql_service"


# ---------------------------------------------------------------------------
# 替身：只 stub 到"真图会怎么喂它"这一层，不改图、不 patch schema
# ---------------------------------------------------------------------------
class _ScriptedLLM:
    enabled = True

    def __init__(self, replies: list[str]) -> None:
        self._replies = list(replies)
        self.prompts: list[str] = []

    async def invoke(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self._replies.pop(0) if self._replies else ""


class _Dw:
    def __init__(self) -> None:
        self.rows = [{"n": 1}]
        self.calls = 0

    async def execute_readonly(self, sql: str) -> list[dict]:
        self.calls += 1
        return self.rows


class _Embedder:
    async def embed_query(self, text: str) -> list[float]:
        return [0.1, 0.2]


class _ExampleRepo:
    def __init__(self, examples: list[dict[str, Any]]) -> None:
        self.examples = examples
        self.calls = 0

    async def recall(self, keywords, *, embedding, top_k, score_margin, filters):
        self.calls += 1
        return self.examples


class _ColumnRepo:
    """列召回桩：merge_retrieved_info 由列行的 table_name 派生 tables（P0-11③），
    filter_table 的候选输入就来自这里。"""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    async def recall(self, keywords, *, embedding, top_k, score_margin, filters):
        return self.rows


def _ctx(**kwargs: Any) -> DataAgentContext:
    class _Ctx(DataAgentContext):
        def __init__(self) -> None:
            super().__init__(**kwargs)

    return _Ctx()


# 一张候选表足够让 filter_table 有料可过滤；列行走真实派生路径，不走 metric_config 直调分支
# （那条分支的 tables 取自 metric_config["tables"]，与本用例无关）。
_COLUMNS = [{"table_name": "orders", "column_name": "amount", "column_comment": "订单金额"}]


# ---------------------------------------------------------------------------
# 1. 机制前提
# ---------------------------------------------------------------------------
async def test_undeclared_key_is_dropped_by_langgraph_positive_control():
    """正控：StateGraph 丢弃 schema 未声明的输入键与节点返回键，且不报错。

    这条不测产品代码，测的是**本文件其余判据的前提**。若哪天 LangGraph 改成保留未知键，
    这条先红，下面几条的"因为声明了才通过"就不会被误读成"本来就不会丢"。
    """
    from typing import TypedDict

    from langgraph.graph import END, START, StateGraph

    class _Schema(TypedDict, total=False):
        declared: str

    seen: dict[str, Any] = {}

    async def probe(state: dict[str, Any]) -> dict[str, Any]:
        seen.update(dict(state))
        return {"undeclared_write": "x"}

    g = StateGraph(_Schema)
    g.add_node("probe", probe)
    g.add_edge(START, "probe")
    g.add_edge("probe", END)
    out = await g.compile().ainvoke({"declared": "yes", "undeclared_input": "y"})

    assert "undeclared_input" not in seen, "未声明的输入键必须被丢弃（这正是 examples 失效的机制）"
    assert "undeclared_write" not in out, "未声明的节点返回键也必须被丢弃"
    assert out["declared"] == "yes"


# ---------------------------------------------------------------------------
# 2. 真图回归
# ---------------------------------------------------------------------------
_EXAMPLES = [{"question": "上季度总销售额", "sql": "SELECT SUM(amount) FROM sales"}]


async def test_examples_survive_the_real_graph_into_generate_prompt():
    """recall_example 产出的范例必须出现在 generate_sql 的 prompt 里（穿过真图，非直调）。"""
    llm = _ScriptedLLM(
        [
            '["销售额"]',  # extract_keywords
            "SELECT SUM(amount) FROM sales LIMIT 1",  # generate_sql
            "共 1 行。",  # answer
        ]
    )
    repo = _ExampleRepo(_EXAMPLES)
    graph = build_graph()

    result = await graph.ainvoke(
        {
            "query": "统计销售额",
            "context": _ctx(dw_repository=_Dw(), embedding_client=_Embedder(), example_repository=repo),
            "llm": llm,
            "sql_max_correct_retries": 3,
        }
    )

    assert repo.calls == 1, "范例召回应被调用一次"
    assert result["examples"] == _EXAMPLES, "节点产出的 examples 必须留在最终状态里（未声明即被丢弃）"
    generate_prompt = llm.prompts[1]
    assert "上季度总销售额" in generate_prompt and "SELECT SUM(amount) FROM sales" in generate_prompt, (
        "few-shot 必须进生成 prompt；出现下面的占位文本说明范例在图边界上被丢了"
    )
    assert "（无历史范例）" not in generate_prompt


async def test_filter_table_switch_injected_by_service_reaches_the_node():
    """QueryService 注入的 filter_table_enabled 必须穿过真图被节点读到（#109）。

    开=true 时节点产生表过滤 LLM 调用，开=false 时一条也不多调一次——两个方向都钉，
    否则"恒关"与"恒开"都能过。
    """
    filter_prompt_marker = "从候选表中选择回答问题所需的表"

    async def _run(enabled: bool) -> _ScriptedLLM:
        llm = _ScriptedLLM(
            [
                '["订单"]',  # extract_keywords
                '["orders"]',  # filter_table（仅 enabled=True 时发生）
                "SELECT amount FROM orders LIMIT 1",  # generate_sql
                "共 1 行。",  # answer
            ]
        )
        await build_graph().ainvoke(
            {
                "query": "订单金额",
                "context": _ctx(
                    dw_repository=_Dw(),
                    embedding_client=_Embedder(),
                    column_repository=_ColumnRepo(_COLUMNS),
                ),
                "llm": llm,
                "sql_max_correct_retries": 3,
                "filter_table_enabled": enabled,
            }
        )
        return llm

    on = await _run(True)
    assert any(filter_prompt_marker in p for p in on.prompts), (
        "filter_table_enabled=True 必须让节点发起表过滤调用：值没穿过图边界，开关就是死的"
    )

    off = await _run(False)
    assert not any(filter_prompt_marker in p for p in off.prompts), "开关关时必须不产生过滤调用"


# ---------------------------------------------------------------------------
# 3. 常驻门禁
# ---------------------------------------------------------------------------
def _declared_keys() -> set[str]:
    tree = ast.parse((_SERVICE_ROOT / "agent" / "state.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "DataAgentState":
            return {
                stmt.target.id
                for stmt in node.body
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)
            }
    pytest.fail("state.py 里找不到 DataAgentState")


def _registered_node_fns() -> set[str]:
    """图里真正注册的节点函数名：只有它们的 return 才算跨边界写入（别拿路由函数误判）。"""
    tree = ast.parse((_SERVICE_ROOT / "agent" / "graph.py").read_text(encoding="utf-8"))
    names = set()
    for call in ast.walk(tree):
        if (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr == "add_node"
            and len(call.args) >= 2
            and isinstance(call.args[1], ast.Name)
        ):
            names.add(call.args[1].id)
    assert names, "graph.py 没有解析到任何 add_node —— 门禁自己空转了"
    return names


def _dict_keys(node: ast.Dict) -> set[str]:
    return {k.value for k in node.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}


def _boundary_writes() -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """(节点 return 键, QueryService 图输入键)，各带出处。"""
    node_fns = _registered_node_fns()
    returns: dict[str, list[str]] = {}
    reads: dict[str, list[str]] = {}
    for py in sorted((_SERVICE_ROOT / "agent" / "nodes").glob("*.py")):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        # 写侧只看真节点函数：路由函数返回的是边名，不是状态更新
        for fn in (n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef | ast.FunctionDef) and n.name in node_fns):
            for ret in ast.walk(fn):
                if isinstance(ret, ast.Return) and isinstance(ret.value, ast.Dict):
                    for key in _dict_keys(ret.value):
                        returns.setdefault(key, []).append(f"{py.name}:{ret.lineno}")
        # 读侧按整模块扫：节点把 state 传给模块内 helper 是常态（finalize 的 trace
        # 构形状就是这样），只扫节点函数体会漏掉 helper 里的死读。
        for sub in ast.walk(tree):
            if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute) and sub.func.attr == "get":
                if isinstance(sub.func.value, ast.Name) and sub.func.value.id == "state" and sub.args:
                    if isinstance(sub.args[0], ast.Constant) and isinstance(sub.args[0].value, str):
                        reads.setdefault(sub.args[0].value, []).append(f"{py.name}:{sub.lineno}")
            if isinstance(sub, ast.Subscript) and isinstance(sub.value, ast.Name) and sub.value.id == "state":
                if isinstance(sub.slice, ast.Constant) and isinstance(sub.slice.value, str):
                    reads.setdefault(sub.slice.value, []).append(f"{py.name}:{sub.lineno}")

    inputs: dict[str, list[str]] = {}
    tree = ast.parse((_SERVICE_ROOT / "services" / "query_service.py").read_text(encoding="utf-8"))
    for stmt in ast.walk(tree):
        if not isinstance(stmt, ast.AnnAssign | ast.Assign):
            continue
        targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
        if any(getattr(t, "id", None) == "state" for t in targets) and isinstance(stmt.value, ast.Dict):
            for key in _dict_keys(stmt.value):
                inputs.setdefault(key, []).append(f"query_service.py:{stmt.lineno}")
    assert inputs, "query_service 没解析到图输入 dict —— 门禁自己空转了"
    return (returns, inputs), reads


def test_every_key_crossing_the_graph_boundary_is_declared():
    """写侧门禁：节点 return 的键与 QueryService 注入的键都必须声明。

    未声明 = 值在图边界上消失，且没有任何报错。这是 examples / filter_table_enabled
    两个缺陷的通用形式，把它的判据常驻下来。
    """
    (returns, inputs), _ = _boundary_writes()
    declared = _declared_keys()
    missing = sorted({k for k in set(returns) | set(inputs) if k not in declared})
    assert not missing, f"跨图边界写入但未在 DataAgentState 声明的键：{missing}（会被 LangGraph 静默丢弃）"


# "读得到、但全仓没有任何写入点"的键：节点用带默认值的 state.get() 读它们，
# 所以现在行为是"恒取默认"，不是崩溃。**这不是豁免通道**——下面那条用例同时钉住
# "它们仍然没有写入点"：谁补了写入点却不声明，那条立刻红。
_READ_ONLY_NO_WRITER = {"example_top_k", "example_score_margin", "path"}


def test_undeclared_reads_are_exactly_the_documented_no_writer_set():
    _, reads = _boundary_writes()
    declared = _declared_keys()
    undeclared_reads = {k for k in reads if k not in declared}
    assert undeclared_reads == _READ_ONLY_NO_WRITER, (
        f"读侧未声明键与在册清单不符（读={sorted(undeclared_reads)} 册={sorted(_READ_ONLY_NO_WRITER)}）；"
        "新键要么补进 DataAgentState，要么按本文件第 2 层的判据先取真图读数"
    )
    # 在册清单的有效性自检：这些键确实没有任何写入点
    (returns, inputs), _ = _boundary_writes()
    still_nowhere_written = _READ_ONLY_NO_WRITER - set(returns) - set(inputs)
    assert still_nowhere_written == _READ_ONLY_NO_WRITER, (
        f"{sorted(_READ_ONLY_NO_WRITER - still_nowhere_written)} 现在有写入点了却没声明 —— 静默丢弃正在发生"
    )


def test_schema_docstring_states_the_drop_constraint():
    """schema 的 docstring 必须写明"未声明即丢弃"，否则下一个加键的人仍会照旧猜。"""
    assert "静默丢弃" in (DataAgentState.__doc__ or ""), "state.py 的类 docstring 应保留这条约束说明"
