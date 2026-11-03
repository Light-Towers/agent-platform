"""非法 skill 必须 fail-closed（`skill_error` 跨图边界的回归 + 该图的边界门禁）。

**缺陷原状**：`select_skill` 在调用方显式传了一个不在册的 `params.skill` 时写下
`skill_error`，`run_skill` 读到它就返回 `UNKNOWN_SKILL` 并**不执行**任何 skill。
但 `skill_error` 从来没在 `ExhibitionAgentState` 里声明过 ⇒ LangGraph 只保留 schema
声明过的键，这一写一读在图边界上被静默丢弃 ⇒ 守卫恒不触发，非法 skill **静默回退成默认
venue skill 并真的打了 warehouse**：调用方拿到一份档期答案，`error` 是空的，
既不知道自己写错了名字、也不知道系统替他换了个问题。这比"少个功能"更糟——是行为被换掉。

判据按"有没有真的执行"来定，不看 answer 文案：用一个计数代理包住 mock warehouse，
非法 skill 那条必须**一个请求都不发**（否则就是回退执行），合法那条必须发。
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import httpx

from exhibition_agent.client.warehouse_client import WarehouseClient
from exhibition_agent.graph.supervisor import run_supervisor
from exhibition_agent.mock_server.warehouse_mock import create_mock_app
from exhibition_agent.observability.trace import InMemoryTraceRecorder
from exhibition_agent.testing_helpers import ctx, ctx_header

_GRAPH_PKG = Path(__file__).resolve().parents[1] / "exhibition_agent" / "graph"


class _CountingApp:
    """包住 mock warehouse 的 ASGI 应用，记录打到它的每个请求路径。"""

    def __init__(self, app: Any) -> None:
        self._app = app
        self.paths: list[str] = []

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope.get("type") == "http":
            self.paths.append(scope.get("path", ""))
        await self._app(scope, receive, send)


def _client() -> tuple[WarehouseClient, _CountingApp]:
    counter = _CountingApp(create_mock_app())
    client = WarehouseClient(base_url="http://mock-warehouse", transport=httpx.ASGITransport(app=counter), timeout=5.0)
    return client, counter


async def _run(skill: str | None) -> tuple[dict[str, Any], _CountingApp]:
    client, counter = _client()
    context = ctx()
    params: dict[str, Any] = {"exhibition_id": "ex-001"}
    if skill is not None:
        params["skill"] = skill
    state = await run_supervisor(
        {
            "query": "查询 SIAL 广州 2026 场馆档期",
            "params": params,
            "execution_context": context,
            "execution_context_header": ctx_header(context),
            "context_mode": "jwt",
            "warehouse_client": client,
            "trace_recorder": InMemoryTraceRecorder(),
            "sql_statements": [],
            "extra_headers": {"X-Mock-Scenario": "normal_200"},
        }
    )
    return state, counter


async def test_unknown_skill_fails_closed_without_executing_default() -> None:
    state, counter = await _run("no.such.skill")

    assert state.get("error") == "UNKNOWN_SKILL", f"非法 skill 必须落显式错误，实得 {state.get('error')!r}"
    assert state.get("skill_result") is None, "非法 skill 不许有执行结果"
    assert "未知 skill" in state["answer"], state["answer"]
    assert counter.paths == [], f"非法 skill 不许真的调用 warehouse（调了就是替用户换了问题）：{counter.paths}"


async def test_valid_skill_still_executes_and_hits_warehouse() -> None:
    """对照组：合法显式 skill 行为不变——否则上一条可能只是"整条链路都没跑"。"""
    state, counter = await _run("venue.schedule.query")

    assert not state.get("error"), state.get("error")
    assert state.get("skill_result") is not None
    assert counter.paths, "合法 skill 必须真的打到 warehouse（证明计数代理有效）"


# ── 该图的边界门禁（形状同 tests/nl2sql_service/test_state_schema_wiring.py）──────────
def _declared() -> set[str]:
    tree = ast.parse((_GRAPH_PKG / "state.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "ExhibitionAgentState":
            names = set()
            for stmt in node.body:
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    names.add(stmt.target.id)
            return names
    raise AssertionError("state.py 里找不到 ExhibitionAgentState")


def _boundary_keys() -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """(节点 return 键, state 读取键)：节点名单从 graph.py 的 add_node 派生，不手写。"""
    gtree = ast.parse((_GRAPH_PKG / "supervisor.py").read_text(encoding="utf-8"))
    node_fns = {
        c.args[1].id
        for c in ast.walk(gtree)
        if isinstance(c, ast.Call)
        and isinstance(c.func, ast.Attribute)
        and c.func.attr == "add_node"
        and len(c.args) >= 2
        and isinstance(c.args[1], ast.Name)
    }
    assert node_fns, "supervisor.py 没解析到任何 add_node —— 门禁自己空转了"

    returns: dict[str, list[str]] = {}
    reads: dict[str, list[str]] = {}
    for py in sorted(_GRAPH_PKG.glob("*.py")):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for fn in (n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef | ast.FunctionDef) and n.name in node_fns):
            for sub in ast.walk(fn):
                if isinstance(sub, ast.Return) and isinstance(sub.value, ast.Dict):
                    for k in sub.value.keys:
                        if isinstance(k, ast.Constant) and isinstance(k.value, str):
                            returns.setdefault(k.value, []).append(f"{py.name}:{sub.lineno}")
                if (
                    isinstance(sub, ast.Call)
                    and isinstance(sub.func, ast.Attribute)
                    and sub.func.attr == "get"
                    and isinstance(sub.func.value, ast.Name)
                    and sub.func.value.id == "state"
                    and sub.args
                    and isinstance(sub.args[0], ast.Constant)
                    and isinstance(sub.args[0].value, str)
                ):
                    reads.setdefault(sub.args[0].value, []).append(f"{py.name}:{sub.lineno}")
    return returns, reads


def test_every_state_key_used_by_the_supervisor_graph_is_declared() -> None:
    declared = _declared()
    returns, reads = _boundary_keys()
    assert returns and reads, "解析结果为空，门禁在空转"
    undeclared_writes = sorted({k for k in returns if k not in declared})
    undeclared_reads = sorted({k for k in reads if k not in declared})
    assert not undeclared_writes, f"节点写了但 schema 没声明的键（会被静默丢弃）：{undeclared_writes}"
    assert not undeclared_reads, f"节点读了但 schema 没声明的键（恒读缺省值）：{undeclared_reads}"


def test_state_docstring_records_the_boundary_constraint() -> None:
    src = (_GRAPH_PKG / "state.py").read_text(encoding="utf-8")
    assert "静默丢弃" in src, "state.py 必须把『未声明即被静默丢弃』这条约束写在现场"
