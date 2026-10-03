# -*- coding: utf-8 -*-
"""会话身份与凭据隔离收口（DUP-1 / CodeQL weak-sensitive-data-hashing）单元测试。

覆盖内核 ``agent_core.guardrails.auth`` 的契约：
- ``resolve_thread_identity``：会话身份 = ``tenant-<服务端断言主体>``，**不做任何摘要**
  （B7b-4 拆链①的产物，含字符集 fail-fast 与单射性）；
- 语义门禁：本模块内不得再有「凭据 → 摘要」调用点，也不再 import hashlib/hmac
  （B7b-5 已删除全仓唯一的指纹实现与旧格式助手）。

另含 B7b-2 对链②的**反向**守门：``resolve_client_key`` 与凭据摘要彻底无关
（旧契约「限流桶 key 也走同一指纹实现」已于 B7b-2 作废，见文件末段）。

文件名保留历史名（本文件早期专测 ``fingerprint``）：改名属扩大爆炸半径，此处只把
标题与内容订正为真实被守护对象。
"""

import ast
import hashlib
import inspect
import pathlib

import pytest

from agent_core.guardrails import auth as auth_module

from agent_core.guardrails.auth import (
    THREAD_ID_PREFIX,
    resolve_client_key,
    resolve_thread_identity,
)
from agent_core.guardrails.fs import safe_filename


# ---------------------------------------------------------------------------
# resolve_thread_identity：会话身份（B7b-4 拆链①：主体明文、不做摘要）
# ---------------------------------------------------------------------------


def test_resolve_thread_identity_format():
    tid = resolve_thread_identity("acme")
    assert tid == "tenant-acme"
    assert tid.startswith(THREAD_ID_PREFIX)


def test_resolve_thread_identity_stable_and_isolating():
    """同主体稳定、不同主体隔离（会话不互串）——不依赖任何密钥。"""
    assert resolve_thread_identity("tenant-a") == resolve_thread_identity("tenant-a")
    assert resolve_thread_identity("tenant-a") != resolve_thread_identity("tenant-b")


def test_resolve_thread_identity_is_not_a_digest_of_credentials():
    """新格式与两代旧形态可分 ⇒ B7b-5 的枚举判别式不需长度/字符集启发式。

    旧入口函数已随 B7b-5 删除 ⇒ 本用例就地用 hashlib 复算「历史落盘形态」作对照
    （测试面不受 P6 扫描；产品代码里不得再出现这类派生）。
    """
    digest = hashlib.sha256(b"secret-a").hexdigest()
    legacy_48bit = f"user-{digest[:12]}"
    legacy_128bit = f"user-{digest[:32]}"
    tid = resolve_thread_identity("secret-a")
    assert tid == f"{THREAD_ID_PREFIX}secret-a"
    assert tid not in {legacy_48bit, legacy_128bit}
    assert not tid.startswith("user-")


def test_resolve_thread_identity_strips_surrounding_whitespace():
    assert resolve_thread_identity("  acme ") == resolve_thread_identity("acme")


@pytest.mark.parametrize("principal", ["", "   ", None])
def test_resolve_thread_identity_rejects_blank_principal(principal):
    """空主体绝不静默落共享桶（fail-fast）——静默兜底 = 跨租户串会话。"""
    with pytest.raises(ValueError):
        resolve_thread_identity(principal)


@pytest.mark.parametrize(
    "principal",
    [
        "a:b",  # safe_filename 会把 : 洗成 _ → 与 "a_b" 落同一目录
        "a/b",
        "a\\b",
        "a b",
        "tenant*",
        "q?x",
        "<script>",
        "pipe|sep",
        "-leading",
        ".leading",
        "_leading",
        "a" * 65,  # 超 64
        "中文租户",
    ],
)
def test_resolve_thread_identity_rejects_non_filename_safe_principal(principal):
    r"""字符集 fail-fast：内核**不做有损清洗**（清洗 = 制造碰撞面）。

    实取 ``guardrails/fs.py`` 白名单为 ``[^\w.\- ]``，``:`` ``/`` ``\`` ``*`` ``?`` 等一律换为
    ``_`` ⇒ 租户 ``a:b`` 与 ``a_b`` 清洗后同名，迁移的「目标已存在拒绝覆盖」会误判为碰撞。
    """
    with pytest.raises(ValueError):
        resolve_thread_identity(principal)


@pytest.mark.parametrize("principal", ["default", "acme-corp", "t_1", "a.b.c.d", "T0", "9lives"])
def test_resolve_thread_identity_accepts_documented_principals(principal):
    assert resolve_thread_identity(principal) == f"{THREAD_ID_PREFIX}{principal}"


