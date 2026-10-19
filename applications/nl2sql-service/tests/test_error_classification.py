# -*- coding: utf-8 -*-
"""execute_sql 执行期异常分类用例（#113：SQLSTATE 优先于字符串 needle）。

**背景**：分类原机制是 ``str(exc).lower()`` 的字符串匹配，实测两类误判——
① ``FATAL: database/role does not exist``（3D000/28P01，**连接级**）被
"does not exist" 命中归成 correctable，会被喂给模型改 SQL（改 3 轮也改不出，
还扩大注入面）；② 驱动/包装层改写异常文本即失效。
**修法**：服务端 SQLSTATE 优先（精确码 → 类前缀），字符串 needle 仅作
拿不到状态码时的回落。

钉四件事：
1. 真 psycopg 异常按 SQLSTATE 正确分类（含 3D000/28P01 的 fatal 归属）；
2. SQLSTATE 与字符串矛盾时**状态码赢**（回归 #113 本体）；
3. 无 sqlstate 的异常回落字符串规则（向后兼容不破）；
4. 未知错误按 generic fatal（不喂模型）。
"""

from __future__ import annotations

import pytest
from nl2sql_service.agent.nodes.execute_sql import (
    classify_error,
    classify_error_class,
)
from psycopg import errors as pg_errors


class _FakePgError(Exception):
    """带 sqlstate 的假异常（对齐 psycopg Error 的 .sqlstate 契约）。"""

    def __init__(self, sqlstate: str, message: str) -> None:
        super().__init__(message)
        self.sqlstate = sqlstate


@pytest.mark.parametrize(
    ("exc", "expected_class"),
    [
        # 真 psycopg 异常：sqlstate 是类属性，实例化即带状态码
        (pg_errors.UndefinedTable('relation "orders" does not exist'), "correctable"),
        (pg_errors.UndefinedColumn('column "phone" does not exist'), "correctable"),
        (pg_errors.SyntaxError("syntax error at or near SELECT"), "correctable"),
        (pg_errors.QueryCanceled("canceling statement due to statement timeout"), "rewritable"),
        (pg_errors.InsufficientPrivilege("permission denied for table orders"), "fatal"),
        (pg_errors.ConnectionFailure("connection exception"), "fatal"),
        # #113 本体：连接级"不存在"不再是 correctable
        (pg_errors.InvalidCatalogName('FATAL: database "nl2sql_dw" does not exist'), "fatal"),
        (pg_errors.InvalidPassword("FATAL: password authentication failed"), "fatal"),
    ],
)
def test_sqlstate_drives_classification(exc, expected_class):
    assert classify_error_class(exc) == expected_class


def test_sqlstate_wins_over_conflicting_string_needles():
    """状态码与字符串矛盾时状态码赢——#113 修的正是"does not exist 误归 correctable"。

    假异常的 message 刻意含 "does not exist"（旧机制的误判触发器），
    但 sqlstate=08006 ⇒ 必须按连接级 fatal 走。
    """
    exc = _FakePgError("08006", 'FATAL: database "x" does not exist')
    assert classify_error_class(exc) == "fatal"
    assert classify_error(exc) == "查询失败：数据源连接不可用"


def test_class_prefix_rule_covers_connection_exception_class():
    """08 类前缀兜底（未逐码列出的连接异常，如 08004 server refused connection）。"""
    assert classify_error_class(_FakePgError("08004", "server refused the connection")) == "fatal"


def test_string_fallback_when_no_sqlstate():
    """拿不到 sqlstate 的异常（非 PG 驱动/丢类型的包装异常）回落字符串规则。"""
    assert classify_error_class(Exception("permission denied for table orders")) == "fatal"
    assert classify_error_class(Exception("canceling statement due to statement timeout")) == "rewritable"
    assert classify_error_class(Exception("undefined column \"x\"")) == "correctable"
    assert classify_error_class(Exception("could not connect to server")) == "fatal"


def test_unknown_error_is_generic_fatal():
    """未识别错误按 fatal：不可分类原文进 prompt 只扩大注入面（S-7）。"""
    exc = Exception("something entirely unexpected")
    assert classify_error_class(exc) == "fatal"
    assert classify_error(exc) == "查询执行失败"


def test_sqlstate_case_and_whitespace_tolerant():
    """状态码大小写/空白不敏感（驱动透传的原始值）。"""
    assert classify_error_class(_FakePgError(" 42p01 ", "undefined table")) == "correctable"
