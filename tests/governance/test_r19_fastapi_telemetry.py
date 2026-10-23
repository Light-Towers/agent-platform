"""R19 门禁治理测试：非白名单 FastAPI() 构造必须显式声明 telemetry。

对应 GitHub issue #23 / TODO §0.2 C 组第 4 条的 remediation
（`docs/plans/plan-r19-fastapi-native-telemetry-2026-10-19.md`）：

- FastAPI ≥0.142 原生 telemetry 默认开启 ⇒ 与 kernel ``TracingMiddleware``
  对同一请求各建一个同名 SERVER span（互为兄弟），且框架自行
  ``set_tracer_provider()`` 会覆盖 kernel ``init_tracing`` 装配的 provider；
- 默认取最小改动：``build_api_app`` 内 ``setdefault`` 关原生 tracing
  （其行为由 agent-core spy 用例钉住），其余构造点显式传
  ``telemetry={"tracing": False}``；
- 本门禁是第二层保险：**AST 级**判定（多行构造调用不得漏判），作用域
  ``applications/`` + ``packages/`` + ``scripts/``（P2 只扫 applications/，
  ``scripts/opencode_gateway.py`` 曾是盲区），tests/ 排除同 P2。

脚本非包内模块，按文件路径加载（与 ``test_exception_echo_governance.py`` 同法）。
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


lint = _load_script("lint_architecture_r19", "scripts/lint_architecture.py")


# ---------------------------------------------------------------------------
# AST 谓词：识别 FastAPI 构造调用（Name 与 Attribute 两形），不误伤其它调用
# ---------------------------------------------------------------------------


def _parse_call(src: str):
    import ast

    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            return node
    raise AssertionError("no call found")


@pytest.mark.parametrize(
    "src",
    [
        "FastAPI()",
        "FastAPI(title='x')",
        "fastapi.FastAPI()",
        "fastapi.FastAPI(\n    title='x',\n)",
    ],
)
def test_is_fastapi_call_positive(src):
    assert lint._is_fastapi_call(_parse_call(src)) is True


@pytest.mark.parametrize(
    "src",
    [
        "FastAPIMiddleware()",
        "build_api_app()",
        "create_app()",
        "APIRouter()",
        "app.get('/x')",
        "TelemetryMiddleware(app)",
    ],
)
def test_is_fastapi_call_negative(src):
    assert lint._is_fastapi_call(_parse_call(src)) is False


def test_telemetry_keyword_detection():
    """缺 telemetry keyword 即判违规；显式声明（任意值）即放行。"""
    import ast

    bare = ast.parse("FastAPI(title='x')").body[0].value
    assert not any(kw.arg == "telemetry" for kw in bare.keywords)
    off = ast.parse('FastAPI(title="x", telemetry={"tracing": False})').body[0].value
    assert any(kw.arg == "telemetry" for kw in off.keywords)


# ---------------------------------------------------------------------------
# 当前树零违规 + 白名单是刻意登记的两项
# ---------------------------------------------------------------------------


def test_r19_current_tree_has_zero_violations():
    assert lint.check_fastapi_telemetry() == []


def test_r19_whitelist_is_deliberate():
    """白名单恰两项、各有据：warehouse_mock=dev fixture；app_factory=工厂本体
    （调用点无字面 keyword，行为由 agent-core spy 用例钉住）。"""
    assert lint._R19_TELEMETRY_WHITELIST == (
        "applications/exhibition-agent/exhibition_agent/mock_server/warehouse_mock.py",
        "packages/agent-core/agent_core/guardrails/app_factory.py",
    )


def test_r19_scope_covers_applications_packages_scripts():
    """作用域必须覆盖三面（opencode_gateway 在 scripts/，曾是 P2 盲区）。"""
    assert lint._R19_SCOPE_PREFIXES == ("applications/", "packages/", "scripts/")


# ---------------------------------------------------------------------------
# 探针：判定面埋点（含"剥掉防线必红"自证）
# ---------------------------------------------------------------------------


def test_r19_scan_flags_bare_and_spares_compliant(tmp_path, monkeypatch):
    api_dir = tmp_path / "applications/foo"
    api_dir.mkdir(parents=True)
    # 违规 1：裸构造（单行）
    (api_dir / "bare.py").write_text("app = FastAPI(title='bare')\n", encoding="utf-8")
    # 违规 2：多行构造（行级正则的经典漏判面，AST 必须抓到）
    (api_dir / "multiline.py").write_text(
        "app = FastAPI(\n    title='multi',\n    description='x',\n)\n", encoding="utf-8"
    )
    # 违规 3：Attribute 形态 fastapi.FastAPI()
    (api_dir / "attr.py").write_text(
        "import fastapi\napp = fastapi.FastAPI()\n", encoding="utf-8"
    )
    # 合规：显式声明 telemetry
    (api_dir / "compliant.py").write_text(
        'app = FastAPI(title="ok", telemetry={"tracing": False})\n', encoding="utf-8"
    )
    # 合规：白名单文件（warehouse_mock 同形）
    wl_dir = tmp_path / "applications/exhibition-agent/exhibition_agent/mock_server"
    wl_dir.mkdir(parents=True)
    (wl_dir / "warehouse_mock.py").write_text(
        'app = FastAPI(title="warehouse-mock")\n', encoding="utf-8"
    )
    # 合规：白名单文件（app_factory 同形）
    pkg_dir = tmp_path / "packages/agent-core/agent_core/guardrails"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "app_factory.py").write_text(
        "def build_api_app(**kw):\n    return FastAPI(**kw)\n", encoding="utf-8"
    )
    # 合规：tests/ 在排除面内
    tests_dir = tmp_path / "applications/foo/tests"
    tests_dir.mkdir()
    (tests_dir / "test_probe.py").write_text("app = FastAPI()\n", encoding="utf-8")
    # 合规：scripts/ 面显式声明
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "gateway.py").write_text(
        'app = FastAPI(title="gw", telemetry={"tracing": False})\n', encoding="utf-8"
    )
    # 违规 4：scripts/ 面裸构造（该面曾被 P2 盲区漏掉）
    (scripts_dir / "bad_gateway.py").write_text("app = FastAPI()\n", encoding="utf-8")

    monkeypatch.setattr(lint, "ROOT", tmp_path)
    violations = lint.check_fastapi_telemetry()

    flagged = {v.split(":")[0] for v in violations}
    assert flagged == {
        "applications/foo/bare.py",
        "applications/foo/multiline.py",
        "applications/foo/attr.py",
        "scripts/bad_gateway.py",
    }, violations


def test_r19_scan_fails_closed_on_unparseable_file(tmp_path, monkeypatch):
    """读不到/解析不了不等于通过（fail-closed，与 P12 同口径）。"""
    bad = tmp_path / "applications/foo"
    bad.mkdir(parents=True)
    (bad / "broken.py").write_text("def broken(:\n", encoding="utf-8")

    monkeypatch.setattr(lint, "ROOT", tmp_path)
    violations = lint.check_fastapi_telemetry()

    assert len(violations) == 1
    assert "无法解析" in violations[0]


def test_r19_removing_factory_default_bites_unit_level():
    """「剥掉防线必红」的工厂层自证：app_factory 源码必须含 telemetry 默认值。

    门禁对 app_factory 是白名单（调用点无字面 keyword），工厂层防线由本断言 +
    agent-core spy 用例（test_build_api_app_defaults_native_telemetry_off）双钉：
    删掉 setdefault 行 ⇒ spy 用例红；改坏调用形状 ⇒ 本断言红。
    """
    factory = _ROOT / "packages/agent-core/agent_core/guardrails/app_factory.py"
    src = factory.read_text(encoding="utf-8")
    assert 'fastapi_kwargs.setdefault("telemetry", {"tracing": False})' in src
