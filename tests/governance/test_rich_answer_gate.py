"""P17 富回答单一转换门禁的治理测试：种植违规能咬 + 真面参与判决。

对应 AGENTS.md「新加判据必须同批带两件事」：① 合成违规（非零）② 真面参与判决。
只有 ``assert check() == []`` 不算证据——本文件同时喂反例与真面源码。
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


lint = _load_script("lint_architecture_p17", "scripts/lint_architecture.py")


# ---------------------------------------------------------------------------
# ① 合成违规：判定必须能咬（非零）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("rel,code", [
    ("applications/agent_server/api/query_router.py", "img = ImageRef(url='http://minio/a.png')"),
    ("applications/agent_server/subagents/rag.py", "return ImageRef(url=u)"),
    ("applications/agent_server/other.py", "x = ImageRef(url=u)"),
])
def test_p17_flags_image_ref_outside_adapter(rel, code):
    assert lint._rich_conversion_violation(rel, code) is not None


def test_p17_flags_router_building_citation():
    assert lint._rich_conversion_violation(
        "applications/agent_server/api/query_router.py", "c = Citation(source=s)"
    ) is not None


def test_p17_flags_adapter_without_allowlist():
    # adapter 里有 ImageRef 构造却没调 is_allowed_image_url ⇒ 白名单被绕过
    assert lint._rich_conversion_violation(
        lint._RICH_ADAPTER_REL, "return ImageRef(url=url)"
    ) is not None


def test_p17_flags_class_definition_not_counted_as_construction():
    # 反向控制：class 定义本身不算构造，避免把契约定义文件误报成违规
    assert lint._rich_conversion_violation(
        "packages/shared-schemas/shared_schemas/rich_answer.py", "class ImageRef(BaseModel):"
    ) is None


def test_p17_test_files_skipped():
    assert lint._rich_conversion_violation(
        "packages/shared-schemas/tests/test_rich_answer.py", "ImageRef(url='x')"
    ) is None


# ---------------------------------------------------------------------------
# ② 真面参与判决：真实 adapter / router 源码必须过
# ---------------------------------------------------------------------------

def test_p17_true_face_adapter_passes():
    text = (_ROOT / lint._RICH_ADAPTER_REL).read_text(encoding="utf-8")
    assert lint._rich_conversion_violation(lint._RICH_ADAPTER_REL, text) is None


def test_p17_true_face_router_passes():
    text = (_ROOT / lint._RICH_ROUTER_REL).read_text(encoding="utf-8")
    assert lint._rich_conversion_violation(lint._RICH_ROUTER_REL, text) is None


def test_p17_full_scan_green():
    assert lint.check_rich_answer_single_conversion() == []
