"""基准脚本预算判定的假绿回归（ADR-0013 C Stage 3 取证工具）。

原缺陷：`dropped_writes` 取自**读侧**后端的 stats——查询后端全程不写入，该值恒为 0，
于是「写丢弃 = 0」这条预算永不可能翻红。写侧计数只能在 seed 阶段读到，所以判据必须是
「非零的写丢弃/写跳过能把预算打红」。四条各防一种假绿：预算能过、能红、红在正确的
维度上、以及源码层面不许把写侧计数挪回读侧。
"""

import argparse
import ast
import asyncio
import sys
from importlib import util
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _ROOT / "scripts" / "bench_cache.py"


def _load_module():
    spec = util.spec_from_file_location("bench_cache_under_test", _SCRIPT)
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _clean_write_phase() -> dict[str, int]:
    return {"written": 100, "dropped_writes": 0, "error": 0, "skipped_no_tenant": 0, "skipped_pii": 0}


def _result(**overrides):
    result = {
        "latency_ms": {"p50": 1.0, "p95": 2.0, "p99": 3.0},
        "error_rate": 0.0,
        "hit_rate": 0.99,
        "memory_delta_bytes": 1024,
        "write_phase": _clean_write_phase(),
    }
    result.update(overrides)
    return result


def test_budgets_pass_on_clean_run():
    assert all(_load_module()._budgets(_result()).values())


def test_dropped_writes_from_write_phase_turns_budget_red():
    """预算必须 keyed 在写侧计数上：非零丢弃必须翻红（原实现里这条不可能发生）。"""
    write_phase = {**_clean_write_phase(), "dropped_writes": 7}
    budgets = _load_module()._budgets(_result(write_phase=write_phase))
    assert budgets["dropped_writes"] is False


def test_silently_skipped_writes_turn_budget_red():
    """PII 门禁/空租户造成的静默跳过会被误读成命中率问题，必须单独红。"""
    bench = _load_module()
    for key in ("skipped_pii", "skipped_no_tenant"):
        write_phase = {**_clean_write_phase(), key: 3}
        assert bench._budgets(_result(write_phase=write_phase))["write_skips"] is False, key


def test_seed_reports_write_counters_measured_does_not():
    """seed 产出写侧增量；measure 不许再报 `dropped_writes`（读侧后端全程没写过）。"""

    class _StubCache:
        def __init__(self) -> None:
            self._stats = {"dropped_writes": 0, "error": 0, "skipped_no_tenant": 0, "skipped_pii": 0}
            self.sets = 0

        async def set(self, **_kwargs):
            self.sets += 1
            if self.sets == 2:  # 模拟队列满丢弃一次 + PII 跳过一次
                self._stats["dropped_writes"] += 1
                self._stats["skipped_pii"] += 1

        async def flush(self) -> None:
            return None

        def get_stats(self) -> dict:
            return dict(self._stats)

    bench = _load_module()
    args = argparse.Namespace(tenants_list=["t-a", "t-b"], entries=4, batch=2, dim=8)
    deltas = asyncio.run(bench._seed(_StubCache(), args, per_tenant=2))
    assert deltas["written"] == 4
    assert deltas["dropped_writes"] == 1
    assert deltas["skipped_pii"] == 1

    tree = ast.parse(_SCRIPT.read_text(encoding="utf-8"))
    functions = {node.name: node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)}

    def dict_keys(node) -> set[str]:
        """函数体内所有 dict 字面量的键（返回值可能是先赋值再 return 的变量）。"""
        keys: set[str] = set()
        for inner in ast.walk(node):
            if isinstance(inner, ast.Dict):
                keys.update(key.value for key in inner.keys if isinstance(key, ast.Constant))
        return keys

    assert "dropped_writes" in dict_keys(functions["_seed"])
    assert "dropped_writes" not in dict_keys(functions["_measure"])


def _run_seed_int_with_hashseed(seed: str) -> str:
    """在**独立进程**里取 _seed_int 的读数（PYTHONHASHSEED 只影响新进程）。"""
    import os
    import subprocess

    code = (
        "import importlib.util,sys;"
        "spec=importlib.util.spec_from_file_location('b', sys.argv[1]);"
        "m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m);"
        "print(m._seed_int('tenant-a', 3))"
    )
    env = {**os.environ, "PYTHONHASHSEED": seed}
    out = subprocess.run(
        [sys.executable, "-c", code, str(_SCRIPT)], env=env, capture_output=True, text=True, timeout=120
    )
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


