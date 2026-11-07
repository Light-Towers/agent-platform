"""`scripts/evidence/face_basis.py`（面基准唯一实现）的门禁自测。

方案：`docs/plans/plan-error-contract-staged-split-2026-11-06.md` §3.4。

这一套用例的存在理由不是"给新脚本加点覆盖率"，而是把本轮抬出的那条**同型根因**钉成机器不变量：
七枚红里两枚（`MISS-DECL=2` / `BASIS-BLIND-TO-NEW-FILES=2`）是同一件事被两把不同源的尺子各报一次。
按《架构决策原则》三层齐备，"单一实现 + 全局装配"缺一层就只是约定，所以这里钉的是**谓词本身**：

- 判据必须**双向**咬（只比单向 = 把另一条线多出来的路径读成无关项）；
- "件在而集为空"必须**拒判**，不许读成"这一轮没有活"（在册「零值拒判」同族）；
- 计数键与路径行数脱钩（件被手改）必须咬 —— 这是"键绑件名不绑内容"那型根因的正解；
- 判决必须绑它当时的 HEAD，换了 commit 还拿来当输入就是"上一轮的判决当这一轮的输入"；
- 件读法（BOM/UTF-16）必须与 `normalize_dump.sniff_encoding` 同源，不复刻第二份。

全程不起子进程、不碰工作树：与 `tests/governance/test_evidence_scripts.py` 同一条纪律。
"""

from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_DIR = REPO_ROOT / "scripts" / "evidence"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, EVIDENCE_DIR / (name + ".py"))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fb = _load("face_basis")
HEAD40 = "c" * 40


# --- ① 指针不可失效：脚本在位、可解析、自测格非空转 --------------------------


def test_face_basis_file_exists_and_parses():
    import ast

    src = (EVIDENCE_DIR / "face_basis.py").read_text(encoding="utf-8")
    ast.parse(src, filename="face_basis.py")
    assert "subprocess" in src, "读数层必须在件里（消费方不许各自再拼一遍 git）"


def test_selftest_reports_all_cells_ok():
    """CLI `--mode selftest` 的格必须齐备且全 OK。

    断言的是**格名清单**而不是"数量 >= N"：数量下限拦不住"某一格被删而另一格加两遍"，
    本轮实踩过一次（自测数 7 而真缺的那格正好没被测到）。
    """
    ok, log = fb.selftest()
    names = [ln.split("=")[0] for ln in log]
    expect = {
        "ST-1-norm",
        "ST-2-diff-both-ways",
        "ST-2b-diff-identical-no-bite",
        "ST-3-off-face-bites",
        "ST-4-porcelain-parse",
        "ST-5-ext-fresh",
        "ST-6a-derived-parse",
        "ST-6b-bind-teeth",
        "ST-7-empty-artifact-refuses",
        "ST-8-read-text-bom-both-shapes",
    }
    assert expect <= set(names), f"缺格：{sorted(expect - set(names))}"
    assert len(names) == len(set(names)), f"重格：{names}"
    assert ok, [ln for ln in log if "<<<" in ln]


def test_module_declares_null_blob_once():
    """intent-to-add 的空 blob OID 全仓只此一处：各处各抄一份就会有人抄错。"""
    assert fb.NULL_BLOB == "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"


# --- ② 归一与集合对拍（双向）--------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expect"),
    [
        ("  a/b.py ", "a/b.py"),
        ('"a/b.py"', "a/b.py"),
        ("a\\b.py", "a/b.py"),
        ('"a\\b.py"', "a/b.py"),
        ("", ""),
        # 边界登记：norm 只处理书写，不折叠结构——`a//b.py` 与 `a/b.py` 是两个不同的量，
        # 呲不到这一对就会把“同一条路径的两种写法”读成“两条路径”。
        ("a//b.py", "a//b.py"),
    ],
)
def test_norm_shapes(raw, expect):
    assert fb.norm(raw) == expect


def test_diff_sets_bites_both_ways():
    d = fb.diff_sets(["a", "b"], ["a", "c"])
    assert d["only_left"] == ["b"] and d["only_right"] == ["c"]
    # 单向比较在这一对上会"看起来没问题"——两向都算才是对拍。
    assert fb.diff_sets(["a"], ["a"]) == {"only_left": [], "only_right": []}
    assert fb.diff_sets([], ["ghost.md"])["only_right"] == ["ghost.md"]


def test_off_face_bites_only_untracked_not_on_basis():
    assert fb.off_face(["tracked.py"], ["new.md", "tracked.py"]) == ["new.md"]
    # 已 intent-to-add 的新文件在基准面上 ⇒ 不点名（否则这一格恒红，门就被人关掉了）。
    assert fb.off_face(["new.md", "tracked.py"], ["new.md"]) == []
    assert fb.off_face(["a"], []) == []


def test_read_porcelain_takes_rename_target_and_skips_noise():
    paths, untracked = fb.read_porcelain(" M a.py\n?? new.md\nR  old.py -> renamed.py\n\n??   \n")
    assert paths == ["a.py", "new.md", "renamed.py"]
    assert untracked == ["new.md"]


