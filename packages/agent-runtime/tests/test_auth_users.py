"""用户目录（``agent_runtime.auth_users``）判据测试：方案 plan-web-auth-user-minimal A1/A3/D-c/D-g。

无 PG 也能跑：fake pool 判 SQL 形状与参数序（与同目录 ``test_conversations_ownership.py`` 的
``_FakePool`` 同思路，本件不复用它 —— 测试文件互相 import 会让一个 session 的改名波及另一个）。

六格各钉一条会被"顺手改回去"的取舍，注释里写明**红的时候是什么形状**：

1. A1 落库的是 argon2 形态串，明文不入参数；
2. D-c ``password_hash IS NULL`` 一律拒（把 NULL 当空串比较即红）；
3. A3 账号不存在与口令错同返回 ``None``，且**都消耗一次散列校验**（去掉 ``_burn`` 即红）；
4. D-g 首账号提权判据在 advisory xact lock 之后、INSERT 之前（换顺序即红）；
5. 表/列缺失 ⇒ :class:`AuthStoreUnavailable`，**不降级放行**（照抄 register_workspace 的降级即红）；
6. 缺 argon2 依赖 ⇒ ``AuthStoreUnavailable``，**不得伪装成"口令不对"**（把 ``_get_hasher()``
   挪回 try 内即红 —— 那是本轮真实修掉的一处 fail-open）。
"""

from __future__ import annotations

import dataclasses
import sys
from typing import Any

import pytest
from agent_core.guardrails.auth import _PRINCIPAL_RE

from agent_runtime import auth_users as au

# ---------------------------------------------------------------------------
# fake pool（本件需要事务与多游标回放，形状与 conversations 那份不同 ⇒ 自带一份）
# ---------------------------------------------------------------------------


class _FakeCursor:
    def __init__(self, row=None):
        self._row = row

    async def fetchone(self):
        return self._row


class _FakeTxn:
    def __init__(self, pool):
        self._pool = pool

    async def __aenter__(self):
        self._pool.history.append(("<<TXN-BEGIN>>", ()))
        return self

    async def __aexit__(self, *exc):
        self._pool.history.append(("<<TXN-END>>", ()))
        return False


class _FakeConn:
    def __init__(self, pool):
        self._pool = pool

    def transaction(self):
        return _FakeTxn(self._pool)

    async def execute(self, sql, params=None):
        norm = " ".join(sql.split())
        self._pool.history.append((norm, tuple(params or ())))
        for i, (substr, result) in enumerate(self._pool.script):
            if substr in norm:
                self._pool.script.pop(i)
                if isinstance(result, BaseException):
                    raise result
                return _FakeCursor(row=result)
        return _FakeCursor(row=None)


class _FakePool:
    """记录全部 SQL + 参数；按 ``queue`` 顺序回放（先命中先消费，与真实连接池的语句序一致）。"""

    def __init__(self):
        self.history: list[tuple[str, tuple]] = []
        self.script: list[tuple[str, Any]] = []

    def connection(self):
        pool = self

        class _Ctx:
            async def __aenter__(self):
                return _FakeConn(pool)

            async def __aexit__(self, *exc):
                return False

        return _Ctx()

    def queue(self, sql_substr: str, result):
        self.script.append((sql_substr, result))

    def sqls(self) -> list[str]:
        return [s for s, _ in self.history]


def _pg_error(sqlstate: str) -> Exception:
    e = Exception(sqlstate)
    e.sqlstate = sqlstate
    return e


# ---------------------------------------------------------------------------
# 归一化（D-d）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    ["alice", "Alice", "  alice  ", "a.b_c-1", "abc", "z" * 32],
)
def test_normalize_login_accepts(raw):
    assert au.normalize_login(raw) == raw.strip().lower()


@pytest.mark.parametrize(
    "raw",
    ["", "  ", "ab", "a" * 33, "_lead", ".lead", "-lead", "alice@example.com", "alice bob", "张三", "a/b", "a:b"],
)
def test_normalize_login_rejects(raw):
    with pytest.raises(au.InvalidLogin):
        au.normalize_login(raw)


