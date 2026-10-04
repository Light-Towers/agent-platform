"""doc-sync 门禁「文件引用」校验面自测。

方案：`docs/plans/plan-doc-sync-file-ref-gate-2026-10-01.md`（补齐文件引用面）
　　　`docs/plans/plan-doc-sync-tracked-scope-2026-10-04.md`（存在性判定改以版本控制清单为基准）。

本套用例的存在意义是防「静默失效」：判定谓词一旦被改坏，检测面会悄然归零而 CI 依旧全绿。
因此除了钉住真实树 0 违规，还必须钉住「构造出坏引用一定能报错」与「故意不校 CHANGELOG」。

另钉住两条关于**判定基准**的不变量（第十条工具假阳性）：
- 本机存在但未入库 ⇒ 必红（不得因本机 FS 有就放行）；
- 清单取不到 ⇒ fail-closed 必红（不得静默退回 `Path.exists()`）。
"""

from __future__ import annotations

import importlib.util
import subprocess
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


def _idx(*paths: str) -> "_doc_sync.TrackedIndex":
    """显式版本控制清单（用例不依赖跑 git，也不依赖本机 FS）。"""
    return _doc_sync.TrackedIndex(list(paths), source="fixture")


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
    _doc_sync.check_doc_file_refs(
        root=tmp_path, docs=("AGENTS.md",), tracked=_idx()
    )
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
    _doc_sync.check_doc_file_refs(
        root=tmp_path, docs=("AGENTS.md",), tracked=_idx("scripts/gate.py")
    )
    assert errors == []


def test_plain_text_ref_is_deliberately_not_checked(errors, tmp_path):
    """逃生舱钉子：**无反引号普通文本**引用刻意不校（AGENTS.md 口径：本机才有、不入库的
    路径用普通文本书写，否则永远过不了「必须在版本控制清单里」）。

    钉住此行为是防「好心补全」：若将来有人把普通文本也纳入扫描，全仓 gitignored 引用会
    一夜打红，门禁被当噪音关掉——比漏报更糟。改此断言前先读 AGENTS.md「文档防漂移」。
    """
    (tmp_path / "AGENTS.md").write_text(
        "本机目录 .codeartsdoer/temp/probe/ 不入库，按口径写成普通文本；"
        "链接形式见 [x](docs/nope-missing.md)。\n",
        encoding="utf-8",
    )
    _doc_sync.check_doc_file_refs(
        root=tmp_path, docs=("AGENTS.md",), tracked=_idx()
    )
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


# ---------------------------------------------------------------------------
# 判定基准 = 版本控制清单（方案 `plan-doc-sync-tracked-scope-2026-10-04.md`）
# 以下用例钉「本机 FS 不再参与判定」。
# ---------------------------------------------------------------------------


def test_local_but_untracked_ref_is_flagged(errors, tmp_path):
    """第十条假阳性的正主：本机存在但未入库 ⇒ 必红，且措辞指名「未纳入版本控制」。

    旧实现（`Path.exists()` 基准）在这一条上放行 ⇒ 本机 rc=0 而 CI 红（PR #65 实踩）。
    """
    (tmp_path / ".codeartsdoer" / "temp").mkdir(parents=True)
    (tmp_path / "ARCHITECTURE.md").write_text(
        "原住址 `.codeartsdoer/temp/` 不是仓内路径。\n", encoding="utf-8"
    )
    _doc_sync.check_architecture_paths(base=tmp_path, tracked=_idx("scripts/gate.py"))
    assert len(errors) == 1
    assert "未纳入版本控制" in errors[0]
    assert ".codeartsdoer/temp/" in errors[0]


def test_url_with_trailing_slash_is_not_a_repo_path(errors, tmp_path):
    """尾斜杠外链 URL 不是仓内路径：旧逻辑里 http+尾斜杠会漏过 continue 落到
    存在性校验 ⇒ 必误红。钉住「http 开头一律跳过」。"""
    (tmp_path / "ARCHITECTURE.md").write_text(
        "文档站：`https://example.com/docs/`\n", encoding="utf-8"
    )
    _doc_sync.check_architecture_paths(
        base=tmp_path, tracked=_idx("scripts/gate.py")
    )
    assert errors == []


def test_tracked_ref_passes_even_if_absent_locally(errors, tmp_path):
    """判定基准是清单而非工作树：索引里有、本机被临时删掉 ⇒ 不判红（不是文档漂移）。"""
    (tmp_path / "ARCHITECTURE.md").write_text(
        "见 `scripts/gate.py`。\n", encoding="utf-8"
    )
    # 注意：**不**在 tmp_path 下真建 scripts/gate.py
    _doc_sync.check_doc_file_refs(
        root=tmp_path, docs=("ARCHITECTURE.md",), tracked=_idx("scripts/gate.py")
    )
    assert errors == []


