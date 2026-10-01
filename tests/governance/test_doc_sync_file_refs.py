"""doc-sync 门禁「文件引用」校验面自测。

方案：`docs/plans/plan-doc-sync-file-ref-gate-2026-10-01.md`。

本套用例的存在意义是防「静默失效」：判定谓词一旦被改坏，检测面会悄然归零而 CI 依旧全绿。
因此除了钉住真实树 0 违规，还必须钉住「构造出坏引用一定能报错」与「故意不校 CHANGELOG」。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_gate():
    spec = importlib.util.spec_from_file_location(
        "check_doc_sync", REPO_ROOT / "scripts" / "check_doc_sync.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_doc_sync = _load_gate()


@pytest.fixture()
def errors():
    """隔离模块级 ERRORS 累加器，避免污染同进程的其他校验。"""
    saved = list(_doc_sync.ERRORS)
    _doc_sync.ERRORS.clear()
    try:
        yield _doc_sync.ERRORS
    finally:
        _doc_sync.ERRORS[:] = saved


def test_real_tree_has_no_dangling_file_refs(errors):
    """真实树必须 0 违规（本 PR 修掉的 ARCHITECTURE.md:91 即由此钉住）。"""
    _doc_sync.check_doc_file_refs()
    assert errors == []


def test_dangling_file_ref_is_flagged(errors, tmp_path):
    """非空洞性自证：构造一个不存在的引用，谓词命中后必须产生错误。"""
    (tmp_path / "AGENTS.md").write_text(
        "详见 `docs/nope-missing.md`。\n", encoding="utf-8"
    )
    _doc_sync.check_doc_file_refs(root=tmp_path, docs=("AGENTS.md",))
    assert len(errors) == 1
    assert "AGENTS.md:1" in errors[0]
    assert "docs/nope-missing.md" in errors[0]


def test_existing_file_ref_passes(errors, tmp_path):
    # 引用项必须按 root 解析（而非真实仓根），故在被测目录下真建一个文件
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "gate.py").write_text("", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text(
        "详见 `scripts/gate.py`。\n", encoding="utf-8"
    )
    _doc_sync.check_doc_file_refs(root=tmp_path, docs=("AGENTS.md",))
    assert errors == []


@pytest.mark.parametrize(
    "text",
    [
        "docs/plans/plan-doc-sync-file-ref-gate-2026-10-01.md",
        "scripts/check_doc_sync.py",
        "applications/agent_server/main.py",
        ".github/workflows/agent-platform-ci.yml",
        "docs/operations/deployment.md#L10",  # 锚点应被剥掉后仍判定
    ],
)
def test_predicate_accepts_repo_file_refs(text):
    assert _doc_sync.is_doc_file_ref(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "applications/agent_server/",          # 目录引用 → 交目录校验面
        "applications/*/pyproject.toml",       # 通配符
        "<改动目录>/tests",                     # 占位符
        "uv run pytest tests -q",              # 命令片段（含空格）
        "agent_core.guardrails.fs",            # 模块路径，非仓内路径
        "README.md",                           # 无顶层前缀
        "http://example.com/docs/a.md",        # 外链
        "docs/plan-f-single-runtime-multi-planner",  # 无扩展名
    ],
)
def test_predicate_rejects_non_file_refs(text):
    assert _doc_sync.is_doc_file_ref(text) is False


def test_changelog_is_deliberately_out_of_scope():
    """CHANGELOG 是 append-only 历史快照，故意不进校验面。

    历史条目所指文件后来多被移动/重命名（实测 24 条），纳入即上线一片红，
    门禁会被当噪音关掉——比不校验更糟。改动此断言前请先读方案 §1。
    """
    assert "CHANGELOG.md" not in _doc_sync.DOC_FILE_REF_DOCS
    assert set(_doc_sync.DOC_FILE_REF_DOCS) == {"AGENTS.md", "ARCHITECTURE.md", "README.md"}