def test_read_face_dedups_and_sorts():
    assert fb.read_face("b.py\na.py\nb.py\n\n") == ["a.py", "b.py"]


# --- ③ 判决新鲜度：fail-closed，坏形状一律判不新鲜 ----------------------------


@pytest.mark.parametrize(
    ("registered", "actual", "expect"),
    [
        ("a" * 40, "a" * 40, True),
        ("a" * 40, "b" + "a" * 39, False),
        ("", "a" * 40, False),
        ("a" * 40, "", False),
        ("not-a-hash", "not-a-hash", False),  # 两个相同的手抄垃圾串不许蒙过
        ("A" * 40, "A" * 40, False),  # 十六进制必须小写（git 的输出形状）
        ("a" * 39, "a" * 39, False),  # 短一位也是"没绑上"，不是"差不多"
    ],
)
def test_ext_fresh_matrix(registered, actual, expect):
    assert fb.ext_fresh(registered, actual) is expect


# --- ④ 键绑内容：计数键 / 行数 / HEAD 三者同源才算一份可核对的申报 -----------


DERIVED_OK = (
    f"SUMMARY) head={HEAD40} candidate=3 own=2 held=1 closure-violations=0\n"
    "OWN-FILE: a.py\nOWN-FILE: b.py\nHELD-FILE: z.py\n"
)


def test_read_derived_own_picks_only_own_rows():
    d = fb.read_derived(DERIVED_OK, "OWN")
    assert d["paths"] == ["a.py", "b.py"]
    assert d["count"] == 2 and d["summary_count"] == 2
    assert d["head"] == HEAD40 and d["shape"] == "summary-list"
    # 同一件按 HELD 读必须只拿到 held 那一行（键名混用会把 held 当 own 递下去）。
    assert fb.read_derived(DERIVED_OK, "HELD")["paths"] == ["z.py"]


def test_bind_ok_passes_only_when_count_key_head_and_paths_agree():
    good, why = fb.bind_ok(fb.read_derived(DERIVED_OK, "OWN"), HEAD40)
    assert good and why == "BIND-OK"


@pytest.mark.parametrize(
    ("text", "key", "current_head", "why_prefix"),
    [
        ("OWN-FILE: a.py\n", "OWN", HEAD40, "NO-COUNT-KEY"),  # 纯路径件：数只绑件名
        ("nothing here\n", "OWN", HEAD40, "NO-DECLARED-PATHS"),  # 件在而集为空 ⇒ 拒判
        (f"SUMMARY) head={'d' * 40} own=2\nOWN-FILE: a.py\nOWN-FILE: b.py\n", "OWN", HEAD40, "HEAD-MOVED"),
        (f"SUMMARY) head={HEAD40} own=5\nOWN-FILE: a.py\nOWN-FILE: b.py\n", "OWN", HEAD40, "COUNT-MISMATCH"),
        ("SUMMARY) own=2\nOWN-FILE: a.py\nOWN-FILE: b.py\n", "OWN", HEAD40, "NO-HEAD-BINDING"),
    ],
)
def test_bind_ok_refuses_every_unbound_shape(text, key, current_head, why_prefix):
    good, why = fb.bind_ok(fb.read_derived(text, key), current_head)
    assert not good
    assert why.startswith(why_prefix), f"期望 {why_prefix} 实得 {why}"


def test_empty_summary_count_still_bites_not_divides():
    """`own=0` 与"件里没有 own 这个键"是两件事：前者是判决说没有活，后者是不可核对。"""
    text = f"SUMMARY) head={HEAD40} own=0\n"
    d = fb.read_derived(text, "OWN")
    assert d["summary_count"] == 0 and d["count"] == 0
    good, why = fb.bind_ok(d, HEAD40)
    assert not good and why.startswith("NO-DECLARED-PATHS")


# --- ⑤ 件读法与 normalize_dump 同源（不复刻第二份就迟早分叉）----------------


def test_read_text_reuses_the_registered_sniffer():
    import normalize_dump  # 同目录单一实现（sys.path 由 face_basis 自己负责）

    assert fb.sniff_encoding is normalize_dump.sniff_encoding, "复刻第二份 BOM 嗅探 = 散点式实现"


@pytest.mark.parametrize(
    "prefix",
    [
        b"",  # 纯 UTF-8
        b"\xef\xbb\xbf",  # PS5.1 `Set-Content -Encoding utf8`
    ],
)
def test_read_text_strips_bom_from_ps51_artifacts(prefix):
    payload = "applications/a.py\napplications/b.py\n"
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "ext.txt"
        p.write_bytes(prefix + payload.encode("utf-8"))
        got = fb.read_text(p)
        lines = [fb.norm(x) for x in got.splitlines() if fb.norm(x)]
        # 本轮实踩的那一口：BOM 让首条路径变成"另一条路径"，于是 hash-object 读不到、
        # 判决被说成 STALE、已批准的活被静默减掉。
        assert "\ufeff" not in got
        assert lines == ["applications/a.py", "applications/b.py"]


def test_read_text_handles_utf16le_redirect():
    payload = "applications/a.py\n"
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "gate.txt"
        p.write_bytes(payload.encode("utf-16"))  # PS5.1 `>` 的默认形状
        assert fb.read_text(p) == payload
