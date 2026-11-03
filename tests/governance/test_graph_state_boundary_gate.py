"""图边界门禁自身的治理用例（正反例 + 枚举自检 + 装配检查）。

范式与本目录其他门禁用例一致：对每条判定出**正例**（真违规必须报红）与**反例**
（合规不许误报），并对"被检对象是否真的被派生到"出自检——否则一条只会报绿的扫描器
比没有更危险（本仓的静默丢键缺陷正是被"全绿"盖住的）。
"""

from __future__ import annotations

import ast
import importlib.util
import re
from contextlib import contextmanager
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "lint_graph_state_boundary.py"


def _load():
    spec = importlib.util.spec_from_file_location("lint_graph_state_boundary", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GATE = _load()


def test_repo_is_clean_and_enumeration_is_not_vacuous() -> None:
    """反例面：全仓当前 0 违规；同时证明被检面不是空的（扫描器真有活干）。"""
    violations, blind, stats = GATE.check()
    assert violations == [], "图边界门禁报红：\n" + "\n".join(violations)
    assert stats["ledger_checked"] == 1, "全仓口径却没做台账对码——三条登记成了死字"
    assert stats["hosts"] >= 9, f"StateGraph 宿主只派生出 {stats['hosts']} 张，明显低于实际 9 张"
    assert stats["sites"] >= 60, f"注册点派生数 {stats['sites']} 明显偏低"
    assert stats["resolved"] == stats["sites"] - stats["lambdas"], (
        f"解析 {stats['resolved']} ≠ 注册点 {stats['sites']} - 虚拟 lambda {stats['lambdas']}：有站点静默漏掉"
    )
    # 派生面下限（实际是 query_app / kb_import_app 两处；将来别的 app 改成
    # `app = graph.compile()` 赋值形状时会增多，故只设下限不设上限）
    assert stats["input_sites"] >= 2, f"图入参面只剩 {stats['input_sites']} 处——入参判据可能失效"
    assert set(blind) == set(GATE.BLIND_SPOTS), "盲区登记与实况不符"
    # 覆盖率必须说人话：宿主总数与被派生出实参键的张数分开，"9 张全过判据"是假话
    assert stats["unjudged_hosts"] == len(GATE.UNJUDGED_INPUT_HOSTS), (
        f"入参面判不到的图 {stats['unjudged_hosts']} 张 ≠ 登记 {len(GATE.UNJUDGED_INPUT_HOSTS)} 项"
    )
    judged = stats["hosts"] - stats["unjudged_hosts"]
    assert judged >= 5, f"入参判据实际只覆盖 {judged}/{stats['hosts']} 张图，低于本轮基线 5 张"
    # 三条台账非空 = 上面那两句"删掉采集就会红"的前提；台账被清空则整套对码退化为永绿
    assert GATE.BLIND_SPOTS and GATE.UNDECLARED_READS and GATE.UNJUDGED_INPUT_HOSTS, "有台账被清空，对码已空转"
    assert all(v.strip() for v in GATE.UNJUDGED_INPUT_HOSTS.values()), "未判登记缺原因，等于没有可复审的口径"


def test_undeclared_state_read_is_collected() -> None:
    """正例（派生面）：节点读一个 schema 里没有的键，必须进"有读无写"实况集。

    这条判据在全仓口径下只通过对码报红，所以这里单测派生本身；删掉采集行时
    `test_repo_is_clean...` 也会红（登记非空 ⇒ 对称差必亮），两头都能抓。
    """
    src = """
from typing import TypedDict
from langgraph.graph import StateGraph

class S(TypedDict):
    a: str

def node_x(state):
    return {"a": state["ghost_read"]}

g = StateGraph(S)
g.add_node("node_x", node_x)
app = g.compile()
"""
    tree = ast.parse(src)
    assert "ghost_read" in GATE._state_reads(tree)


def test_registry_drift_message_can_fire() -> None:
    """台账对码自身的正例：注入一项未登记必须报红，且过期项单独说清（否则三条登记只是摆设）。"""
    fired = GATE._registry_drift("X", {"a.py::f", "b.py::g"}, {"a.py::f"}, new_word="未登记", stale_word="已过期")
    assert fired == ["X与登记不符：未登记 ['b.py::g']"], fired
    stale = GATE._registry_drift("X", set(), {"a.py::f"}, new_word="未登记", stale_word="已过期")
    assert stale == ["X与登记不符：已过期 ['a.py::f']"], stale
    assert GATE._registry_drift("X", {"a.py::f"}, {"a.py::f"}, new_word="未登记", stale_word="已过期") == []


def test_subset_run_does_not_compare_ledgers() -> None:
    """子集口径（正反例用的合成源）不做台账对码，否则每条正例都被登记噪声盖住。"""
    src = """
from typing import TypedDict
from langgraph.graph import StateGraph

class S(TypedDict):
    a: str

def node_x(state):
    return {"a": "1"}

g = StateGraph(S)
g.add_node("node_x", node_x)
app = g.compile()
"""
    assert _analyze_src(src) == []
    assert _stats_for(src)["ledger_checked"] == 0


def test_write_of_undeclared_key_fires() -> None:
    """正例：节点写一个 schema 里没有的键 ⇒ 必须报红。"""
    src = """
from typing import TypedDict
from langgraph.graph import StateGraph

class S(TypedDict):
    a: str

def node_x(state):
    return {"a": "ok", "ghost": 1}

g = StateGraph(S)
g.add_node("node_x", node_x)
app = g.compile()
"""
    live = _analyze_src(src)
    assert any("写入未声明键 ['ghost']" in v for v in live), live


def test_nested_dict_write_is_not_a_state_write() -> None:
    """反例：`slots = dict(state["slots"]); slots["k"]=v` 是嵌套数据，不是图状态键。

    这条是本轮真实踩过的假阳性形状（kefu 三个 flow 都用它），误报会让人去声明根本
    不属于 state 的键。
    """
    src = """
from typing import TypedDict
from langgraph.graph import StateGraph

class S(TypedDict):
    slots: dict

def node_x(state):
    slots = dict(state.get("slots", {}))
    slots["order_id"] = "1001"
    return {**state, "slots": slots}

g = StateGraph(S)
g.add_node("node_x", node_x)
app = g.compile()
"""
    assert _analyze_src(src) == [], _analyze_src(src)


def test_undeclared_graph_input_fires() -> None:
    """正例：调用方往图里塞一个未声明的入参键 ⇒ 请求侧静默丢弃，必须报红。"""
    src = """
from typing import TypedDict
from langgraph.graph import StateGraph

class S(TypedDict):
    a: str

def node_x(state):
    return {"a": "1"}

g = StateGraph(S)
g.add_node("node_x", node_x)
app = g.compile()
app.invoke({"a": "1", "ghost_in": 2})
"""
    live = _analyze_src(src)
    assert any("入参含未声明键" in v and "ghost_in" in v for v in live), live


def test_annotated_state_literal_is_judged() -> None:
    """`initial_state: S = {...}` 也算入参构造点（kefu 就是这个形状）。

    早先只认 `ast.Assign`，带注解的赋值抽不出键 ⇒ 那张图的入参面**静默不判**，
    归属却算成功——属于"覆盖数虚高"的形状。
    """
    src = """
from typing import TypedDict
from langgraph.graph import StateGraph

class S(TypedDict):
    a: str

def node_x(state):
    return {"a": "1"}

g = StateGraph(S)
g.add_node("node_x", node_x)
app = g.compile()
initial_state: S = {"a": "x", "ghost_ann": 1}
app.ainvoke(initial_state)
"""
    live = _analyze_src(src)
    assert any("ghost_ann" in v for v in live), live


def test_attribute_receiver_graph_is_judged() -> None:
    """`self._graph = build_graph()` + `self._graph.ainvoke({...})` 也要判得到。

    nl2sql / agent_server 就是这个形状（构造注入与属性接收者）；不认属性末级名时
    这两张图的入参面完全没跑过判据。
    """
    src = """
from typing import TypedDict
from langgraph.graph import StateGraph

class S(TypedDict):
    a: str

def node_x(state):
    return {"a": "1"}

def build_graph():
    g = StateGraph(S)
    g.add_node("node_x", node_x)
    return g.compile()

class Holder:
    def __init__(self) -> None:
        self._graph = build_graph()

    def run(self) -> object:
        return self._graph.ainvoke({"a": "1", "ghost_attr": 1})
"""
    live = _analyze_src(src)
    assert any("ghost_attr" in v for v in live), live


def test_write_on_helper_returned_variable_fires() -> None:
    """正例：`res = step7(state); res["ghost"] = v; return res` 的常量下标写入是更新键。

    KS 的 `node_item_name_confirm` 就是这个形状（`final_state["history"]`）；早先只认
    dictish 初始化，这条写入整条被跳过——盲区登记里"业务键走就地写入已覆盖"那句因此
    是错的。没有这条正例， widening 本身不可证。
    """
    src = """
from typing import TypedDict
from langgraph.graph import StateGraph

class S(TypedDict):
    a: str

def step7(state):
    return state

def node_x(state):
    res = step7(state)
    res["ghost_w"] = 1
    return res

g = StateGraph(S)
g.add_node("node_x", node_x)
app = g.compile()
"""
    live = _analyze_src(src)
    assert any("写入未声明键 ['ghost_w']" in v for v in live), live


def test_local_dict_not_returned_is_still_not_a_state_write() -> None:
    """反例补强：变量出现在 `return {**state, "slots": slots}` 里 ≠ 被当状态整体返回。

    widening 用了"名字出现在裸 return 里"作触发条件，这条确认 slots 那种**只作为值嵌进
    返回体**的形状仍不算 state 写入面（否则 kefu 三个 flow 的 21 处假阳性会回来）。
    """
    src = """
from typing import TypedDict
from langgraph.graph import StateGraph

class S(TypedDict):
    slots: dict

def node_x(state):
    slots = {}
    slots["order_id"] = "1001"
    return {**state, "slots": slots}

g = StateGraph(S)
g.add_node("node_x", node_x)
app = g.compile()
"""
    assert _analyze_src(src) == [], _analyze_src(src)


def test_variable_key_state_write_is_registered_as_blind() -> None:
    """正例：键由变量决定的 `state[k]=v` 追不到 ⇒ 进盲区面（不许当成"没有写入"）。"""
    src = """
from typing import TypedDict
from langgraph.graph import StateGraph

class S(TypedDict):
    a: str

def node_x(state):
    k = "a"
    state[k] = "1"
    return state

g = StateGraph(S)
g.add_node("node_x", node_x)
app = g.compile()
"""
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "node_x")
    writes, blind_flag = GATE._state_writes(fn, {})
    assert blind_flag is True and writes == set()


