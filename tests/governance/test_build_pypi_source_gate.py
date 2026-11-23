"""P18 构建源门禁的治理测试：种植违规能咬 + 真面参与判决。

对应 AGENTS.md「新加判据必须同批带两件事」：① 合成违规（非零）② 真面参与判决。
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


lint = _load_script("lint_architecture_p18", "scripts/lint_architecture.py")


# ① 合成违规必须能咬
@pytest.mark.parametrize("line", [
    "ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple",
    'RUN pip config set global.trusted-host pypi.tuna.tsinghua.edu.cn',
    "ENV PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple",
])
def test_p18_flags_slow_source(line):
    assert lint._dockerfile_source_violation("Dockerfile", line) is not None


def test_p18_comment_not_counted():
    # 注释里的源名不算违规（真面里大量注释描述历史慢源）
    assert lint._dockerfile_source_violation("Dockerfile", "# 默认清华源 xxx") is None


def test_p18_fast_source_ok():
    assert lint._dockerfile_source_violation(
        "Dockerfile", "ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/"
    ) is None


# ② 真面参与判决：3 个真实 Dockerfile 必须过
@pytest.mark.parametrize("rel", [
    "Dockerfile",
    "Dockerfile.nl2sql-service",
    "applications/knowledge-service/Dockerfile",
])
def test_p18_true_face_passes(rel):
    text = (_ROOT / rel).read_text(encoding="utf-8")
    assert lint._dockerfile_source_violation(rel, text) is None


def test_p18_full_scan_green():
    assert lint.check_build_pypi_source() == []