def test_resolve_thread_identity_is_injective_under_safe_filename():
    """单射性：合法主体过 ``safe_filename`` 后仍两两不同（挡住「内核有损清洗」的退化写法）。"""
    principals = ["default", "acme-corp", "t_1", "a.b.c.d", "T0", "9lives", "x-y_z.w"]
    cleaned = [safe_filename(resolve_thread_identity(p)) for p in principals]
    assert len(set(cleaned)) == len(principals), "safe_filename 后发生碰撞：会话目录会互串"


def test_thread_id_prefix_is_not_the_legacy_namespace():
    """前缀不得改回 ``user-``：那是 overloaded 命名空间（旧两代摘要 + 客户端自填值）。

    取代原「旧键仍产出 ``user-``」用例：被治理对象（``legacy_thread_id``）已删除，
    同等语义改由本断言 + 迁移脚本文档用例承接（非删用例交差）。
    """
    assert THREAD_ID_PREFIX == "tenant-"
    assert safe_filename("user-x") == "user-x"  # 旧前缀仍可能是库内历史值，不改写


# ---------------------------------------------------------------------------
# resolve_client_key：B7b-2 已拆链②（旧契约「桶键走 fingerprint 摘要」作废）
# 下列守门锁的是「凭据进不了限流桶」这一语义，而非某个参数名。
# ---------------------------------------------------------------------------


def test_resolve_client_key_signature_cannot_receive_credential():
    """签名级守门：只接受 IP 与已断言主体（旧签名的 ``headers``/``auth_enabled`` 正是链②入口）。"""
    params = set(inspect.signature(resolve_client_key).parameters)
    assert params == {"client_host", "subject"}


@pytest.mark.parametrize("credential", ["secret", "sk-123", "Bearer xyz", "a" * 64])
def test_resolve_client_key_bucket_independent_of_credential(credential):
    """同一 IP 的桶键必与「带不带凭据 / 带哪把凭据」无关，且不含任何摘要形态。

    旧用例额外把 pepper 拉高/拉低来验证桶键不受 pepper 影响 —— 被治理对象（指纹
    实现与 pepper 常量）已随 B7b-5 删除，同等语义改由下列穷举摘要算法的否定式
    断言承接（不收窄而是加严），并由模块级 AST 门禁锁住「本模块不再 import
    hashlib/hmac」。
    """
    key = resolve_client_key("1.2.3.4")
    assert key == "ip:1.2.3.4"
    assert not key.startswith("key:")
    assert credential not in key
    encoded = credential.encode("utf-8")
    for algo in ("md5", "sha1", "sha224", "sha256", "sha384", "sha512"):
        full = hashlib.new(algo, encoded).hexdigest()
        for digest in (full, full[:12], full[:32]):
            assert digest not in key


def test_resolve_client_key_uses_subject_verbatim_not_digest():
    """主体直用明文：不得为了「看起来更安全」而把主体过一道摘要（那只是新散点）。"""
    assert resolve_client_key("1.2.3.4", "tenant-α") == "sub:tenant-α"
    assert resolve_client_key("1.2.3.4", "  tenant-α  ") == "sub:tenant-α"


def test_no_function_digests_credentials_anymore():
    """语义门禁（AST）：本模块内调用指纹的函数集合 == ``set()``，且无任何哈希原语。

    三条「凭据 → 摘要」链已全部拆除（链③ B7b-1 slot 化 / 链② B7b-2 主体优先 / 链① B7b-4
    会话身份主体化）⇒ 本断言由 ``{derive_thread_id}`` 收到空集（用例 docstring 早已预告
    这一改法，**不得删用例交差**）。今后任何新增的「凭据 → 摘要」消费点都会在此红
    ——守的是语义而非名字，改名绕过也会被拿到（方案 §5）：故除「旧入口名被调用」外，
    还断言「``hashlib``/``hmac`` 的 import 与属性调用在本模块为零」，即使换个名字
    手写摘要也逃不掉。
    """
    src = pathlib.Path(inspect.getfile(auth_module)).read_text(encoding="utf-8")
    tree = ast.parse(src)
    callers = {
        func.name
        for func in ast.walk(tree)
        if isinstance(func, ast.FunctionDef | ast.AsyncFunctionDef)
        for call in ast.walk(func)
        if isinstance(call, ast.Call)
        and (
            getattr(call.func, "id", None)
            in {"fingerprint", "derive_thread_id", "legacy_thread_id"}
            or getattr(call.func, "attr", None) == "new"
        )
    }
    assert callers == set()
    # 模块顶层：不得 import 任何哈希原语（包括别名与 from-import）
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {(alias.name or "").split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not imported & {"hashlib", "hmac"}, imported
    # 属性调用形态：hashlib.sha256(...) / hmac.new(...) 等一律为零
    digest_attr_calls = [
        ast.dump(call.func)
        for call in ast.walk(tree)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id in {"hashlib", "hmac", "blake2b", "blake2s"}
    ]
    assert digest_attr_calls == [], digest_attr_calls
