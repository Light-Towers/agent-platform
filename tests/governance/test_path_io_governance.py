"""A 类路径横切（CodeQL ``py/path-injection``）的治理测试：P7 门禁。

对应 Batch 3 的「第③层强制门禁」：
- P7-1 白名单外禁手写 ``is_relative_to``（containment 只允许 kernel ``guardrails.fs`` 一处）；
- P7-2 api 层文件 I/O 出口必须经 ``safe_join`` / ``resolve_within``。

脚本非包内模块，按文件路径加载（与 ``test_thread_identity_migration.py`` 同法）。
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


lint = _load_script("lint_architecture_p7", "scripts/lint_architecture.py")


# ---------------------------------------------------------------------------
# P7-1 单行判定
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        "if not abs_path.is_relative_to(output_abs):",
        "assert candidate.is_relative_to( root )",
        "return target.is_relative_to(base) and target.exists()",
    ],
)
def test_p7_1_flags_manual_containment(line):
    assert lint._is_manual_containment_line(line.strip()) is True


@pytest.mark.parametrize(
    "line",
    [
        "# 历史实现：if not abs_path.is_relative_to(output_abs): raise ...",
        "abs_path = resolve_within(output_dir, path)",
        "if not name.startswith('session_'):",
    ],
)
def test_p7_1_allows_legitimate_lines(line):
    assert lint._is_manual_containment_line(line.strip()) is False


# ---------------------------------------------------------------------------
# P7-2 文件粒度判定
# ---------------------------------------------------------------------------


def test_p7_2_flags_file_io_without_kernel_guard():
    text = (
        "from fastapi.responses import FileResponse\n\n\n"
        "@app.get('/api/download')\n"
        "async def download(path: str):\n"
        "    return FileResponse(Path(path))\n"
    )
    assert lint._api_io_violation(text) is not None


@pytest.mark.parametrize(
    "helper",
    ["safe_join", "resolve_within"],
)
def test_p7_2_allows_file_io_with_kernel_guard(helper):
    text = (
        "from fastapi.responses import FileResponse\n\n\n"
        "async def download(path: str):\n"
        f"    abs_path = {helper}(output_dir, path)\n"
        "    return FileResponse(abs_path)\n"
    )
    assert lint._api_io_violation(text) is None


def test_p7_2_allows_io_marker_appearing_only_in_comment():
    """仅注释里引用了违规写法（无真实 I/O 行）不该报——避免文档/注释误伤。"""
    text = "# 例：return FileResponse(path) 属于违规写法\nasync def health():\n    return {'ok': True}\n"
    assert lint._api_io_violation(text) is None


def test_p7_2_ignores_files_without_io_markers():
    assert lint._api_io_violation("async def health():\n    return {'ok': True}\n") is None


# ---------------------------------------------------------------------------
# 当前树零违规 + 端到端扫描面
# ---------------------------------------------------------------------------


def test_p7_current_tree_has_zero_violations():
    """federation 4 个文件端点的散点 containment 必须已收敛到 kernel helper。"""
    assert lint.check_manual_path_containment() == []
    assert lint.check_api_layer_path_io() == []


def test_p7_scan_flags_probes_and_spares_whitelist(tmp_path, monkeypatch):
    """埋探针验证判定面：白名单内放行、越界站点各报一条。"""
    kernel_fs = tmp_path / "packages/agent-core/agent_core/guardrails/fs.py"
    kernel_fs.parent.mkdir(parents=True)
    kernel_fs.write_text(
        "def _ensure_within(root, candidate):\n"
        "    if candidate != root and not candidate.is_relative_to(root):\n"
        "        raise ValueError()\n",
        encoding="utf-8",
    )
    api_dir = tmp_path / "applications/foo/api"
    api_dir.mkdir(parents=True)
    (api_dir / "__init__.py").write_text("", encoding="utf-8")
    (api_dir / "manual_containment.py").write_text(
        "def check(p, base):\n    return p.is_relative_to(base)\n", encoding="utf-8"
    )
    (api_dir / "raw_io.py").write_text(
        "async def download(path):\n    return FileResponse(Path(path))\n", encoding="utf-8"
    )
    (api_dir / "guarded_io.py").write_text(
        "async def download(path):\n"
        "    abs_path = resolve_within(output_dir, path)\n"
        "    return FileResponse(abs_path)\n",
        encoding="utf-8",
    )
    # 非 api 层：P7-2 不管辖（本例无 is_relative_to，故 P7-1 也不报）
    service = tmp_path / "applications/foo/service.py"
    service.write_text("def render():\n    return FileResponse(STATIC / 'index.html')\n", encoding="utf-8")
    monkeypatch.setattr(lint, "ROOT", tmp_path)

    v1 = lint.check_manual_path_containment()
    assert len(v1) == 1
    assert "manual_containment.py" in v1[0]

    v2 = lint.check_api_layer_path_io()
    assert len(v2) == 1
    assert "raw_io.py" in v2[0]
    assert "guarded_io.py" not in v2[0]
