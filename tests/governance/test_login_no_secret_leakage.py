"""A7：口令 / 散列 / 令牌 / 私钥不得进日志与响应体（方案 plan-web-auth-user-minimal §6 判据表）。

为什么做成**源级扫描**而不是"跑一遍看日志"：这三条都是"今天没漏、明天加一行日志就漏"的
不变量，只有把形状钉死才能在下一次改动时变红。同族做法见本目录
``test_audit_operator_principal.py``（AST 扫凭据外流）。

四格各自的失效形状：

1. ``UserRecord`` / 响应模型**结构上就没有**散列与口令字段 —— 一旦有，它就迟早出现在某个
   ``return`` 或某行日志里；
2. 登录面的任何 ``logger`` 调用不得引用口令、散列、令牌、私钥四类变量；
3. 明文口令不得作为 SQL 参数出现（只能以散列形态进参数位）；
4. 用户输入进日志前必须过收口（截断 + 字符集），否则换行/控制字符可以伪造日志行。
"""

from __future__ import annotations

import ast
import dataclasses
import re
from pathlib import Path

import pytest
from agent_runtime import auth_users as au
from agent_server.api import auth_router

_ROOT = Path(__file__).resolve().parents[2]
ROUTER_SRC = (_ROOT / "applications/agent_server/api/auth_router.py").read_text(encoding="utf-8")
USERS_SRC = (_ROOT / "packages/agent-runtime/agent_runtime/auth_users.py").read_text(encoding="utf-8")

# 四类秘密在源码里的变量名形态（比"扫敏感词"精确：扫的是**标识符**，注释里的中文词不误伤）。
_SECRET_NAMES = (
    "password",
    "pw_hash",
    "password_hash",
    "access_token",
    "token",
    "private_key_pem",
)


def _logger_calls(src: str) -> list[ast.Call]:
    """取所有 ``logger.*(...)`` 调用节点（含 ``logger.info/exception/...``）。"""
    out: list[ast.Call] = []
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            base = node.func.value
            if isinstance(base, ast.Name) and base.id == "logger":
                out.append(node)
    return out


def _names_in(node: ast.AST) -> set[str]:
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def _attr_names_in(node: ast.AST) -> set[str]:
    return {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}


# ---------------------------------------------------------------------------
# 格 1：结构上没有可外流的字段
# ---------------------------------------------------------------------------


def test_user_record_has_no_password_field():
    fields = {f.name for f in dataclasses.fields(au.UserRecord)}
    assert fields == {"id", "org_id", "display_name", "is_admin"}
    assert not any("password" in f or "hash" in f for f in fields), fields


@pytest.mark.parametrize(
    "model,allowed",
    [
        (auth_router.TokenResponse, {"token_type", "access_token", "expires_in", "tenant_id", "user_id", "is_admin"}),
        (auth_router.MeResponse, {"tenant_id", "user_id"}),
    ],
)
def test_response_models_are_exact(model, allowed):
    """字段集**恰等于**声明集：多加一个"顺手回显"的字段就要先过本条。

    ``access_token`` 允许出现在**它自己的那次响应**里（它就是给前端的），但绝不允许出现在
    ``MeResponse`` 这类会被反复读取的响应里。
    """
    assert set(model.model_fields) == allowed, set(model.model_fields) ^ allowed


def test_me_response_carries_no_token():
    assert "access_token" not in auth_router.MeResponse.model_fields
    assert "password" not in " ".join(auth_router.MeResponse.model_fields)


# ---------------------------------------------------------------------------
# 格 2：日志行不引用秘密
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("src_name,src", [("auth_router", ROUTER_SRC), ("auth_users", USERS_SRC)])
def test_no_logger_call_references_secrets(src_name, src):
    offenders = []
    for call in _logger_calls(src):
        used = _names_in(call) | _attr_names_in(call)
        hit = {n for n in used if n in _SECRET_NAMES}
        # ``body.login`` / ``user.id`` 之类不是秘密；只盯标识符，注释与文案不参与判定
        if hit:
            offenders.append((call.lineno, sorted(hit)))
    assert not offenders, f"{src_name} 的日志行引用了秘密变量：{offenders}"


