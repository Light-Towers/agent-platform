"""取证脚本（`scripts/evidence/`）的门禁自测。

方案：`docs/plans/plan-evidence-scripts-intake-2026-10-04.md`。

这套用例钉的是**纯逻辑不变量**，不打网络、不调 `gh`：
「按 `on.push.paths` × changed paths 派生预期 check 名」这条曾经因为用正则取 `jobs:`
而把真阳性红漏成无关项（`jobs:` 位于文件末尾时匹配不到终止符）。比任何账面措辞都更
需要回归保护的是这条谓词，而不是 `[A]`–`[G]` 的网络调用。
"""

from __future__ import annotations

import ast
import importlib.util
from datetime import datetime
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


_verify = _load("verify_main_tip")
_dump = _load("normalize_dump")


@pytest.fixture(autouse=True)
def _no_subprocess(monkeypatch):
    """本套用例**不得**访问网络/子进程（判据 3）。

    autouse 拦断两条出口：任何 `gh`/`git` 调用都被替身直接抛错 ⇒ 一旦将来有人
    把需要网络的步骤接进纯函数路径，这里立刻红，而不是靠 reviewer 自觉。
    （`main()` 里被 monkeypatch 的是 `verify` 本身，不会走到这里。）
    """
    def _forbidden(*_a, **_kw):
        raise AssertionError("本套用例禁止调用子进程（gh/git）——它应只测纯逻辑")

    monkeypatch.setattr(_verify, "_run", _forbidden)
    monkeypatch.setattr(_verify, "gh_api", _forbidden)


# --- ① 指针不可失效：脚本必须真实存在且可解析 --------------------------------

@pytest.mark.parametrize("fname", ["verify_main_tip.py", "normalize_dump.py", "README.md"])
def test_evidence_files_exist(fname: str):
    assert (EVIDENCE_DIR / fname).is_file(), "账面把这些文件当可重跑指针引用，缺失即指针失效"


def test_scripts_are_parseable():
    for fname in ("verify_main_tip.py", "normalize_dump.py"):
        ast.parse((EVIDENCE_DIR / fname).read_text(encoding="utf-8"), filename=fname)


# --- ② 派生式预期集：曾经的坑逐个钉住 ----------------------------------------

CI_YML = """\
name: agent-platform-ci
on:
  push:
    branches: [main]
    paths:
      - 'docs/**'
      - 'packages/**'
jobs:
  ci:
    runs-on: ubuntu-latest
"""

JOBS_AT_EOF_YML = """\
name: tail-case
on:
  push:
    paths:
      - 'scripts/**'
jobs:
  ha:
    runs-on: ubuntu-latest
"""


def test_paths_filter_hit_and_miss():
    texts = {"x/ci.yml": CI_YML}
    hit, _ = _verify.derive_expected_checks(texts, ["docs/TODO.md"])
    miss, _ = _verify.derive_expected_checks(texts, ["README.md"])
    assert "ci" in hit
    assert "ci" not in miss, "不该跑的写进集合 ⇒ 永远等不到而被误判未达成"


def test_two_star_does_not_cross_into_sibling_dir():
    """`docs/**` 命中 docs 子树，不命中仓库根的 `docs.md`。"""
    expected, _ = _verify.derive_expected_checks({"x/ci.yml": CI_YML}, ["docs.md"])
    assert "ci" not in expected


def test_jobs_block_at_end_of_file_is_not_lost():
    """旧正则坑的回归钉：`jobs:` 在文件末尾时，jobs 名仍必须进预期集。"""
    expected, audit = _verify.derive_expected_checks({"x/tail.yml": JOBS_AT_EOF_YML}, ["scripts/a.py"])
    assert "ha" in expected, sorted(expected)
    assert audit["tail-case (tail.yml)"]["jobs"] == ["ha"]


def test_yaml_11_boolean_on_key_is_honored():
    """YAML 1.1 把裸 `on:` 解成布尔 True 键 ⇒ 只取 "on" 会当成不触发。"""
    cfg = _verify._safe_load(CI_YML)
    assert "on" not in cfg and True in cfg, "前置事实：PyYAML 按 YAML 1.1 解出 True 键"
    assert _verify._push_block(cfg) is not None
    expected, _ = _verify.derive_expected_checks({"x/ci.yml": CI_YML}, ["packages/agent-runtime/x.py"])
    assert "ci" in expected


def test_no_paths_filter_means_always_triggered():
    texts = {"x/any.yml": "name: any\non:\n  push:\n    branches: [main]\njobs:\n  lint:\n    runs-on: x\n"}
    expected, _ = _verify.derive_expected_checks(texts, ["whatever.txt"])
    assert "lint" in expected


def test_workflow_without_push_trigger_is_excluded():
    texts = {"x/dispatch.yml": "name: dispatch\non:\n  workflow_dispatch:\njobs:\n  llm-eval:\n    runs-on: x\n"}
    expected, _ = _verify.derive_expected_checks(texts, ["docs/TODO.md"])
    assert "llm-eval" not in expected


def test_codeql_analyze_checks_are_always_expected():
    """两个 Analyze 不来自仓内 workflow 文件（GitHub 默认 code scanning setup）。"""
    expected, _ = _verify.derive_expected_checks({}, [])
    assert expected == {"Analyze (actions)", "Analyze (python)"}


# --- ③ 真实 workflow 文本上的形状断言（只读本地文件，无网络） ------------------

def test_real_workflows_docs_only_does_not_expect_ha_or_assembly():
    texts = _verify.load_workflow_texts(REPO_ROOT)
    expected, _ = _verify.derive_expected_checks(texts, ["docs/TODO.md", "CHANGELOG.md"])
    assert expected == {"Analyze (actions)", "Analyze (python)", "ci"}, sorted(expected)


