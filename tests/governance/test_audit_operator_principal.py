"""P12「凭据不得当审计主体」治理测试（plan-audit-operator-principal-2026-10-03 §4.4）。

根因（**人工语义审计发现，CodeQL 未报**）：``/session/revert`` 曾把
``verify_api_key`` 的返回值（入站头**原文**）当 ``operator`` 写进 ``revert_audit``
与日志 ⇒ 部署密钥被持久化进审计痕迹。本文件守两面：

1. **行为面**：路由传给 handler 的 ``operator`` 必须是服务端断言租户，且入站密钥
   值不得出现在任何日志记录里；
2. **门禁面**：``lint_architecture.check_credential_param_escape`` 的判据正反例 +
   真实树零违规 + fail-closed + 「剥掉防线即红」的回归锁。

脚本非包内模块，按文件路径加载（与 P11/P6 用例同一做法）。
"""

import ast
import asyncio
import importlib.util
import logging
import types
from pathlib import Path

import pytest
from agent_runtime.revert import RevertHandler
from agent_runtime.workspace_registry import (
    bind_tenant_context,
    reset_tenant_context,
    server_tenant_id,
)
from agent_server.api.session_router import session_revert
from agent_server.config import get_settings
from agent_server.schemas import RevertRequest

_ROOT = Path(__file__).resolve().parents[2]

_INBOUND_KEY = "sk-INBOUND-SECRET-2f9c"