def test_seed_vector_is_a_known_answer():
    module = _load_module()
    assert module._seed_int("tenant-a", 3) == 647847500
    assert module._seed_int("tenant-b", 0) == 182490549


def test_seed_vector_is_stable_across_processes():
    """原实现 `hash((tenant, index))` 在本条面前必红：CPython 对 str 的哈希按进程随机化，
    两次 PYTHONHASHSEED 不同就换一批向量 ⇒ 同一脚本两次跑量的不是同一份数据。"""
    module = _load_module()
    first = _run_seed_int_with_hashseed("1")
    second = _run_seed_int_with_hashseed("2")
    assert first == second == str(module._seed_int("tenant-a", 3))


def test_seed_source_no_longer_uses_process_random_hash():
    """不许把向量种子挪回 `hash(...)`（与"预算不许取自读侧"同一条源码级防线）。

    用 AST 而不是文本匹配：脚本的 docstring 里正**解释**着 `hash((tenant, index))` 这个
    旧写法，文本判据会被自己的说明文字打红。
    """
    tree = ast.parse(_SCRIPT.read_text(encoding="utf-8"))
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "hash" not in called


def test_measure_waits_for_backfill_instead_of_sleeping():
    """`_measure` 必须等回填就绪；悄悄换回 sleep(2.0) 会让全部用例照绿而命中率数字失真。"""
    tree = ast.parse(_SCRIPT.read_text(encoding="utf-8"))
    measure = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "_measure")
    names = {
        node.func.id
        for node in ast.walk(measure)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "_wait_backfill" in names
    assert "sleep" not in names


@pytest.mark.parametrize(
    "info,expected_ready",
    [
        ({"state": "ready", "hash_indexing_failures": "0"}, True),
        ({"state": "backfill_in_progress", "hash_indexing_failures": "0"}, False),
        ({"state": "backfill_paused_by_oom", "hash_indexing_failures": "0"}, False),
        ({"state": "ready", "hash_indexing_failures": "7"}, False),
        ({"state": "ready"}, True),
        ({"hash_indexing_failures": "0"}, False),
        ("not-a-dict", False),
    ],
)
def test_backfill_verdict_matches_upstream_ft_info_states(info, expected_ready):
    """state 取值与 hash_indexing_failures 的语义取自 valkey-search docs/commands/ft.info.md；
    非零失败数意味着一部分行不可检索 ⇒ 命中率不可信，判未就绪而不是放过去。"""
    module = _load_module()
    ready, note = module._backfill_verdict(info)
    assert ready is expected_ready
    assert "state=" in note or "形状" in note


class _FakeSearch:
    """client.ft(index).info() 的形状：按序吐出预设回复，Exception 项就地抛出。"""

    def __init__(self, replies):
        self._replies = list(replies)

    def ft(self, _name):
        return self

    async def info(self):
        if not self._replies:
            raise AssertionError("超出预期轮询次数")
        item = self._replies.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class _FakeCache:
    _index = "idx"

    def __init__(self, replies):
        self._client = _FakeSearch(replies)


def test_wait_backfill_returns_when_ready():
    import asyncio

    module = _load_module()
    cache = _FakeCache([{"state": "backfill_in_progress", "hash_indexing_failures": "0"},
                        {"state": "ready", "hash_indexing_failures": "0"}])
    note = asyncio.run(module._wait_backfill(cache, 5.0))
    assert "state=ready" in note


def test_wait_backfill_aborts_instead_of_measuring_a_hot_index():
    """回填不结束就中止：带着"命中率 0.6"回去会被读成容量不足，实际是没等够。"""
    import asyncio

    module = _load_module()
    cache = _FakeCache([{"state": "backfill_paused_by_oom", "hash_indexing_failures": "0"}] * 400)
    with pytest.raises(SystemExit) as excinfo:
        asyncio.run(module._wait_backfill(cache, 0.2))
    assert "回填未在" in str(excinfo.value)


def test_wait_backfill_survives_transient_info_errors():
    import asyncio

    module = _load_module()
    cache = _FakeCache([ConnectionError("boom"), {"state": "ready", "hash_indexing_failures": "0"}])
    note = asyncio.run(module._wait_backfill(cache, 5.0))
    assert "state=ready" in note
