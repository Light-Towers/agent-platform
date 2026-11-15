# -*- coding: utf-8 -*-
"""1b 判据与守卫的反证用例（方案 §6 R3/R10 + AGENTS.md 硬规矩 #8）。

四条线各自带「合成违规能咬 + 真面参与判决」：
- P15 窄门禁（棘轮基线）：现状零违规、新签发面必红、基线缺位必红、扫描瞎必红；
- P16 不接线机检：现状零违规、真接线必红、透传不误报、装配面缺失必红；
- 两齿都进 ``main()`` 判决（monkeypatch 成违规 ⇒ rc=1）；
- ``require_feature`` 本体：admin 放行 / viewer 403 且 feature 只进 details /
  未断言调用方按 viewer 兜底 / HTTP 级 403 且零转发 / 读面显式放行。
"""

from __future__ import annotations

import ast
import importlib.util
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from agent_core.guardrails.app_factory import build_api_app
from agent_core.guardrails.errors import AppError
from agent_runtime.workspace_registry import bind_role_context, reset_role_context
from agent_server.api import auth
from agent_server.api.auth import CODE_FEATURE_FORBIDDEN, require_feature
from fastapi.testclient import TestClient

_ROOT = Path(__file__).resolve().parents[2]


def _load_script(name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(name, _ROOT / relative_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


lint = _load_script("lint_architecture_role_gates", "scripts/lint_architecture.py")

_SIGN_SRC = (
    "from agent_core.internal_header import sign_internal_header\n"
    'value = sign_internal_header("t")\n'
)
_ROGUE_SRC = (
    "from agent_core.internal_header import sign_internal_header\n"
    'value = sign_internal_header("rogue")\n'
)
_PASSTHROUGH_SRC = (
    "def execute(caller_permissions=None):\n"
    "    validator.validate(graph, caller_permissions=caller_permissions)\n"
)
_WIRING_SRC = (
    "def assemble():\n"
    "    discover(registry, caller_permissions=frozenset({'admin'}))\n"
)


def _write(tree: Path, rel: str, text: str) -> None:
    path = tree / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _baseline_tree(tree: Path) -> None:
    """铺满基线：只铺要测的两处，其余必检位得到的是「缺失」而不是「真被判过」。

    与 ``tests/governance/test_otel_extras_gate.py:55-71`` 同一条纪律。
    """
    for rel in lint._SIGN_SITE_ALLOWED:
        _write(tree, rel, _SIGN_SRC)


def _wiring_scope_tree(tree: Path) -> None:
    for rel in lint._NO_WIRING_SCOPE:
        _write(tree, rel, _PASSTHROUGH_SRC)


# --- P15 ---------------------------------------------------------------------

def test_p15_current_tree_is_clean_and_really_judged():
    """真树零违规 + 真面参与判决（不是「扫不到对象所以绿」）。"""
    scanned, hits, found, errors = lint._sign_site_scan()
    assert scanned > 0 and hits > 0
    assert errors == []
    assert set(found) == set(lint._SIGN_SITE_ALLOWED), "现网仓必须真被这条齿判过"
    assert lint.check_internal_header_sign_sites() == []


def test_p15_flags_new_sign_site(tmp_path, monkeypatch):
    """合成违规能咬：基线外新增一个签发面 ⇒ 恰好一条具名违规。"""
    _baseline_tree(tmp_path)
    _write(tmp_path, "applications/demo/rogue_client.py", _ROGUE_SRC)
    monkeypatch.setattr(lint, "ROOT", tmp_path)
    violations = lint.check_internal_header_sign_sites()
    assert len(violations) == 1
    assert "rogue_client.py" in violations[0]


def test_p15_missing_baseline_bit_is_red(tmp_path, monkeypatch):
    """变异：删掉一个必检签发位 ⇒ 正向判据击中（显式清单是下限）。"""
    _baseline_tree(tmp_path)
    (tmp_path / sorted(lint._SIGN_SITE_ALLOWED)[0]).unlink()
    monkeypatch.setattr(lint, "ROOT", tmp_path)
    violations = lint.check_internal_header_sign_sites()
    assert any("必检签发位缺失" in v for v in violations)


def test_p15_unparsable_file_is_fail_closed(tmp_path, monkeypatch):
    """变异：解析不出 ⇒ 报红，不静默放行。"""
    _baseline_tree(tmp_path)
    _write(tmp_path, "applications/demo/broken.py", "def f(:\n")
    monkeypatch.setattr(lint, "ROOT", tmp_path)
    violations = lint.check_internal_header_sign_sites()
    assert any("broken.py" in v and "无法解析" in v for v in violations)


def test_p15_empty_scan_reports_unparsed(tmp_path, monkeypatch):
    """硬规矩 #7/#8：扫描面为零命中时不得默默报绿。"""
    _write(tmp_path, "applications/demo/plain.py", "x = 1\n")
    monkeypatch.setattr(lint, "ROOT", tmp_path)
    violations = lint.check_internal_header_sign_sites()
    assert any("<<< SIGN-SITE-UNPARSED" in v for v in violations)


# --- P16 ---------------------------------------------------------------------

def test_p16_current_tree_is_clean_and_really_judged():
    """真树零违规，且三个装配面都真实存在（不靠「文件不存在所以绿」）。"""
    for rel in lint._NO_WIRING_SCOPE:
        assert (_ROOT / rel).is_file()
    assert lint.check_skill_permission_no_wiring() == []


def test_p16_flags_real_wiring(tmp_path, monkeypatch):
    """合成违规能咬：装配层传入权限集 ⇒ 具名违规。"""
    _wiring_scope_tree(tmp_path)
    _write(tmp_path, lint._NO_WIRING_SCOPE[0], _WIRING_SRC)
    monkeypatch.setattr(lint, "ROOT", tmp_path)
    violations = lint.check_skill_permission_no_wiring()
    assert len(violations) == 1
    assert "caller_permissions" in violations[0]


def test_p16_passthrough_shape_is_not_wiring():
    """F19 在册的透传形状（同名形参 / 显式 None）不得误报；字面集合要报。"""
    allowed = ast.parse(_PASSTHROUGH_SRC + "call(None, permissions=None)\n")
    assert lint._permission_wiring_lines(allowed) == []
    bad = ast.parse(_WIRING_SRC)
    assert lint._permission_wiring_lines(bad) == [(2, "caller_permissions")]


def test_p16_missing_scope_reports_unparsed(tmp_path, monkeypatch):
    """装配面缺失 ⇒ fail-closed 标记，不是默默报绿。"""
    _write(tmp_path, lint._NO_WIRING_SCOPE[0], _PASSTHROUGH_SRC)
    monkeypatch.setattr(lint, "ROOT", tmp_path)
    violations = lint.check_skill_permission_no_wiring()
    assert any("<<< NO-WIRING-UNPARSED" in v for v in violations)


# --- 两齿真进 main() 判决（改判据自身前提 ⇒ 守卫用例报红）-----------------------

@pytest.mark.parametrize(
    "check_name,marker",
    [
        ("check_internal_header_sign_sites", "P15"),
        ("check_skill_permission_no_wiring", "P16"),
    ],
)
def test_new_gates_participate_in_main_decision(monkeypatch, capsys, check_name, marker):
    monkeypatch.setattr(lint, check_name, lambda: ["synthetic violation"])
    assert lint.main() == 1
    out = capsys.readouterr().out
    assert marker in out and "synthetic violation" in out


# --- require_feature 本体（R3 / R10 / D10）------------------------------------

def test_require_feature_admin_allowed():
    token = bind_role_context("admin")
    try:
        for code in (
            "chat.run", "session.history", "sql.train",
            "execution.control", "human_task.decide",
        ):
            require_feature(code)()
    finally:
        reset_role_context(token)


def test_require_feature_viewer_denied_and_feature_only_in_details():
    token = bind_role_context("viewer")
    try:
        with pytest.raises(AppError) as exc:
            require_feature("sql.train")()
    finally:
        reset_role_context(token)
    err = exc.value
    assert err.status_code == 403
    assert err.code == CODE_FEATURE_FORBIDDEN == "FORBIDDEN_FEATURE"
    assert err.details == {"feature": "sql.train"}
    assert "sql.train" not in err.msg, "D10：feature 码不得进 msg（能力清单不外泄）"


def test_require_feature_unasserted_defaults_to_viewer():
    """P8 (a)：无断言调用方 = viewer ⇒ chat.run 放行、写面 403（R10 行为可断言）。"""
    token = bind_role_context(None)
    try:
        require_feature("chat.run")()
        with pytest.raises(AppError) as exc:
            require_feature("sql.train")()
    finally:
        reset_role_context(token)
    assert exc.value.status_code == 403


def test_guards_are_single_dependency_across_14_endpoints():
    """14 处逐端点挂载；端点文件里不得出现第二份 inline 判定。"""
    base = _ROOT / "applications/agent_server/api"
    expected = {
        "query_router.py": 1,
        "session_router.py": 2,
        "sql_router.py": 1,
        "control.py": 8,
        "human_task.py": 2,
    }
    for name, count in expected.items():
        text = (base / name).read_text(encoding="utf-8")
        assert len(re.findall(r"Depends\(require_feature\(", text)) == count, name
        assert "has_feature(" not in text, f"{name} 不得写第二份 inline 判定"


def _test_app(router, monkeypatch):
    """最小生产形 app：统一错误信封已装，静态 API_KEY 闸门放行。"""
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.setattr(auth, "get_settings", lambda: SimpleNamespace(api_key=None))
    app = build_api_app()
    app.include_router(router)
    return app


def test_http_viewer_sql_train_is_403_and_forwards_nothing(monkeypatch):
    """R3：viewer 打写面 ⇒ 403 统一信封，且一行都不落（不是先写后回滚）。"""
    from agent_server.api.sql_router import router as sql_router

    app = _test_app(sql_router, monkeypatch)
    token = bind_role_context("viewer")
    try:
        with patch("httpx.AsyncClient") as client_cls:
            resp = TestClient(app).post("/sql/train", json={"ddl": "CREATE TABLE t (id INT)"})
    finally:
        reset_role_context(token)
    assert resp.status_code == 403, resp.text
    assert resp.json()["code"] == CODE_FEATURE_FORBIDDEN
    assert resp.json()["details"] == {"feature": "sql.train"}
    assert client_cls.call_count == 0, "守卫在依赖阶段拦下，零转发"


def test_http_admin_sql_train_passes_guard(monkeypatch):
    """admin 不被守卫拦：落到函数体的既有 503（URL 未配），不是 403。"""
    from agent_server.api.sql_router import router as sql_router

    app = _test_app(sql_router, monkeypatch)
    monkeypatch.setattr(
        "agent_server.api.sql_router.get_settings",
        lambda: SimpleNamespace(nl2sql_service_url="", default_tenant_id="t"),
    )
    token = bind_role_context("admin")
    try:
        resp = TestClient(app).post("/sql/train", json={"ddl": "CREATE TABLE t (id INT)"})
    finally:
        reset_role_context(token)
    assert resp.status_code == 503, resp.text
    assert resp.json().get("code") != CODE_FEATURE_FORBIDDEN


def test_http_human_task_read_faces_are_explicitly_unguarded(monkeypatch):
    """§4:104 只给两个 POST 分配 feature：两个 GET 读面 viewer 也放行（显式断言，非「没测」）。"""
    from agent_server.api.human_task import router as human_task_router

    app = _test_app(human_task_router, monkeypatch)
    token = bind_role_context("viewer")
    try:
        detail = TestClient(app).get("/api/human-tasks/task/no-such-task")
        listing = TestClient(app).get("/api/human-tasks/exec-1")
    finally:
        reset_role_context(token)
    # 未配置 store ⇒ 503，而不是 403：证明读面确实未挂守卫。
    assert detail.status_code == 503 and listing.status_code == 503
    assert detail.json().get("code") != CODE_FEATURE_FORBIDDEN
    assert listing.json().get("code") != CODE_FEATURE_FORBIDDEN
