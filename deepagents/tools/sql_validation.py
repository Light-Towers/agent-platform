# -*- coding: utf-8 -*-
"""
SQL 校验纯函数（从 db_tools.py 抽取）。

这些函数不依赖 mysql.connector，仅供纯逻辑测试和 db_tools 复用。
"""
import re

import sqlparse
from sqlparse.sql import Statement
from sqlparse.tokens import Keyword, DML

_SAFE_IDENTIFIER = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')


def _validate_identifier(name: str) -> str:
    if not _SAFE_IDENTIFIER.match(name):
        raise ValueError(f"非法标识符：{name}")
    return name


def _validate_sql_select_only(query: str) -> str:
    stmts = sqlparse.parse(query)
    if len(stmts) != 1:
        raise ValueError("仅允许单条 SELECT 语句")
    stmt: Statement = stmts[0]
    idx, first_token = stmt.token_next(-1, skip_ws=True, skip_cm=True)
    if first_token is None or first_token.ttype is not DML or first_token.normalized.upper() != 'SELECT':
        raise ValueError(f"仅允许 SELECT 语句，检测到：{first_token.normalized if first_token else '空'}")
    return query


def _ensure_limit(query: str, default_limit: int = 100) -> str:
    if re.search(r'\bLIMIT\b', query, re.IGNORECASE):
        return query
    return query.rstrip().rstrip(';') + f' LIMIT {default_limit}'
