"""缓存计数 → 共享契约 `CacheStatsReport` 的闭环门禁（2026-10-27）。

钉四件事：

1. **有计数就得有上报**：两个后端能产出的每一个计数名都必须是契约模型的字段。
   反例形状：后端新加一个计数器（如 `dropped_writes` 那类），探针面静默不上报——
   运维看到的现象是"某类丢弃在涨但 health 看不出来"。
2. **有字段就得有生产者**：契约里的计数字段不许是空头位（写了没人产，读的人会等一个不来的数）。
3. **被检对象派生，不手写清单**：产数名从 `CacheStats` 的 record 调用点、`snapshot()` 派生键、
   `ValkeySemanticCache._runtime_counts` 字面量、以及 disabled 后端的真实返回里取。
   本仓的复发债是"门禁用手写表数被检对象，表本身就是盲区"（排期台账 §31）。
4. **两个装配点都在**：agent_server 与 federation 的 /health 都必须经 `CacheStatsReport` 出数，
   不在其中一处直接摊 `get_stats()`——摊 dict 会让两处的键集合各走各的。

`from_counts` 的行为面（缺键填 0、未知键忽略、None 不炸）也在本文件里，因为它就是
"固定形状"这条设计的全部含义；探针路径不许因为后端多一个计数器就 500。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from shared_schemas import CacheStatsReport

_ROOT = Path(__file__).resolve().parents[2]
_VALKEY = _ROOT / "packages/agent-runtime/agent_runtime/cache/valkey_backend.py"
_DISABLED = _ROOT / "packages/agent-runtime/agent_runtime/cache/disabled_backend.py"
_STATS = _ROOT / "packages/agent-core/agent_core/cache/stats.py"


def _target_name(target: ast.expr | None) -> str | None:
    """匹配 `x = {...}` 与 `self.x = {...}` 两种写法（后者 target 是 Attribute）。"""
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    return None


def _dict_literal_keys(path: Path, func_name: str, var_name: str) -> set[str]:
    """取某个函数里 `var_name = {...}`（含 `self.var_name = {...}`）字面量的键集合。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for fn in (n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef | ast.FunctionDef) and n.name == func_name):
        for stmt in ast.walk(fn):
            targets = getattr(stmt, "targets", None) or [getattr(stmt, "target", None)]
            if isinstance(stmt, ast.Assign | ast.AnnAssign) and any(_target_name(t) == var_name for t in targets):
                if isinstance(stmt.value, ast.Dict):
                    return {k.value for k in stmt.value.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}
    pytest.fail(f"{path.name}:{func_name} 里找不到 `{var_name} = {{...}}` 字面量 —— 派生口径已失效")


def _string_arg_calls(path: Path, attr: str) -> set[str]:
    """取 `X.attr("name")` 形式调用里的字面量参数（record 的层名）。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = set()
    for call in ast.walk(tree):
        if (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr == attr
            and call.args
            and isinstance(call.args[0], ast.Constant)
            and isinstance(call.args[0].value, str)
        ):
            out.add(call.args[0].value)
    return out


def _produced_counter_names() -> set[str]:
    """两个后端真实产出的键集合（派生，非手写）。"""
    names: set[str] = set()
    # CacheStats.record(...) 的层名：命中/未命中分项
    names |= _string_arg_calls(_VALKEY, "record")
    # CacheStats.snapshot() 自己造的两个键
    names |= _string_arg_calls(_STATS, "get")  # _counts.get("total") / .get("l1_hit") 等
    # valkey 的运行时计数器
    names |= _dict_literal_keys(_VALKEY, "__init__", "_runtime_counts")
    # get_stats() 另外贴上的两个身份键
    names |= {"backend", "scope"}
    # disabled 后端真实返回（不靠读代码猜，直接实例化取键）
    from agent_runtime.cache.disabled_backend import DisabledSemanticCache

    names |= set(DisabledSemanticCache("probe").get_stats())
    return names


def test_every_produced_counter_has_a_contract_field():
    produced = _produced_counter_names()
    assert produced >= {"backend", "scope", "total", "hit_rate", "dropped_writes"}, "派生结果本身不成立"
    unreported = sorted(produced - set(CacheStatsReport.model_fields))
    assert not unreported, f"后端产出了但契约没有字段（探针面静默不上报）：{unreported}"


def test_every_contract_counter_has_a_producer():
    produced = _produced_counter_names()
    phantom = sorted(set(CacheStatsReport.model_fields) - produced)
    assert not phantom, f"契约里有没人产出的计数字段（读的人会等一个不来的数）：{phantom}"


def test_from_counts_fills_missing_and_ignores_unknown():
    """固定形状的全部含义：缺的补 0、多的忽略、None 不炸（探针路径不许 500）。"""
    counters = {k for k in CacheStatsReport.model_fields if k not in ("backend", "scope")}

    sparse = CacheStatsReport.from_counts({"backend": "disabled", "scope": "agent_server"})
    assert {k: getattr(sparse, k) for k in counters} == {k: getattr(CacheStatsReport(), k) for k in counters}, (
        "稀疏输入必须把所有计数渲成缺省值——键集合恒定才有'没发生'与'没上报'可区分"
    )
    assert sparse.backend == "disabled" and sparse.scope == "agent_server", "身份键照实透传"

    unknown = CacheStatsReport.from_counts({"total": 3, "hit_rate": 0.5, "brand_new_counter": 9})
    assert unknown.total == 3 and unknown.hit_rate == 0.5
    assert not hasattr(unknown, "brand_new_counter"), "未知键必须被忽略而不是报错或透传"

    empty = CacheStatsReport.from_counts(None)
    assert {k: getattr(empty, k) for k in counters} == {k: getattr(CacheStatsReport(), k) for k in counters}


def test_both_health_assembly_points_use_the_shared_model():
    """装配面：两个 /health 都经 CacheStatsReport 出数，不各摊各的 dict。"""
    servers = {
        "agent_server": _ROOT / "applications/agent_server/api/health_router.py",
        "federation": _ROOT / "applications/agent_federation/api/server.py",
    }
    for app, path in servers.items():
        src = path.read_text(encoding="utf-8")
        assert "CacheStatsReport.from_counts" in src, f"{app} 的 /health 没有经共享模型出缓存计数"
        assert 'get_stats()["' not in src, f"{app} 在直接读单个计数键，绕过了固定形状"