def _load_script(module_name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(module_name, _ROOT / relative_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


lint = _load_script("lint_architecture", "scripts/lint_architecture.py")


def _set_api_key(monkeypatch, key: str):
    monkeypatch.setenv("API_KEY", key)
    get_settings.cache_clear()


class _RecordingRevert:
    """替身 handler：只记录收到的 operator，不碰 checkpointer。"""

    def __init__(self) -> None:
        self.operators: list[str] = []

    async def revert(self, operator: str, session_id: str, checkpoint_id: str):
        self.operators.append(operator)
        from agent_runtime.schemas import RevertResult

        return RevertResult(
            success=True,
            session_id=session_id,
            checkpoint_id=checkpoint_id,
            context_summary="stub",
        )


def _fake_request(handler) -> types.SimpleNamespace:
    return types.SimpleNamespace(app=types.SimpleNamespace(state=types.SimpleNamespace(revert_handler=handler)))


# ---------------------------------------------------------------------------
# ① 行为面：审计主体来自服务端断言租户
# ---------------------------------------------------------------------------


def test_revert_operator_is_asserted_tenant_not_credential(monkeypatch):
    """部署级 default 分支：operator == server_tenant_id(default_tenant_id)，且不是入站密钥。"""
    _set_api_key(monkeypatch, _INBOUND_KEY)
    monkeypatch.setenv("DEFAULT_TENANT_ID", "single-tenant-x")
    get_settings.cache_clear()
    handler = _RecordingRevert()
    req = RevertRequest(session_id="s-1", checkpoint_id="c-1")

    result = asyncio.run(session_revert(req, _fake_request(handler), _auth=_INBOUND_KEY))

    assert result.session_id == "s-1"
    assert handler.operators == ["single-tenant-x"]
    assert handler.operators[0] == server_tenant_id(get_settings().default_tenant_id)
    # 凭据既不以原文、也不以任何派生形态进入审计主体
    assert handler.operators[0] != _INBOUND_KEY


def test_revert_operator_prefers_bound_tenant_context(monkeypatch):
    """请求链路已绑定租户 ⇒ ContextVar 优先于部署级 default（与 /import、/sql/train 同语义）。"""
    _set_api_key(monkeypatch, _INBOUND_KEY)
    monkeypatch.setenv("DEFAULT_TENANT_ID", "single-tenant-x")
    get_settings.cache_clear()
    handler = _RecordingRevert()
    req = RevertRequest(session_id="s-2", checkpoint_id="c-2")

    token = bind_tenant_context("acme")
    try:
        asyncio.run(session_revert(req, _fake_request(handler), _auth=_INBOUND_KEY))
    finally:
        reset_tenant_context(token)

    assert handler.operators == ["acme"]


def test_revert_call_logs_no_credential(monkeypatch, caplog):
    """整条路由调用（含鉴权依赖本体）产生的日志里，不得出现入站密钥原文。"""
    _set_api_key(monkeypatch, _INBOUND_KEY)
    from agent_server.api.auth import verify_api_key

    handler = _RecordingRevert()
    req = RevertRequest(session_id="s-3", checkpoint_id="c-3")
    with caplog.at_level(logging.DEBUG):
        authed = verify_api_key(_INBOUND_KEY)
        asyncio.run(session_revert(req, _fake_request(handler), _auth=authed))

    assert authed == _INBOUND_KEY  # 依赖本体确实返回原文（不是摘要）⇒ 更不能被当主体
    assert _INBOUND_KEY not in caplog.text
    assert handler.operators and _INBOUND_KEY not in handler.operators[0]


def test_write_audit_line_carries_asserted_identity_only(monkeypatch, caplog):
    """审计原语（内存模式 logger.info）：operator 给什么就记什么 ⇒ 上游必须给身份。

    直接调 ``_write_audit`` 而非走 ``revert()``：后者经 ``spawn_background`` 投递，
    在 ``asyncio.run`` 收尾时完成时机不确定，用它做断言会引入假失败。
    """
    _set_api_key(monkeypatch, _INBOUND_KEY)
    handler = RevertHandler(checkpointer=object(), pool=None)
    with caplog.at_level(logging.INFO, logger="agent_runtime.revert"):
        asyncio.run(handler._write_audit("acme", "s-4", "src-1", "tgt-1", "success"))

    audit = [r.getMessage() for r in caplog.records if "revert_audit" in r.getMessage()]
    assert len(audit) == 1
    assert "operator=acme" in audit[0]
    assert _INBOUND_KEY not in audit[0]


@pytest.mark.parametrize(
    "relative",
    [
        "applications/agent_server/api/session_router.py",
        "applications/agent_server/api/import_router.py",
        "applications/agent_server/api/sql_router.py",
    ],
)
def test_credential_bound_param_is_unreferenced_in_body(relative):
    """签名级守门：绑定凭据的形参在函数体内**完全不被引用**（比 P12 的「不当实参」更严）。

    这三处是 ``applications/**`` 里仅有的 ``Depends(verify_api_key)`` 站点，逐个钉死
    「闸门用完即弃」，比把名字留在作用域里再指望 lint 抓更彻底。
    """
    tree = ast.parse((_ROOT / relative).read_text(encoding="utf-8-sig"))
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        names = lint._credential_bound_params(node)
        if not names:
            continue
        for sub in ast.walk(ast.Module(body=node.body, type_ignores=[])):
            if isinstance(sub, ast.Name) and sub.id in names:
                hits.append((node.name, sub.id, sub.lineno))
    assert hits == [], f"{relative} 仍引用凭据形参：{hits}"


# ---------------------------------------------------------------------------
# ② 门禁面：P12 判据正反例
# ---------------------------------------------------------------------------


def _dep_expr(source: str) -> ast.expr:
    """取 ``def f(p=<source>)`` 里默认值的 AST 节点。"""
    fn = ast.parse(f"def f(p={source}):\n    return 1\n").body[0]
    return fn.args.defaults[0]


@pytest.mark.parametrize(
    "source,expected",
    [
        ("Depends(verify_api_key)", True),
        ("Security(verify_api_key)", True),
        ("Depends(verify_api_key())", True),  # 少写了调用括号同样把返回值带进来
        ("Depends(dependency=verify_api_key)", True),
        ("Depends(get_current_user)", False),
        ("verify_api_key", False),  # 未包 Depends：不是注入绑定
        ("Depends()", False),
        ("Security(lambda: 1)", False),
    ],
)
def test_is_credential_dep_classification(source, expected):
    assert lint._is_credential_dep(_dep_expr(source)) is expected


def test_credential_bound_params_alignment_with_other_defaults():
    """defaults 右对齐：前面有别的默认值时，仍要把凭据默认值挂到正确的形参名上。"""
    tree = ast.parse(
        "def f(a, b=1, _auth=Depends(verify_api_key), *, c=2, also=Depends(verify_api_key)):\n"
        "    return 1\n"
    )
    assert lint._credential_bound_params(tree.body[0]) == {"_auth", "also"}


def test_credential_bound_params_empty_when_no_credential_dep():
    tree = ast.parse("def f(a, b=1, _auth=Depends(get_current_user)):\n    return 1\n")
    assert lint._credential_bound_params(tree.body[0]) == set()


@pytest.mark.parametrize(
    "body,needle",
    [
        ("    handler.revert(api_key, sid)\n", "api_key"),  # 位置实参（当年真实形状）
        ("    handler.revert(operator=api_key)\n", "api_key"),  # 关键字实参
        ("    log.info('op', api_key)\n", "api_key"),  # 写日志同样算外流
        (
            "    def inner():\n        handler.revert(api_key)\n    inner()\n",
            "api_key",
        ),  # 内层闭包里传出
    ],
)
def test_p12_detects_escape_shapes(body, needle):
    fn = ast.parse(f"def f(api_key=Depends(verify_api_key)):\n{body}").body[0]
    hits = lint._credential_escape_lines(fn, lint._credential_bound_params(fn))
    assert hits and hits[0][1] == needle


def test_p12_does_not_count_the_binding_itself_as_escape():
    """默认值里的 ``Depends(verify_api_key)`` 是绑定，不是外流。"""
    fn = ast.parse("def f(_auth=Depends(verify_api_key)):\n    return 1\n").body[0]
    assert lint._credential_escape_lines(fn, lint._credential_bound_params(fn)) == []


def test_p12_known_blind_spot_return_is_not_a_call_arg():
    """已知局限（**不是**待修 bug 的免死牌）：``return`` 外流形状抓不到。

    写下它是为了防止后续把 P12 当「凭据不入审计的全局完备门禁」来汇报——行为面
    （本文件 ① 组）与人工语义审计才是补这段盲区的力量。
    """
    fn = ast.parse("def f(api_key=Depends(verify_api_key)):\n    return api_key\n").body[0]
    assert lint._credential_escape_lines(fn, lint._credential_bound_params(fn)) == []


# ---------------------------------------------------------------------------
# ③ 端到端扫描面：真实树零违规 + 合成必红 + fail-closed
# ---------------------------------------------------------------------------


_BAD_SRC = (
    "from fastapi import Depends\n"
    "from agent_server.api.auth import verify_api_key\n"
    "async def endpoint(req, api_key=Depends(verify_api_key)):\n"
    "    return await handler.revert(api_key, req.sid)\n"
)
_GOOD_SRC = (
    "from fastapi import Depends\n"
    "from agent_server.api.auth import verify_api_key\n"
    "async def endpoint(req, _auth=Depends(verify_api_key)):\n"
    "    return await handler.revert(server_tenant_id('acme'), req.sid)\n"
)


def test_p12_current_tree_has_zero_violations():
    assert lint.check_credential_param_escape() == []


def test_p12_outside_applications_scope_is_not_scanned(tmp_path, monkeypatch):
    """作用域限定 ``applications/**``：kernel 侧对凭据的处理归 P6，不在本门禁重复计。"""
    pkg = tmp_path / "packages" / "agent-core" / "agent_core"
    pkg.mkdir(parents=True)
    (pkg / "leak.py").write_text(_BAD_SRC, encoding="utf-8")
    monkeypatch.setattr(lint, "ROOT", tmp_path)
    assert lint.check_credential_param_escape() == []


def test_p12_scan_flags_bad_and_spares_good(tmp_path, monkeypatch):
    app_dir = tmp_path / "applications" / "demo"
    app_dir.mkdir(parents=True)
    (app_dir / "bad.py").write_text(_BAD_SRC, encoding="utf-8")
    (app_dir / "good.py").write_text(_GOOD_SRC, encoding="utf-8")
    monkeypatch.setattr(lint, "ROOT", tmp_path)

    violations = lint.check_credential_param_escape()
    assert len(violations) == 1
    assert "bad.py" in violations[0] and "api_key" in violations[0]


def test_p12_is_fail_closed_on_unparsable_file(tmp_path, monkeypatch):
    """解析不了不得静默放行（与 P11 同一口径），否则门禁退化为约定。"""
    app_dir = tmp_path / "applications" / "demo"
    app_dir.mkdir(parents=True)
    (app_dir / "broken.py").write_text("def f(:\n", encoding="utf-8")
    monkeypatch.setattr(lint, "ROOT", tmp_path)

    violations = lint.check_credential_param_escape()
    assert any("broken.py" in v and "无法解析" in v for v in violations)


def test_p12_bom_file_still_scanned_and_still_bites(tmp_path, monkeypatch):
    """BOM 回归锁：utf-8-sig 读取既不能把 BOM 误判成「无法解析」，也不能因此漏判外流。

    本仓有 10 个已入库的 BOM 文件（``nl2sql_service/**/__init__.py``），早期用
    ``encoding="utf-8"`` 读会让 P12 在无违规时报出 10 条假阳性（fail-closed 退化为噪音）。
    """
    app_dir = tmp_path / "applications" / "demo"
    app_dir.mkdir(parents=True)
    (app_dir / "clean_bom.py").write_text(_GOOD_SRC, encoding="utf-8-sig")
    (app_dir / "bad_bom.py").write_text(_BAD_SRC, encoding="utf-8-sig")
    monkeypatch.setattr(lint, "ROOT", tmp_path)

    violations = lint.check_credential_param_escape()
    assert len(violations) == 1
    assert "bad_bom.py" in violations[0]
    assert not any("无法解析" in v for v in violations)


def test_p12_the_real_session_router_goes_red_if_the_guard_is_stripped():
    """回归锁：把真实 ``session_router`` 的防线剥掉（审计主体改回凭据），P12 必须立刻判红。

    这排除了「门禁只是恰好没命中」的假通过——证明 ``applications/`` 零违规确实由
    当前的 ``server_tenant_id`` 写法撑着，而不是判据根本没接通。
    """
    rel = "applications/agent_server/api/session_router.py"
    text = (_ROOT / rel).read_text(encoding="utf-8-sig")
    assert "operator = server_tenant_id(settings.default_tenant_id)" in text

    stripped = text.replace(
        "result = await revert_handler.revert(operator, req.session_id, req.checkpoint_id)",
        "result = await revert_handler.revert(_auth, req.session_id, req.checkpoint_id)",
    )
    assert stripped != text, "未剥掉任何内容，替换逻辑失效"

    tree = ast.parse(stripped, filename=rel)
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names = lint._credential_bound_params(node)
            hits.extend(lint._credential_escape_lines(node, names))
    assert hits, "剥掉防线后 P12 判据仍未命中 ⇒ 门禁形同虚设"
    assert hits[0][1] == "_auth"
