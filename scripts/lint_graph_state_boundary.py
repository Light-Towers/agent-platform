#!/usr/bin/env python3
"""图边界状态键门禁（全仓）：LangGraph 的 StateGraph schema 是唯一真相源。

**要拦的错误形状**：`StateGraph(SomeState)` 只保留 schema 声明过的键——节点返回、
图入参、路由函数读取里任何**未声明的键会被静默丢弃，不报错、不记日志**。本仓已因此
出现过五处真实缺陷（nl2sql 的 `examples` / `filter_table_enabled`、exhibition 的
`skill_error`、knowledge-service 的 `hyde_doc` 与恒空兜底 `file_name`），每次都是
"功能跑完就蒸发"，且单元测试全绿。

**为什么是一条 lint 而不是各应用各自写测试**（AGENTS.md《架构决策原则》三层齐备）：
单一实现=本文件；全局装配=`make lint`（进 `make ci`）；强制门禁=本脚本的 fail-closed 判定。
被检对象全部**派生**（AST 找 StateGraph 宿主、找 add_node 注册点、找 compile() 产出名），
不维护手写清单。

判定面（每张图四个面 + 两条自检）：
1. 写入面：注册节点函数返回 / 就地写入的键 ⊆ schema；
2. 读取面：节点函数所在文件与图文件里对 `state` 的读取键 ⊆ schema；
3. 入参面：`<compiled>.invoke|ainvoke|stream|astream(实参)` 的键 ⊆ schema；
4. 默认值面：以该 schema 注解的模块级 dict 字面量的键 ⊆ schema；
5. 解析自检：宿主必须能解析出 schema 类、每个非 lambda 注册点必须解析出函数，
   解析不了即红（**宁可误报也不静默跳过**）；
6. 盲区对称差：AST 追不到写入形状的返回（跨对象/跨包工厂）逐条登记在
   `BLIND_SPOTS`，实况与登记不符即红——防止扫描面盲区静默扩大。

范围：**只扫产品代码**（跳过任意层级的 `tests/`、`eval/` 目录）；测试里临时搭的图
由测试自己负责，否则替身里的假 schema 会把门禁判成违规。

用法：`uv run python scripts/lint_graph_state_boundary.py`（`--json` 出机器可读摘要）。
退出码：0=通过，1=有违规或盲区漂移。
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUBTREES = ("applications", "packages")
SKIP_DIR_NAMES = {"__pycache__", ".git", ".codeartsdoer", ".tmp-scratch", ".venv", "node_modules", "build", "dist"}
SKIP_PARTS = {"tests", "eval"}

# AST 追不到写入键的返回形状：`file::函数名` → 为什么追不到 + 为什么不影响判定。
# 新增一条要么改成字面量返回 / 就地写入（推荐），要么在此登记理由；两者都不许省略判据。
BLIND_SPOTS: dict[str, str] = {
    # 返回体由 MCPToolAdapter 内部经 result_parser=_parse_web_pages 产出 {"web_search_docs": ...}，
    # 键在适配器实参里而不是本函数的字面量里，AST 追不进对象图。
    "applications/knowledge-service/knowledge_service/query_process/agent/nodes/node_web_search_mcp.py"
    "::node_web_search_mcp": "return adapter.invoke(state)，键在适配器实参里",
    # `return wrap_tool(fn, ...)` 是跨包工厂（agent_core.tools.guarded），返回闭包；
    # 真实写入键来自被包裹的 fn，而叶子规则已把 fn 作为同级叶子单独解析过 ⇒ 无损失。
    "applications/knowledge-service/knowledge_service/query_process/agent/fanout.py::wrap_channel_node": (
        "return 跨包工厂闭包；被包裹的节点函数已由同级叶子单独覆盖"
    ),
    # `return final_state`，final_state 由同文件另一函数返回；整体键集追不到，但
    # `final_state["history"] = ...` 这类常量下标写入已被采集（history 在 schema 里 ⇒ 无违规）。
    "applications/knowledge-service/knowledge_service/query_process/agent/nodes/node_item_name_confirm.py"
    "::node_item_name_confirm": "return helper 返回对象，整体键集追不到；常量下标写入已单独采集",
}

# 「有读无写且未声明」的旋钮登记：读这类键恒取默认值 ⇒ 对应功能不可达。
# 每条 = `相对路径::函数::键` → 待谁拍板。登记与实况由对称差断言绑定：谁把键声明进
# schema 或删掉这条读取，登记就会过期 ⇒ 门禁翻红，逼着当场清理，不留悬空豁免。
# 入参面**判不到**的宿主：`相对路径::原因`。判不到的原因要写清，覆盖数不许把它们
# 算进去（check() 会拿实况与这张登记做对称差）。
UNJUDGED_INPUT_HOSTS: dict[str, str] = {
    "applications/kefu-service/kefu_agent/flows/order_flow.py": (
        "子图由父图节点转发 `state`（`_order_flow.ainvoke(state)`），入参键由外层决定"
    ),
    "applications/kefu-service/kefu_agent/flows/logistics_flow.py": "同上：父图转发 state",
    "applications/kefu-service/kefu_agent/flows/postsale_flow.py": "同上：父图转发 state",
    "applications/nl2sql-service/nl2sql_service/agent/graph.py": (
        "图经构造注入（`self._graph = graph`），静态面追不到调用方传入的 dict"
    ),
}

UNDECLARED_READS: dict[str, str] = {
    "applications/nl2sql-service/nl2sql_service/agent/nodes/recall_example.py::recall_example::example_top_k": (
        "范例召回 top-k 旋钮无注入点，待拍板是否进 Settings（批 1 已登记）"
    ),
    "applications/nl2sql-service/nl2sql_service/agent/nodes/recall_example.py::recall_example::example_score_margin": (
        "范例召回分数 margin 旋钮无注入点，与上一条同批待拍板"
    ),
    "applications/nl2sql-service/nl2sql_service/agent/nodes/finalize.py::finalize::path": (
        "trace 的 path 语义未定（graph/其他），待拍板后再决定声明还是删除"
    ),
}

# 解析缓存：键必须带文件指纹。只按路径缓存会在"同一路径换了内容"时读到上一份 AST
# ——本仓已因此造出过假读数（自写校验脚本缓存跨文件复用）。
_TREES: dict[Path, tuple[tuple[int, int], ast.Module]] = {}


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _py_files() -> list[Path]:
    out: list[Path] = []
    for sub in SUBTREES:
        base = ROOT / sub
        if not base.is_dir():
            continue
        for p in base.rglob("*.py"):
            rel_parts = set(p.relative_to(base).parts[:-1])
            if rel_parts & (SKIP_DIR_NAMES | SKIP_PARTS):
                continue
            out.append(p)
    return sorted(out)


def _tree(path: Path) -> ast.Module:
    stat = path.stat()
    fingerprint = (stat.st_mtime_ns, stat.st_size)
    cached = _TREES.get(path)
    if cached is None or cached[0] != fingerprint:
        cached = (fingerprint, ast.parse(_text(path), filename=str(path)))
        _TREES[path] = cached
    return cached[1]


def _rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _pkg_root(path: Path) -> Path:
    """包根 = `applications/<app>` 或 `packages/<pkg>`（同根内解析符号，不跨应用猜）。"""
    rel = path.relative_to(ROOT)
    return ROOT / rel.parts[0] / rel.parts[1]


def _files_of(pkg: Path, all_files: list[Path]) -> list[Path]:
    return [p for p in all_files if _pkg_root(p) == pkg]


def _classes_with_keys(pkg_files: list[Path]) -> dict[str, list[tuple[Path, set[str]]]]:
    out: dict[str, list[tuple[Path, set[str]]]] = {}
    for path in pkg_files:
        for node in ast.walk(_tree(path)):
            if isinstance(node, ast.ClassDef):
                keys = {
                    t.target.id for t in node.body if isinstance(t, ast.AnnAssign) and isinstance(t.target, ast.Name)
                }
                if keys:
                    out.setdefault(node.name, []).append((path, keys))
    return out


def _functions(pkg_files: list[Path]) -> dict[str, list[tuple[Path, ast.AST]]]:
    out: dict[str, list[tuple[Path, ast.AST]]] = {}
    for path in pkg_files:
        for node in ast.walk(_tree(path)):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                out.setdefault(node.name, []).append((path, node))
    return out


def _dict_keys(node: ast.expr | None) -> set[str]:
    if isinstance(node, ast.Dict):
        return {k.value for k in node.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}
    return set()


def _state_reads(scope: ast.AST) -> set[str]:
    keys: set[str] = set()
    for node in ast.walk(scope):
        if isinstance(node, ast.Call):
            f = node.func
            if (
                isinstance(f, ast.Attribute)
                and f.attr in ("get", "pop")
                and isinstance(f.value, ast.Name)
                and f.value.id == "state"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                keys.add(node.args[0].value)
        elif isinstance(node, ast.Subscript):
            if (
                isinstance(node.value, ast.Name)
                and node.value.id == "state"
                and isinstance(node.slice, ast.Constant)
                and isinstance(node.slice.value, str)
            ):
                keys.add(node.slice.value)
    return keys


def _is_dictish(node: ast.expr) -> bool:
    """可能是 dict 的初始化形状：字面量、推导式、`dict(...)` / `copy(...)`。"""
    if isinstance(node, ast.Dict | ast.DictComp):
        return True
    return (
        isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("dict", "copy", "deepcopy")
    )


def _state_writes(fn: ast.AST, index: dict[str, list[tuple[Path, ast.AST]]]) -> tuple[set[str], bool]:
    """认六种形状：dict 字面量返回、`state[k]=v` / `state.update({...})` 就地写入、
    **本地 dict 变量的常量下标写入**（`out = {}; out["k"] = v; return out`，nl2sql 多个节点
    就是这么写的）、`return 本地 dict 变量`、**`return 由 helper 赋值的本地变量` 上的常量下标写入**
    （`res = step7(state); res["k"] = v; return res`）、`return 同包唯一命名的函数(...)`（一层）。

    追不到的形状置 blind：`return 一个不是 dictish 的本地变量`（键集整体取不到，但上面的常量
    写入仍会单独算进 writes）、常量之外的变量下标写入、追不进对象的工厂返回。
    """
    writes: set[str] = set()
    blind = False
    # 本地 dict 变量名 → 已静态确认的键。**只有被 `return` 出来的本地 dict 才算 state 写入面**：
    # `slots = dict(state["slots"]); slots["order_id"] = x` 是嵌套数据写入，不是图状态的键
    # （把这类写入算进来会造出假阳性——kefu 三个 flow 就是这个形状）。
    declared_local_dicts: set[str] = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Name):
            declared_local_dicts.add(node.value.id)
    locals_: dict[str, set[str]] = {}
    for node in ast.walk(fn):
        targets = None
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target]
        if targets is None or not _is_dictish(node.value):
            continue
        for target in targets:
            if isinstance(target, ast.Name) and target.id in declared_local_dicts:
                locals_.setdefault(target.id, set()).update(_dict_keys(node.value))
        # 非 dictish 的赋值（如 `result = adapter.invoke(state)`）不登记为本地 dict，
        # 后面 `return result` 因此会被判为追不到 ⇒ 进盲区面而不是被当成空写入。

    for node in ast.walk(fn):
        if isinstance(node, ast.Return) and node.value is not None:
            if isinstance(node.value, ast.Dict):
                writes |= _dict_keys(node.value)
                for k, v in zip(node.value.keys, node.value.values):
                    if k is None and not (isinstance(v, ast.Name) and v.id == "state"):
                        blind = True  # {**别的对象} 的键静态取不到
            elif isinstance(node.value, ast.Name):
                if node.value.id in locals_:
                    writes |= locals_[node.value.id]
                elif node.value.id != "state":
                    blind = True
            elif isinstance(node.value, ast.Call):
                callee = node.value.func
                name = callee.id if isinstance(callee, ast.Name) else getattr(callee, "attr", "")
                defs = index.get(name, [])
                if len(defs) == 1:
                    inner, inner_blind = _state_writes(defs[0][1], index)
                    writes |= inner
                    blind = blind or inner_blind
                elif name:
                    blind = True
        elif isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Subscript):
            sub = node.targets[0]
            if not isinstance(sub.value, ast.Name):
                continue
            base = sub.value.id
            if base == "state":
                if isinstance(sub.slice, ast.Constant) and isinstance(sub.slice.value, str):
                    writes.add(sub.slice.value)
                else:
                    blind = True  # 键由变量决定，静态面取不到
            elif base in locals_:
                if isinstance(sub.slice, ast.Constant) and isinstance(sub.slice.value, str):
                    locals_[base].add(sub.slice.value)
                else:
                    blind = True
            elif base in declared_local_dicts:
                # `res = helper(state); res["k"] = v; return res`：res 的键集整体追不到（仍算盲区），
                # 但这条常量下标写入一定会出现在返回体里 ⇒ 是实打实的更新键，不许漏判。
                # KS 的 `final_state["history"]` 就是这个形状，早先被整条跳过。
                if isinstance(sub.slice, ast.Constant) and isinstance(sub.slice.value, str):
                    writes.add(sub.slice.value)
                else:
                    blind = True
            # 其余本地 dict（嵌套数据，如 slots / payload）不算 state 写入面
        elif isinstance(node, ast.Call):
            f = node.func
            if (
                isinstance(f, ast.Attribute)
                and f.attr == "update"
                and isinstance(f.value, ast.Name)
                and (f.value.id == "state" or f.value.id in locals_)
                and node.args
            ):
                writes |= _dict_keys(node.args[0])
    return writes, blind


def _state_graph_call(tree: ast.Module) -> ast.Call | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "StateGraph":
            return node
    return None


def _add_node_sites(tree: ast.Module) -> list[tuple[str, ast.expr]]:
    sites: list[tuple[str, ast.expr]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr != "add_node" or len(node.args) < 2:
                continue
            label = node.args[0]
            if not (isinstance(label, ast.Constant) and isinstance(label.value, str)):
                sites.append(("!<非字面量节点名>", node.args[1]))
                continue
            sites.append((label.value, node.args[1]))
    return sites


def _compiled_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            f = node.value.func
            if isinstance(f, ast.Attribute) and f.attr == "compile":
                names |= {t.id for t in node.targets if isinstance(t, ast.Name)}
    return names


def _annotated_default_keys(schema_name: str, pkg_files: list[Path]) -> set[str]:
    keys: set[str] = set()
    for path in pkg_files:
        for node in ast.walk(_tree(path)):
            if (
                isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and isinstance(node.value, ast.Dict)
                and isinstance(node.annotation, ast.Name)
                and node.annotation.id == schema_name
            ):
                keys |= _dict_keys(node.value)
    return keys


_INVOKE_METHODS = {"invoke", "ainvoke", "stream", "astream"}


def _graph_producers(pkg_files: list[Path]) -> dict[str, Path]:
    """函数名 → 定义它的模块，条件是该函数体内出现 `StateGraph(` 或 `.compile()`。

    这类函数返回编译后的图，所以 `graph = build_graph()` 的左值就是图对象。
    派生自代码，不手写图变量名（本仓实际形状：nl2sql/agent_server/exhibition 用
    `build_graph()`，kefu 用 `build_kefu_graph()` 与三个 `build_*_flow()`，
    knowledge-service 用模块级 `X = builder.compile()`）。
    """
    out: dict[str, Path] = {}
    for path in pkg_files:
        for node in ast.walk(_tree(path)):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            dump = ast.dump(node)
            if "StateGraph" in dump or "compile" in dump:
                out[node.name] = path
    return out


def _graph_vars_in_file(
    tree: ast.Module, producer_names: set[str], *, allow_bare_compile: bool
) -> set[str]:
    """本文件里被赋值为「图」的变量名。

    `allow_bare_compile` 只对**宿主自己的模块**打开：`app = builder.compile()` 里的 builder
    是局部名，静态上认不出它属于哪张图，所以只能靠"在宿主模块内"来归属。对其他文件放开它
    会过度归属（实测：KS 两张图会各自抽到对方全部入参，两张图的判据退化成同一份并集）。
    产出者函数的返回值（`graph = build_graph()`）按函数身份归属，因此允许跨文件。
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if not (isinstance(node, (ast.Assign, ast.AnnAssign)) and isinstance(node.value, ast.Call)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        tgts = [t.id for t in targets if isinstance(t, ast.Name)]
        # 属性目标（`self._graph = build_graph()`）按**末级属性名**归属：调用点常写成
        # `self._graph.ainvoke(...)`，认不出这层就会让整张图的入参面静默不判。
        tgts += [t.attr for t in targets if isinstance(t, ast.Attribute)]
        call = node.value
        f = call.func
        is_compile = allow_bare_compile and isinstance(f, ast.Attribute) and f.attr == "compile"
        is_producer = isinstance(f, ast.Name) and f.id in producer_names
        is_chain = isinstance(f, ast.Attribute) and isinstance(f.value, ast.Call) and (
            (isinstance(f.value.func, ast.Name) and f.value.func.id in producer_names)
            or (isinstance(f.value.func, ast.Attribute) and f.value.func.attr == "compile")
        )
        if is_compile or is_producer or is_chain:
            names.update(tgts)
    return names


def _input_keys_for(
    pkg_files: list[Path], producer_names: set[str], compiled_names: set[str], host_path: Path
) -> set[str]:
    """图调用点的入参键集。

    图变量的来源派生成两类，不手写变量名清单：
    1. 被「本宿主的产出者函数」或任意 `*.compile()` 的返回值赋值的名字（`graph = build_graph()`、
       `app = builder.compile()`、`x = build_graph().with_config(...)` 链）；
    2. 宿主模块里 `X = <builder>.compile()` 的 X。
    **含图自身文件里的调用**——早先跳过它，会漏掉在宿主模块内直接 invoke/stream 的形状。
    """
    # 图变量名按**整包**归属：agent_server 的 `graph = build_graph()` 在 main.py，调用点在
    # api/query_router.py——早先要求同文件，会让这类图"归属成功但一条判据没跑"（虚覆盖）。
    graph_vars: set[str] = set(compiled_names)
    for path in pkg_files:
        graph_vars |= _graph_vars_in_file(_tree(path), producer_names, allow_bare_compile=(path == host_path))
    keys: set[str] = set()
    for path in pkg_files:
        tree = _tree(path)
        assigns: dict[str, ast.expr] = {}
        for node in ast.walk(tree):
            # 带注解的赋值也是实参构造点：kefu 的 `initial_state: KefuState = {...}` 就因
            # 只认 ast.Assign 而抽不出键，整张图的入参面静默不判。
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
                assigns.setdefault(node.targets[0].id, node.value)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                assigns.setdefault(node.target.id, node.value)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            base = node.func.value
            if node.func.attr not in _INVOKE_METHODS or not node.args:
                continue
            recv_name = base.id if isinstance(base, ast.Name) else (
                base.attr if isinstance(base, ast.Attribute) else ""
            )
            if recv_name not in graph_vars:
                continue
            arg = node.args[0]
            stack: list[ast.expr] = [arg]
            seen: set[str] = set()
            while stack:
                cur = stack.pop()
                keys |= _dict_keys(cur)
                if isinstance(cur, ast.Name) and cur.id in assigns and cur.id not in seen:
                    seen.add(cur.id)
                    stack.append(assigns[cur.id])
            if isinstance(arg, ast.Name):
                for inner in ast.walk(tree):
                    if (
                        isinstance(inner, ast.Assign)
                        and isinstance(inner.targets[0], ast.Subscript)
                        and isinstance(inner.targets[0].value, ast.Name)
                        and inner.targets[0].value.id == arg.id
                        and isinstance(inner.targets[0].slice, ast.Constant)
                        and isinstance(inner.targets[0].slice.value, str)
                    ):
                        keys.add(inner.targets[0].slice.value)
                    elif isinstance(inner, ast.For) and isinstance(inner.target, ast.Name):
                        loop_keys = {
                            e.value
                            for e in (inner.iter.elts if isinstance(inner.iter, ast.Tuple) else [])
                            if isinstance(e, ast.Constant) and isinstance(e.value, str)
                        }
                        for sub in ast.walk(inner):
                            if (
                                isinstance(sub, ast.Assign)
                                and isinstance(sub.targets[0], ast.Subscript)
                                and isinstance(sub.targets[0].value, ast.Name)
                                and sub.targets[0].value.id == arg.id
                                and isinstance(sub.targets[0].slice, ast.Name)
                                and sub.targets[0].slice.id == inner.target.id
                            ):
                                keys |= loop_keys
    return keys


def _registry_drift(label: str, live: set[str], registered: set[str], *, new_word: str, stale_word: str) -> list[str]:
    """实况集合与登记台账对码（对称差）；不一致即红，并分别说清是"新增未登记"还是"登记过期"。"""
    drift = live ^ registered
    if not drift:
        return []
    parts = []
    if fresh := sorted(drift & live):
        parts.append(f"{new_word} {fresh}")
    if stale := sorted(drift - live):
        parts.append(f"{stale_word} {stale}")
    return [f"{label}与登记不符：" + "；".join(parts)]


def check(all_files: list[Path] | None = None) -> tuple[list[str], set[str], dict[str, int]]:
    """→ (违规清单, 实况盲区集合, 计数)。计数用于自检与 `--json`。

    `all_files` 传子集（门禁用例的正反例用合成源）时**不做台账对码**：台账记的是
    全仓覆盖面，子集运行天然对不上，把它算进子集会报出与规则无关的红。
    """
    repo_wide = all_files is None
    all_files = all_files if all_files is not None else _py_files()
    violations: list[str] = []
    blind: set[str] = set()
    undeclared_reads: set[str] = set()
    unjudged_hosts: set[str] = set()
    hosts: list[Path] = []
    for path in all_files:
        if "StateGraph" in _text(path) and _state_graph_call(_tree(path)) is not None:
            hosts.append(path)

    stats = {"hosts": len(hosts), "sites": 0, "resolved": 0, "lambdas": 0, "input_sites": 0}
    for host in hosts:
        rel = _rel(host)
        pkg_files = _files_of(_pkg_root(host), all_files)
        call = _state_graph_call(_tree(host))
        assert call is not None
        if not (call.args and isinstance(call.args[0], ast.Name)):
            violations.append(f"{rel}: StateGraph 的 schema 实参不是类名（静态面失效）")
            continue
        schema_name = call.args[0].id
        found = _classes_with_keys(pkg_files).get(schema_name, [])
        if len(found) != 1:
            violations.append(f"{rel}: schema {schema_name} 在包内命中 {len(found)} 处，无法作为唯一真相源")
            continue
        _schema_path, schema = found[0]
        index = _functions(pkg_files)

        for node_name, expr in _add_node_sites(_tree(host)):
            stats["sites"] += 1
            if node_name == "!<非字面量节点名>":
                violations.append(f"{rel}: add_node 的节点名不是字面量，注册面无法判定")
                continue
            if isinstance(expr, ast.Lambda):
                stats["lambdas"] += 1  # 虚拟节点（分叉/合并中转）不写业务键
                continue
            leaves = {
                n.id if isinstance(n, ast.Name) else n.attr
                for n in ast.walk(expr)
                if isinstance(n, ast.Name | ast.Attribute)
            }
            targets: list[tuple[Path, ast.AST]] = []
            for leaf in sorted(leaves):
                defs = index.get(leaf, [])
                if len(defs) > 1:
                    violations.append(f"{rel}::{node_name}: {leaf} 包内重名 {len(defs)} 处，无法唯一解析")
                elif len(defs) == 1:
                    targets.append(defs[0])
            if not targets:
                violations.append(f"{rel}::{node_name}: 叶子 {sorted(leaves)} 解析不出任何函数（规则空转）")
                continue
            stats["resolved"] += 1
            for where, fn in targets:
                writes, is_blind = _state_writes(fn, index)
                if is_blind:
                    blind.add(f"{_rel(where)}::{fn.name}")
                bad = writes - schema
                if bad:
                    violations.append(f"{_rel(where)}::{fn.name} 写入未声明键 {sorted(bad)}（图边界静默丢弃）")
                for key in sorted((_state_reads(_tree(where)) | _state_reads(_tree(host))) - schema):
                    undeclared_reads.add(f"{_rel(where)}::{fn.name}::{key}")

        producers_here = {name for name, where in _graph_producers(pkg_files).items() if where == host}
        compiled_here = _compiled_names(_tree(host))
        if producers_here or compiled_here:
            stats["input_sites"] += 1
            seen = _input_keys_for(pkg_files, producers_here, compiled_here, host)
            label = ",".join(sorted(producers_here | compiled_here))
            bad_input = seen - schema
            if bad_input:
                violations.append(f"{rel}: 图（{label}）入参含未声明键 {sorted(bad_input)}（请求侧静默丢弃）")
            # 归属成功但一个键都抽不出 ⇒ 这条判据对该图是空转的，必须进未判登记
            if not seen:
                unjudged_hosts.add(rel)
        else:
            violations.append(f"{rel}: 既无 compile() 绑定名也无本模块产出者函数——入参面无法归属该图")
            unjudged_hosts.add(rel)
        bad_default = _annotated_default_keys(schema_name, pkg_files) - schema
        if bad_default:
            violations.append(f"{rel}: {schema_name} 的默认值字面量含未声明键 {sorted(bad_default)}")

    if repo_wide:
        violations += _registry_drift(
            "未声明读取的登记",
            undeclared_reads,
            set(UNDECLARED_READS),
            new_word="有读无写的键未登记",
            stale_word="登记已过期（键已声明或读取已删）",
        )
        violations += _registry_drift(
            "入参面覆盖",
            unjudged_hosts,
            set(UNJUDGED_INPUT_HOSTS),
            new_word="入参面判不到但未登记",
            stale_word="登记已过期（该图现在已能判）",
        )
        violations += _registry_drift(
            "盲区登记",
            blind,
            set(BLIND_SPOTS),
            new_word="实况有而未登记",
            stale_word="登记有而实况无（豁免口已过期）",
        )
    stats["unjudged_hosts"] = len(unjudged_hosts)
    stats["ledger_checked"] = int(repo_wide)
    return violations, blind, stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LangGraph 图边界状态键门禁（全仓 StateGraph 宿主）")
    parser.add_argument("--json", action="store_true", help="输出机器可读摘要")
    args = parser.parse_args(argv)

    violations, blind, stats = check()
    if args.json:
        print(
            json.dumps(
                {"violations": violations, "blind_spots": sorted(blind), **stats},
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        for v in violations:
            print(f"  ✗ {v}")
        print(
            f"图边界门禁：StateGraph 宿主 {stats['hosts']} 张 / 注册点 {stats['sites']} 处"
            f"（解析 {stats['resolved']}、虚拟 lambda {stats['lambdas']}）/ 图入参面 {stats['input_sites']} 处"
            f" / 已知盲区 {len(blind)} 处；违规 {len(violations)} 项"
        )
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