@pytest.mark.parametrize("raw", [None, 123, 3.5, [], {}, b"alice"])
def test_normalize_login_non_string_rejects(raw):
    """非字符串也走同一条例外（调用方只需 catch 一类，不必先做类型守卫）。"""
    with pytest.raises(au.InvalidLogin):
        au.normalize_login(raw)


@pytest.mark.parametrize("login", ["alice", "a.b_c-1", "abc", "z" * 32, "9live"])
def test_accepted_login_is_legal_principal(login):
    """D-l 的前置条件：归一化后的 id 必须能安全拼进会话主体。

    不是风格检查 —— ``asserted_person_id`` 的段内字符集与内核 ``_PRINCIPAL_RE`` 一旦分叉，
    症状是"注册能过、/query 每请求 500"。这里钉的是**接受集 ⊆ 内核字符集**（真子集关系）。
    """
    assert _PRINCIPAL_RE.match(login), login


# ---------------------------------------------------------------------------
# A1：散列形态
# ---------------------------------------------------------------------------


def test_hash_password_is_argon2id_shape():
    h = au.hash_password("correct horse battery")
    assert h.startswith("$argon2id$")
    assert "correct horse battery" not in h


async def test_create_user_persists_argon2_shape_not_plaintext():
    """A1 的本体：落到参数位上的必须是散列串，明文一个字都不许出现在 SQL 通路里。"""
    pool = _FakePool()
    pool.queue("SELECT 1 FROM users", None)  # 表内零用户 ⇒ 首账号 admin
    pool.queue("INSERT INTO users", ("alice",))
    pw = "Sup3r-Secret-Pass!"
    await au.create_user(pool, "alice", pw, org_id="acme")
    ins = next((p for s, p in pool.history if s.startswith("INSERT INTO users")), None)
    assert ins is not None, pool.sqls()
    assert ins[-1].startswith("$argon2id$")
    assert pw not in ins
    assert not any(pw in " ".join(map(str, p)) for _, p in pool.history)


async def test_create_user_wraps_in_transaction_with_advisory_lock():
    """D-g：首账号提权是跨请求判断，必须在事务 + advisory xact lock 内完成。

    判据看**顺序**而不只看存在：锁在 INSERT 之后拿到等于没锁（两个并发注册都会先读到
    "还没有用户"，同秒产出两个管理员）。
    """
    pool = _FakePool()
    pool.queue("SELECT 1 FROM users", None)
    pool.queue("INSERT INTO users", ("alice",))
    await au.create_user(pool, "alice", "password123", org_id="acme")
    sqls = pool.sqls()
    assert "<<TXN-BEGIN>>" in sqls
    i_lock = sqls.index("SELECT pg_advisory_xact_lock(%s)")
    i_seed = next(i for i, s in enumerate(sqls) if s.startswith("INSERT INTO organizations"))
    i_admin = next(i for i, s in enumerate(sqls) if s.startswith("SELECT 1 FROM users"))
    i_ins = next(i for i, s in enumerate(sqls) if s.startswith("INSERT INTO users"))
    assert i_lock < i_seed < i_admin < i_ins, sqls


async def test_create_user_first_account_becomes_admin():
    pool = _FakePool()
    pool.queue("SELECT 1 FROM users", None)
    pool.queue("INSERT INTO users", ("alice",))
    rec = await au.create_user(pool, "alice", "password123", org_id="acme")
    assert rec.is_admin is True
    assert rec.id == "alice" and rec.org_id == "acme"


async def test_create_user_second_account_is_not_admin():
    pool = _FakePool()
    pool.queue("SELECT 1 FROM users", (1,))  # 已有用户 ⇒ 不再是首账号
    pool.queue("INSERT INTO users", ("bob",))
    rec = await au.create_user(pool, "bob", "password123", org_id="acme")
    assert rec.is_admin is False