def test_spread_of_unknown_object_is_registered_as_blind() -> None:
    """正例：`return {**payload}`（payload 非 state）键集静态取不到 ⇒ 算盲区，不许静默少算。"""
    src = "def node_x(state):\n    return {**payload, 'a': 1}\n"
    fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef))
    _writes, blind_flag = GATE._state_writes(fn, {})
    assert blind_flag is True


def test_local_dict_returned_as_state_is_covered() -> None:
    """正例面：`out: dict = {}; out["k"]=v; return out` 要认成写入（nl2sql 四节点用这形状）。"""
    src = 'def node_x(state):\n    out: dict = {}\n    out["ghost2"] = 1\n    return out\n'
    fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef))
    writes, blind_flag = GATE._state_writes(fn, {})
    assert writes == {"ghost2"} and blind_flag is False


def test_lint_graph_state_boundary_is_wired_into_make_lint() -> None:
    """装配面：脚本必须挂在 `make lint` 里（进 `make ci`），否则只是没人跑的孤儿。"""
    makefile = (_ROOT / "Makefile").read_text(encoding="utf-8")
    block = re.search(r"^lint:\n((?:\t.*\n)+)", makefile, re.M)
    assert block, "Makefile 里找不到 lint 目标"
    assert "scripts/lint_graph_state_boundary.py" in block.group(1), block.group(1)


