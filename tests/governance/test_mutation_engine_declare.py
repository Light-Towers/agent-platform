"""战役引擎 `--declare` 那条判据自己的用例（判据没测 = 又是一条"写了等着红"的规则）。

为什么单独立一件：`make mutation` 一直只产"待定性清单"，**存活集合变了没人拦**——
只有 §11 的散文记着"这 7 刀为什么还活着"。本批把那条散文变成机器判据之后，
判据本身必须可测，否则它和它要替代的散文一样不可核对（AGENTS.md「三层齐备」的第三层）。

`diff_survivors` 是纯函数 ⇒ 直接喂假报告，不起子进程、不碰被检目录。
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "mutation_engine.py"


def _load():
    spec = importlib.util.spec_from_file_location("mutation_engine_under_test", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


engine = _load()


def _row(digest: str, verdict: str, *, line: int = 10, op: str = "num:1→2") -> dict:
    return {
        "digest": digest,
        "file": "packages\\agent-runtime\\agent_runtime\\cache\\valkey_backend.py",
        "line": line,
        "operator": op,
        "verdict": verdict,
    }


def test_same_survivor_set_reports_no_drift() -> None:
    """集合一致 ⇒ 两个方向都空，且沿用数等于存活数（这条红了就说明判据在瞎报）。"""
    prev = [_row("a", "killed"), _row("b", "survived"), _row("c", "survived")]
    now = [_row("a", "killed"), _row("b", "survived"), _row("c", "survived")]
    drift = engine.diff_survivors(now, prev)
    assert drift["regressed"] == [] and drift["improved"] == []
    assert drift["carried"] == 2
    assert drift["denominator"] == (3, 3)


def test_survivor_that_became_killed_is_reported_as_improvement_not_regression() -> None:
    """以前存活、现在被杀 ⇒ 只进 `improved`。把它混进 `regressed` 会让人去查"哪条用例退化了"，方向反了。"""
    prev = [_row("a", "survived"), _row("b", "survived")]
    now = [_row("a", "killed"), _row("b", "survived")]
    drift = engine.diff_survivors(now, prev)
    assert drift["improved"] == ["a"]
    assert drift["regressed"] == []
    assert drift["carried"] == 1


def test_killed_surviving_again_is_a_regression_and_carries_the_locator() -> None:
    """以前杀得动、现在杀不动 ⇒ `regressed`，且必须带 file:line operator——只给 digest 没法定位。"""
    prev = [_row("a", "killed", line=225, op="cmp:Lt→LtE"), _row("b", "survived")]
    now = [_row("a", "survived", line=225, op="cmp:Lt→LtE"), _row("b", "survived")]
    drift = engine.diff_survivors(now, prev)
    assert drift["regressed"] == ["a"]
    assert drift["improved"] == []
    assert len(drift["regressed_where"]) == 1
    where = drift["regressed_where"][0]
    assert "valkey_backend.py" in where and ":225" in where and "cmp:Lt→LtE" in where


def test_denominator_change_is_visible_so_new_positions_are_not_read_as_drift() -> None:
    """被检文件动过 ⇒ 位置数会变；判据把分母原样交出来，由调用方拒绝"直接比集合"。"""
    prev = [_row("a", "killed")]
    now = [_row("a", "killed"), _row("z", "killed")]
    drift = engine.diff_survivors(now, prev)
    assert drift["denominator"] == (2, 1)
    assert drift["regressed"] == [] and drift["improved"] == []


def test_partial_reruns_are_not_allowed_to_judge_the_set() -> None:
    """部分复跑不许做集合判定，否则"我只跑了一个文件"会被读成"其余文件没漂移"。"""
    assert engine.set_check_allowed("", 0) is True
    assert engine.set_check_allowed("valkey_backend", 0) is False
    assert engine.set_check_allowed("", 8) is False
    # main() 确实走的是这个判据（不是另写一份口径）
    src = _SCRIPT.read_text(encoding="utf-8")
    assert "partial = not set_check_allowed(args.only, args.limit_per_file)" in src
    assert "不做判定" in src