async def test_create_user_explicit_is_admin_wins():
    """``is_admin`` 显式传入时不查表（管理员建号的通路）。"""
    pool = _FakePool()
    pool.queue("INSERT INTO users", ("ops",))
    rec = await au.create_user(pool, "ops", "password123", org_id="acme", is_admin=False)
    assert rec.is_admin is False
    assert not any(s.startswith("SELECT 1 FROM users") for s in pool.sqls())


async def test_create_user_duplicate_raises_exists():
    pool = _FakePool()
    pool.queue("SELECT 1 FROM users", (1,))
    pool.queue("INSERT INTO users", None)  # ON CONFLICT DO NOTHING ⇒ 0 行
    with pytest.raises(au.UserExistsError):
        await au.create_user(pool, "alice", "password123", org_id="acme")


@pytest.mark.parametrize("state", ["42P01", "42703"])
async def test_missing_table_or_column_is_unavailable_not_degraded(state):
    """判据 5：表/列缺失 ⇒ AuthStoreUnavailable，**不降级放行**。

    与 ``register_workspace`` 的降级分支刻意不同形：那边少一列只是少一个展示字段，这边少一张
    表等于少一整个安全边界，放行就是"没有用户目录也能建号"。
    """
    pool = _FakePool()
    pool.queue("INSERT INTO organizations", _pg_error(state))
    with pytest.raises(au.AuthStoreUnavailable):
        await au.create_user(pool, "alice", "password123", org_id="acme")


async def test_real_db_failure_not_swallowed():
    """非 42P01/42703 的故障照原样往外抛（降级面不等于 fail-open）。"""
    pool = _FakePool()
    pool.queue("INSERT INTO organizations", _pg_error("57P01"))
    with pytest.raises(Exception) as exc:
        await au.create_user(pool, "alice", "password123", org_id="acme")
    assert not isinstance(exc.value, au.AuthStoreUnavailable)


@pytest.mark.parametrize("org", ["", "   ", None])
async def test_create_user_requires_org_id(org):
    """D-e：注册落哪个企业由部署声明，空 org 不是"默认租户"的入口。"""
    with pytest.raises(ValueError):
        await au.create_user(_FakePool(), "alice", "password123", org_id=org)


async def test_create_user_pool_none_is_unavailable():
    with pytest.raises(au.AuthStoreUnavailable):
        await au.create_user(None, "alice", "password123", org_id="acme")


# ---------------------------------------------------------------------------
# A3 / D-c：凭据校验
# ---------------------------------------------------------------------------


async def test_verify_credentials_ok_returns_record_without_hash():
    pool = _FakePool()
    pool.queue("SELECT id, org_id", ("alice", "acme", "Alice", False, au.hash_password("password123")))
    rec = await au.verify_credentials(pool, "alice", "password123")
    assert rec is not None and rec.id == "alice"
    # A7 的实现面：结构上没有 password_hash 字段，散列不可能顺着返回值外流
    assert not hasattr(rec, "password_hash")
    assert "password_hash" not in {f.name for f in dataclasses.fields(au.UserRecord)}


async def test_null_password_hash_is_rejected():
    """D-c 本体：``password_hash IS NULL`` 一律拒，绝不与空串比较。"""
    pool = _FakePool()
    pool.queue("SELECT id, org_id", ("carol", "acme", "Carol", False, None))
    assert await au.verify_credentials(pool, "carol", "") is None
    assert await au.verify_credentials(pool, "carol", "anything") is None


async def test_wrong_password_and_unknown_user_return_same_none():
    """A3 的实现面：两种失败**同返回形状**（文案与状态码由宿主统一给）。"""
    pool_known = _FakePool()
    pool_known.queue("SELECT id, org_id", ("alice", "acme", "Alice", False, au.hash_password("password123")))
    wrong = await au.verify_credentials(pool_known, "alice", "bad-password-xx")
    pool_unknown = _FakePool()
    pool_unknown.queue("SELECT id, org_id", None)
    missing = await au.verify_credentials(pool_unknown, "nobody", "bad-password-xx")
    assert wrong is None and missing is None


