"""E-2 SQL 守卫统一单测（优化 E / P4.2）。

覆盖 `tools/sql_guard.validate_sql_mysql`：
  - 委托内核 agent_core.sql.guard（dialect=mysql）放行只读 SELECT；
  - 被禁 DML（INSERT/DELETE/UPDATE/DROP）被拒；
  - 无 LIMIT 的 SELECT 由内核 max_rows 兜底补充；
  - USE_CORE_GUARD=off 时回退到原 sql_validation 实现。
"""

import importlib

import pytest


@pytest.fixture
def sql_guard(monkeypatch):
    # 确保开关处于默认 on
    monkeypatch.setattr("tools.sql_guard._USE_CORE_GUARD", True)
    monkeypatch.setattr("tools.sql_guard._HAS_CORE_GUARD", True)
    import tools.sql_guard as sg

    return sg


def test_select_pass(sql_guard):
    ok, reason, cleaned = sql_guard.validate_sql_mysql("SELECT id, name FROM users")
    assert ok is True
    assert "LIMIT" in cleaned.upper()


def test_select_with_existing_limit(sql_guard):
    ok, reason, cleaned = sql_guard.validate_sql_mysql("SELECT id FROM users LIMIT 50")
    assert ok is True
    assert "LIMIT 50" in cleaned.upper()


def test_reject_insert(sql_guard):
    ok, reason, _ = sql_guard.validate_sql_mysql("INSERT INTO users (name) VALUES ('x')")
    assert ok is False


def test_reject_delete(sql_guard):
    ok, reason, _ = sql_guard.validate_sql_mysql("DELETE FROM users WHERE id = 1")
    assert ok is False


def test_reject_update(sql_guard):
    ok, reason, _ = sql_guard.validate_sql_mysql("UPDATE users SET name='y' WHERE id=1")
    assert ok is False


def test_reject_drop(sql_guard):
    ok, reason, _ = sql_guard.validate_sql_mysql("DROP TABLE users")
    assert ok is False


def test_fallback_off(monkeypatch):
    monkeypatch.setattr("tools.sql_guard._USE_CORE_GUARD", False)
    import tools.sql_guard as sg

    ok, reason, cleaned = sg.validate_sql_mysql("SELECT id FROM users")
    assert ok is True
    assert "LIMIT" in cleaned.upper()