def test_fail_closed_when_index_unavailable(errors, tmp_path, monkeypatch):
    """取不到仓内清单 ⇒ 必须报红，绝不静默退回 `Path.exists()`。"""
    monkeypatch.setattr(_doc_sync, "load_tracked_index", lambda base: None)
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "gate.py").write_text("", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("详见 `scripts/gate.py`。\n", encoding="utf-8")
    _doc_sync.check_doc_file_refs(root=tmp_path, docs=("AGENTS.md",))
    assert len(errors) == 1
    assert "fail-closed" in errors[0]


def test_fail_closed_covers_agents_and_architecture_faces(errors, tmp_path, monkeypatch):
    """方案 §5.3：fail-closed 自证须钉满**三条面**——本用例补 agents 表格面与 arch 目录面
    （doc-refs 面已由上一用例钉住），堵住「只在一条面上 fail-closed、其余面静默放行」的缝。"""
    monkeypatch.setattr(_doc_sync, "load_tracked_index", lambda base: None)
    (tmp_path / "AGENTS.md").write_text(
        "| 目录 | 定位 |\n|------|------|\n| `applications/agent_server/` | 平台 |\n",
        encoding="utf-8",
    )
    (tmp_path / "ARCHITECTURE.md").write_text(
        "## 目录\n\n- `applications/agent_server/` 单进程 Supervisor 平台\n"
        "- 外链尾斜杠不判：`https://example.com/docs/`\n",
        encoding="utf-8",
    )
    _doc_sync.check_agents_md_paths(base=tmp_path)
    _doc_sync.check_architecture_paths(base=tmp_path)
    assert len(errors) == 2
    assert all("fail-closed" in e for e in errors)
    assert any(e.startswith("AGENTS.md:") for e in errors)
    assert any(e.startswith("ARCHITECTURE.md:") for e in errors)


def test_real_tree_all_faces_pass_under_git_index(errors):
    """真实树在 **git 索引基准**下三条面均 0 违规（钉「修完不误报」，也钉索引真的取到了）。"""
    idx = _doc_sync.resolve_tracked(REPO_ROOT)
    assert idx is not None
    assert idx.source.startswith("git ls-files @")
    assert len(idx.files) > 500  # 索引非空（空集会把上面两条钉用例变成假命题）
    _doc_sync.check_agents_md_paths()
    _doc_sync.check_architecture_paths()
    _doc_sync.check_doc_file_refs()
    assert errors == []


@pytest.mark.parametrize(
    "ref,expect",
    [
        ("scripts/evidence/README.md", True),   # 精确文件
        ("scripts/evidence/", True),            # 目录引用（带尾斜杠）
        ("scripts/evidence", True),             # 目录引用（不带尾斜杠）
        ("scripts/", True),                     # 中间层目录
        ("./scripts/evidence/", True),          # `./` 前缀须被规范化
        ("scripts\\evidence\\", True),          # 反斜杠（Windows 手写习惯）须被规范化
        ("docs/", False),                       # 清单里没有的目录
        ("scripts/nope.py", False),             # 清单里没有的文件
        ("", False),
        ("/", False),                           # 去斜杠后为空
    ],
)
def test_tracked_index_has_semantics(ref, expect):
    assert _idx("scripts/evidence/README.md").has(ref) is expect


def test_load_tracked_index_happy_path(tmp_path, monkeypatch):
    def _ok(*args, **kwargs):
        return subprocess.CompletedProcess(
            list(args[0]), 0, b"scripts/evidence/README.md\x00docs/a.md\x00", b""
        )

    monkeypatch.setattr(_doc_sync.subprocess, "run", _ok)
    idx = _doc_sync.load_tracked_index(tmp_path)
    assert idx is not None
    assert idx.has("scripts/evidence/README.md") is True
    assert idx.has("scripts/evidence/") is True
    assert idx.source.startswith("git ls-files @")


@pytest.mark.parametrize(
    "outcome",
    ["git_rc_nonzero", "git_missing", "undecodable_output"],
)
def test_load_tracked_index_returns_none_on_failure(tmp_path, monkeypatch, outcome):
    """git 缺席 / rc!=0 / 输出不可解 ⇒ None（而不异常、也不回退 FS）。"""
    if outcome == "git_rc_nonzero":
        def _f(*a, **k):
            return subprocess.CompletedProcess([], 128, b"", b"fatal: not a git repository")
    elif outcome == "git_missing":
        def _f(*a, **k):
            raise OSError("git not found")
    else:
        def _f(*a, **k):
            return subprocess.CompletedProcess([], 0, b"ok.py\x00\xc3\x28.py\x00", b"")

    monkeypatch.setattr(_doc_sync.subprocess, "run", _f)
    assert _doc_sync.load_tracked_index(tmp_path) is None