async def test_unknown_user_still_burns_one_verify(monkeypatch):
    """A3 的时间侧信道那半：账号不存在也要消耗一次 argon2 校验。

    去掉 ``_burn`` 就红 —— 响应时间会把"这个账号存不存在"泄漏给未鉴权的一端。
    用打桩计数而不是比耗时：耗时断言在 CI 上是掷骰子。
    """
    burns: list[str] = []
    monkeypatch.setattr(au, "_burn", lambda password: burns.append(password))
    pool = _FakePool()
    pool.queue("SELECT id, org_id", None)
    assert await au.verify_credentials(pool, "ghost", "password123") is None
    assert burns == ["password123"]


async def test_known_user_wrong_password_does_not_burn(monkeypatch):
    """反向钉死上一条不是"无条件烧"：走真校验的那条分支不该再烧一次（双倍 CPU）。"""
    burns: list[str] = []
    monkeypatch.setattr(au, "_burn", lambda password: burns.append(password))
    pool = _FakePool()
    pool.queue("SELECT id, org_id", ("alice", "acme", "Alice", False, au.hash_password("password123")))
    assert await au.verify_credentials(pool, "alice", "wrong-but-long-1") is None
    assert burns == []


async def test_empty_password_does_not_touch_db(monkeypatch):
    """空口令不进门，也不给"这个账号存在吗"留时间信号。"""
    monkeypatch.setattr(au, "_burn", lambda password: None)
    pool = _FakePool()
    assert await au.verify_credentials(pool, "alice", "") is None
    assert pool.history == []


@pytest.mark.parametrize("bad", ["", "  ", "short", "a" * 129])
async def test_password_policy_rejects(bad):
    with pytest.raises(au.InvalidPassword):
        au.check_password_policy(bad)


@pytest.mark.parametrize("pw", ["password123", "a" * 128])
def test_password_policy_accepts_band(pw):
    assert au.check_password_policy(pw) == pw


def test_verify_password_null_hash_is_false():
    assert au.verify_password(None, "whatever") is False
    assert au.verify_password("", "whatever") is False


def test_verify_password_corrupt_hash_is_false_not_crash():
    """库里存了一行非 argon2 形态的串（人工写入/迁移事故）⇒ 判 False，不把库异常外抛。"""
    assert au.verify_password("not-a-hash", "whatever") is False


# ---------------------------------------------------------------------------
# 判据 6：缺依赖不得伪装成"口令不对"（本轮真实修掉的 fail-open 形状）
# ---------------------------------------------------------------------------


def _make_argon2_unimportable(monkeypatch):
    """把 ``argon2`` 置为 ``sys.modules[...] = None``：``import argon2`` 当场 ImportError。"""
    monkeypatch.setattr(au, "_hasher", None)
    monkeypatch.setattr(au, "_dummy_hash", None)
    monkeypatch.setitem(sys.modules, "argon2", None)


def test_missing_dependency_raises_unavailable_on_hash(monkeypatch):
    _make_argon2_unimportable(monkeypatch)
    with pytest.raises(au.AuthStoreUnavailable):
        au.hash_password("password123")


def test_missing_dependency_raises_unavailable_on_verify(monkeypatch):
    """关键一格：缺 argon2 时**不能**返回 False（那等于把配置错误说成"口令不对"）。

    成因是 ``_get_hasher()`` 曾在 ``try`` 内 —— 现在它在 try 外，``AuthStoreUnavailable``
    照常往外走；把它挪回 try 内本条即红。
    """
    _make_argon2_unimportable(monkeypatch)
    with pytest.raises(au.AuthStoreUnavailable):
        au.verify_password("$argon2id$v=19$m=65536,t=3,p=4$x$y", "password123")


def test_verify_password_returns_true_for_matching_hash():
    h = au.hash_password("password123")
    assert au.verify_password(h, "password123") is True
    assert au.verify_password(h, "password124") is False


async def test_touch_last_login_missing_column_is_silent():
    """展示位不是安全边界：016 未应用时静默，不影响登录成立（与 create_user 的处置刻意不同）。"""
    pool = _FakePool()
    pool.queue("UPDATE users", _pg_error("42703"))
    assert await au.touch_last_login(pool, "alice") is None