def test_no_fstring_embeds_plaintext_password():
    """``f"...{password}"`` 这一形一旦存在，它就会跟着日志/响应/异常文案一起漂。"""
    assert not re.search(r"f\"[^\"]*\{[^}]*password[^}]*\}", USERS_SRC), "auth_users 里有 f-string 内插口令"
    assert not re.search(r"f\"[^\"]*\{[^}]*password[^}]*\}", ROUTER_SRC), "auth_router 里有 f-string 内插口令"


# ---------------------------------------------------------------------------
# 格 3：明文口令只以散列形态进 SQL 参数
# ---------------------------------------------------------------------------


def test_plaintext_password_is_never_a_sql_argument():
    """AST 级：任何 ``conn.execute(sql, (..., password, ...))`` 里出现 ``password`` 标识符即红。

    只看 ``execute`` 的参数元组/列表，不看函数形参 —— 形参叫 password 是语义正确的（目录就是
    收口令的），漏的是它被原样送进 SQL。
    """
    tree = ast.parse(USERS_SRC)
    offenders: list[int] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "execute"):
            continue
        for arg in node.args[1:]:
            if _names_in(arg) & {"password"} or _attr_names_in(arg) & {"password"}:
                offenders.append(node.lineno)
    assert not offenders, f"明文口令进了 SQL 参数（行 {offenders}）；应传 hash_password(password) 的产物"


def test_hash_password_result_is_what_reaches_the_insert():
    """正向对照：INSERT 参数里必须是散列变量，不是口令本身（防止上一条被"删掉口令"糊过）。"""
    tree = ast.parse(USERS_SRC)
    inserts = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "execute"
        and isinstance(n.args[0], ast.Constant)
        and isinstance(n.args[0].value, str)
        and "INSERT INTO users" in " ".join(n.args[0].value.split())
    ]
    assert inserts, "没找到 INSERT INTO users 的 execute 调用（被改名了？本条要跟着改，别删）"
    for call in inserts:
        used = _names_in(call.args[1]) if len(call.args) > 1 else set()
        assert "pw_hash" in used, used
        assert "password" not in used, used


# ---------------------------------------------------------------------------
# 格 4：用户输入进日志前收口
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expect_clean",
    [
        ("alice", "alice"),
        ("ALICE", "alice"),
        ("a" * 200, "***"),
        ("alice\nFAKE LOG LINE", "***"),
        ("alice;rm", "***"),
        ("", "***"),
    ],
)
def test_redact_normalizes_or_masks(raw, expect_clean):
    """要么干净要么打码，不做转义：登录名不是秘密（A3 的前提就是存在性不保密），
    但它是**用户输入**，原样进日志等于给换行/控制字符开注入面。
    """
    assert auth_router._redact(raw) == expect_clean


def test_no_hardcoded_secret_literals_in_login_surface():
    """登录面源码里不得出现 PEM 私钥体，也不得出现形似 base64 DER 的字面量。

    本轮拍板是"新生成的密钥只写 K8s Secret"，这条就是那句拍板的机器面：仓里出现一次
    ``BEGIN … PRIVATE KEY`` 就说明有人把密钥抄进了代码/文档。
    """
    for name, src in (("auth_router", ROUTER_SRC), ("auth_users", USERS_SRC)):
        upper = src.upper()
        # 与 scripts/lint_public_mirror.py:_asm 同形：needle 只在运行时成形，源码里不落完整
        # 私钥头整串（否则公开镜像零容忍的 publish 模式会把测试自己当新公开的凭据）。
        # 断言强度不变：拼出来仍是三个完整 PEM 头，照样咬得到抄进登录面的私钥。
        for marker in (
            "".join(("BEGIN ", "RSA PRIVATE KEY")),
            "".join(("BEGIN ", "PRIVATE KEY")),
            "".join(("BEGIN ", "EC PRIVATE KEY")),
        ):
            assert marker not in upper, f"{name} 里出现了私钥体 {marker}"
        assert "MII" not in src, f"{name} 里出现了形似 base64 DER 的字面量"
