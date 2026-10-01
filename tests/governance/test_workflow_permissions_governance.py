"""P11 workflow 最小权限门禁的治理测试（CodeQL `actions/missing-workflow-permissions`）。

对应 B7d 方案 §7.2 的第③层「强制门禁」：根 `.github/workflows/*.yml` 必须显式声明
顶层 ``permissions:`` 块。只补被点名的 workflow 属散点式做法，本门禁让未来的漏接在
CI 失败而非靠自觉。

判据口径（为何只认顶层块）：顶层声明由构造保证覆盖该 workflow 全部 job；job 级声明
易漏且不可核，单独出现不视为满足。

脚本非包内模块，按文件路径加载（与 P6/P6-2 用例同一做法）。
"""

import importlib.util
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]


def _load_script(module_name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(module_name, _ROOT / relative_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


lint = _load_script("lint_architecture", "scripts/lint_architecture.py")

_GOOD = "name: demo\non: push\npermissions:\n  contents: read\n\njobs:\n  a:\n    runs-on: ubuntu-latest\n"


# ---------------------------------------------------------------------------
# 单文件判定：正反例
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,needle",
    [
        # 完全没声明（#48 的真实形状：ha-assembly.yml 合流时漏接）
        ("name: demo\non: push\n\njobs:\n  a:\n    runs-on: ubuntu-latest\n", "缺顶层"),
        # 只写在 job 级：顶层缺失，回落组织默认读写，仍不满足
        (
            "name: demo\njobs:\n  a:\n    permissions:\n      contents: read\n",
            "缺顶层",
        ),
        # 顶层 write-all：等于没限权
        ("name: demo\npermissions: write-all\njobs:\n  a:\n", "write-all"),
        # 顶层空块：语法在但一个作用域都没开
        ("name: demo\npermissions:\n\njobs:\n  a:\n", "空块"),
    ],
)
def test_p11_flags_missing_or_unsafe_permissions(text, needle):
    reason = lint._workflow_permission_violation(text)
    assert reason is not None and needle in reason


@pytest.mark.parametrize(
    "text",
    [
        _GOOD,
        # 多作用域显式列举
        "name: demo\npermissions:\n  contents: read\n  actions: read\njobs:\n  a:\n",
        # 顶层 read-all 是合法的最小姿态（与 write-all 相对）
        "name: demo\npermissions: read-all\njobs:\n  a:\n",
        # 顶层收紧 + 个别 job 提升（仍不得省略顶层块）
        "name: demo\npermissions:\n  contents: read\njobs:\n"
        "  a:\n    permissions:\n      pull-requests: write\n",
        # 注释行不得被当成 permissions 声明（已有独立反例，这里只验合法形态）
        "name: demo\npermissions:\n  contents: read\n# 某 job 单独提升\njobs:\n  a:\n",
    ],
)
def test_p11_allows_legitimate_shapes(text):
    assert lint._workflow_permission_violation(text) is None


def test_p11_comment_only_block_is_not_a_declaration():
    """注释掉的 ``# permissions:`` 不算声明，否则门禁形同虚设。"""
    assert lint._workflow_permission_violation(
        "name: demo\n# permissions:\n#   contents: read\njobs:\n  a:\n"
    ) is not None
    # 注释后跟真实声明仍然合规（剥注释不得误删正文）
    assert lint._workflow_permission_violation(
        "name: demo\n# 最小权限\npermissions:\n  contents: read\njobs:\n  a:\n"
    ) is None


# ---------------------------------------------------------------------------
# 当前树：零违规 + 扫描面 + fail-closed
# ---------------------------------------------------------------------------


def test_p11_current_tree_has_zero_violations():
    assert lint.check_workflow_permissions() == []


def test_p11_scan_flags_bad_and_spares_good(tmp_path, monkeypatch):
    """端到端扫描面：往临时根埋一坏一好，只有坏的被报。"""
    wf_dir = tmp_path / ".github" / "workflows"
    wf_dir.mkdir(parents=True)
    (wf_dir / "bad.yml").write_text(
        "name: bad\non: push\njobs:\n  a:\n    runs-on: ubuntu-latest\n", encoding="utf-8"
    )
    (wf_dir / "good.yml").write_text(_GOOD, encoding="utf-8")
    monkeypatch.setattr(lint, "ROOT", tmp_path)

    violations = lint.check_workflow_permissions()
    assert len(violations) == 1
    assert "bad.yml" in violations[0]


def test_p11_is_fail_closed_when_workflow_dir_absent(tmp_path, monkeypatch):
    """目录被搬走不得静默放行，否则门禁退化为约定。"""
    monkeypatch.setattr(lint, "ROOT", tmp_path)
    assert lint.check_workflow_permissions() != []


@pytest.mark.parametrize(
    "rel",
    sorted(p.relative_to(_ROOT).as_posix() for p in (_ROOT / ".github" / "workflows").glob("*.y*ml")),
)
def test_p11_the_permissions_block_is_what_keeps_each_workflow_green(rel):
    """回归锁：把任一真实 workflow 的顶层 permissions 块删掉，必须立刻被判违规。

    这排除了「门禁只是恰好没命中」的假通过——证明每个 workflow 的合规确实由该块撑着。
    """
    text = (_ROOT / rel).read_text(encoding="utf-8")
    assert lint._workflow_permission_violation(text) is None  # 现状合规

    lines = text.splitlines(keepends=True)
    idx = next(i for i, ln in enumerate(lines) if ln.startswith("permissions:"))
    end = idx + 1
    while end < len(lines) and lines[end].startswith((" ", "\t", "#")):
        end += 1
    stripped = "".join(lines[:idx] + lines[end:])
    assert stripped != text, f"{rel}: 未剥掉任何行，删除逻辑失效"
    assert lint._workflow_permission_violation(stripped) is not None