def test_every_lint_script_is_enumerated_in_make_lint() -> None:
    """派生枚举自检：`scripts/lint_*.py` 的每一条都要出现在 `make lint` 里。

    本仓"门禁用手写清单"已复发多次（L-5 / P14 / L-4 / check_doc_sync 枚举等）；这条把
    `make lint` 的清单与文件系统派生集做对称差，新加 lint 脚本却忘了接线即红。
    """
    makefile = (_ROOT / "Makefile").read_text(encoding="utf-8")
    block = re.search(r"^lint:\n((?:\t.*\n)+)", makefile, re.M)
    assert block, "Makefile 里找不到 lint 目标"
    wired = set(re.findall(r"scripts/(lint_[a-z0-9_]+\.py)", block.group(1)))
    present = {p.name for p in (_ROOT / "scripts").glob("lint_*.py")}
    assert present - wired == set(), f"这些 lint 脚本没接进 make lint（门禁不会跑）：{sorted(present - wired)}"
    assert wired - present == set(), f"make lint 引用了不存在的 lint 脚本：{sorted(wired - present)}"


@contextmanager
def _synthetic_src(src: str):
    """把合成源码放进真实包路径跑一遍判定（只为验证规则会开火，不落到仓库里）。"""
    tmp_dir = _ROOT / ".tmp-governance-graph-src"
    tmp_dir.mkdir(exist_ok=True)
    f = tmp_dir / "synthetic_graph.py"
    f.write_text(src, encoding="utf-8")
    GATE._TREES.clear()  # 双保险：合成源码复用同一路径，缓存必须失效
    try:
        yield GATE._py_files() + [f]
    finally:
        f.unlink()
        tmp_dir.rmdir()
        GATE._TREES.clear()


def _analyze_src(src: str) -> list[str]:
    with _synthetic_src(src) as files:
        violations, _blind, _stats = GATE.check(files)
    return [v for v in violations if "synthetic_graph" in v or "tmp-governance" in v]


def _stats_for(src: str) -> dict[str, int]:
    with _synthetic_src(src) as files:
        return GATE.check(files)[2]