def test_real_workflows_runtime_change_expects_ha():
    texts = _verify.load_workflow_texts(REPO_ROOT)
    expected, _ = _verify.derive_expected_checks(texts, ["packages/agent-runtime/sandbox.py", "tests/ha/test_x.py"])
    assert {"ci", "ha", "assembly"} <= expected, sorted(expected)


def test_missing_workflow_dir_raises_not_silently_empty(tmp_path):
    with pytest.raises(FileNotFoundError):
        _verify.load_workflow_texts(tmp_path)


# --- ④ 反向判据：PyYAML 缺席必须 fail-closed，绝不降级成正则 ------------------

def test_dependency_absent_raises(monkeypatch):
    monkeypatch.setattr(_verify, "_yaml", None)
    with pytest.raises(_verify.EvidenceDependencyError):
        _verify.derive_expected_checks({"x/ci.yml": CI_YML}, ["docs/TODO.md"])


def test_main_returns_exit_2_on_dependency_absent(monkeypatch, capsys):
    """`2` = 前置不可用，**从不**折算成通过；也不得退化成「正则解析成功但静默漏 check」。"""

    def _boom(*_a, **_kw):
        raise _verify.EvidenceDependencyError("mock：PyYAML 缺席")

    monkeypatch.setattr(_verify, "verify", _boom)
    rc = _verify.main(["--merge-sha", "deadbeef", "--merged-at", "2026-10-04T00:00:00Z"])
    assert rc == 2
    assert "IMPORT_FAIL" in capsys.readouterr().err


def test_main_returns_exit_2_on_precondition_failure(monkeypatch, capsys):
    def _boom(*_a, **_kw):
        raise RuntimeError("gh api 未登录")

    monkeypatch.setattr(_verify, "verify", _boom)
    rc = _verify.main(["--merge-sha", "deadbeef", "--merged-at", "2026-10-04T00:00:00Z"])
    assert rc == 2
    assert "PRECONDITION_FAIL" in capsys.readouterr().err


def test_verify_fails_closed_when_head_is_not_tip(monkeypatch):
    """预期集取自本地工作区 workflow ⇒ HEAD != tip 必须前置失败（走 rc=2 通道），
    绝不拿漂移的预期集硬算——该红的 check 没进集合就是静默假绿。"""

    def _fake_run(argv):
        assert argv[:2] == ["git", "rev-parse"], "守卫通过前不应有其他子进程调用"
        return "head-sha" if argv[-1] == "HEAD" else "tip-sha"

    monkeypatch.setattr(_verify, "_run", _fake_run)
    with pytest.raises(RuntimeError, match="本地 HEAD"):
        _verify.verify("tip-sha", datetime(2026, 10, 4), 48)


def test_verify_exit_code_mapping_is_not_inverted(monkeypatch, tmp_path, capsys):
    """PASS ⇒ 0，未达成 ⇒ 1（把 rc 映射写反会让 CI 上的红永远看不见）。"""
    out = str(tmp_path / "tip.txt")
    monkeypatch.setattr(_verify, "verify", lambda *_a: (True, ["=== 总体：PASS ==="]))
    assert _verify.main(["--merge-sha", "aaaa", "--merged-at", "2026-10-04T00:00:00Z", "--out", out]) == 0
    monkeypatch.setattr(_verify, "verify", lambda *_a: (False, ["=== 总体：未达成 ==="]))
    assert _verify.main(["--merge-sha", "bbbb", "--merged-at", "2026-10-04T00:00:00Z", "--out", out]) == 1
    assert (tmp_path / "tip.txt").read_text(encoding="utf-8").startswith("=== 总体")
    capsys.readouterr()  # 上面两次 main() 的 stdout 在此丢弃，避免污染后续用例输出


# --- ⑤ UTF-16 坑的固化：dump 转码 --------------------------------------------

@pytest.mark.parametrize("enc", ["utf-16-le", "utf-16-be"])
def test_sniff_bom_before_utf8(tmp_path, enc: str):
    """以 utf-8 读会得到夹 NUL 的假文本（肉眼正常、计数全 0）⇒ 必须先按 BOM 判编码。"""
    bom = b"\xff\xfe" if enc == "utf-16-le" else b"\xfe\xff"
    p = tmp_path / "dump.txt"
    p.write_bytes(bom + "主干 ci pass".encode(enc))
    assert _dump.sniff_encoding(p.read_bytes()) == "utf-16"

    dest, used, text = _dump.normalize(p)
    assert used == "utf-16"
    assert "\x00" not in text and "ci pass" in text
    assert dest.read_text(encoding="utf-8") == text


def test_plain_utf8_dump_is_passed_through(tmp_path):
    p = tmp_path / "plain.txt"
    p.write_bytes("已落盘\n".encode("utf-8"))  # 写字节：text 模式在 Windows 会把 \n 变 \r\n
    assert _dump.sniff_encoding(p.read_bytes()) == "utf-8"
    _dest, used, text = _dump.normalize(p)
    assert used == "utf-8" and text == "已落盘\n"


def test_dump_main_reports_missing_file_as_rc_1(tmp_path):
    assert _dump.main([str(tmp_path / "nope.txt")]) == 1


def test_dump_main_skips_already_utf8_product(tmp_path, capsys):
    """防链式：`.utf8` 产物再喂进来必须跳过且 rc=1，不得生成 `x.utf8.utf8` 副本。"""
    p = tmp_path / "x.txt.utf8"
    p.write_bytes("ok\n".encode("utf-8"))
    assert _dump.main([str(p)]) == 1
    assert not (tmp_path / "x.txt.utf8.utf8").exists(), "链式副本被生成 ⇒ 防链式守卫失效"
    assert "跳过" in capsys.readouterr().err
