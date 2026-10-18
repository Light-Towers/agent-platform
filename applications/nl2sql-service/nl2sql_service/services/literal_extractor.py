"""SQL 字面量抽取（P0-8② 的机器可读判据来源）。

用 sqlglot AST（不是正则）从生成的 SQL 里抽 `(表, 列, 字面量)` 三元组：
- 比较符 `col = 'x'` 与 `col IN ('x','y')` 都覆盖；
- 表名走**作用域解析**：限定列用限定符，未限定列在 FROM 只有一张表时
  归该表，多表歧义时跳过（不猜——猜错就是拿 A 列的值去核 B 列）；
- 只抽字符串字面量（取值匹配的语义对象）；数字/参数不抽。

同时给出"是否带维度过滤"（存在字符串字面量比较即视为有）——零结果分诊
（P0-8③）只在有维度过滤时才值得跑。
"""

from __future__ import annotations

from typing import Any

import sqlglot
from sqlglot import exp

from nl2sql_service.services.value_resolver import LiteralProbe


def _table_scope(stmt: exp.Select) -> dict[str, str]:
    """别名/表名 → 真实表名（FROM 与 JOIN 都算；无别名时表名自身）。"""
    scope: dict[str, str] = {}
    for table in stmt.find_all(exp.Table):
        name = table.name
        if not name:
            continue
        scope[name.lower()] = name
        alias = table.alias
        if alias:
            scope[alias.lower()] = name
    return scope


def _unquote_literal(literal: exp.Literal) -> str:
    """sqlglot 的字符串字面量 this 带引号（如 '已支付'），取值需去引号。

    仅去除成对的首尾引号；非引号包裹（理论上不会发生）原样返回。
    """
    raw = literal.this
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ("'", '"'):
        return raw[1:-1]
    return raw


def _resolve_table(column: exp.Column, scope: dict[str, str], from_tables: list[str]) -> str:
    # sqlglot 的 Column.table 在未限定时返回空串、限定时可能是 str 或 Table 对象
    table_expr = column.table
    if isinstance(table_expr, str):
        qualifier = table_expr.lower()
    elif table_expr:
        qualifier = str(table_expr.name).lower()
    else:
        qualifier = ""
    if qualifier and qualifier in scope:
        return scope[qualifier]
    if not qualifier and len(from_tables) == 1:
        return from_tables[0]
    return ""


def extract_literals(sql: str, dialect: str = "postgres") -> tuple[list[LiteralProbe], bool]:
    """返回 ((表, 列, 字面量) 列表, 是否带维度过滤)。解析失败返回 ([], False)。"""
    if not sql or not sql.strip():
        return [], False
    try:
        statements = [s for s in sqlglot.parse(sql, read=dialect) if s is not None]
    except sqlglot.errors.ParseError:
        return [], False
    if len(statements) != 1 or not isinstance(statements[0], exp.Select):
        return [], False
    stmt = statements[0]

    scope = _table_scope(stmt)
    from_tables = [t.name for t in stmt.find_all(exp.Table) if t.name]

    probes: list[LiteralProbe] = []
    seen: set[tuple[str, str, str]] = set()
    for node in stmt.walk():
        if not isinstance(node, (exp.EQ, exp.In)):
            continue
        column = node.this if isinstance(node.this, exp.Column) else None
        if column is None:
            continue
        table = _resolve_table(column, scope, from_tables)
        if not table:
            continue
        column_name = column.name
        literals: list[Any]
        if isinstance(node, exp.EQ):
            literals = [node.expression]
        else:
            literals = list(node.expressions or [])
        for literal in literals:
            if not isinstance(literal, exp.Literal) or not literal.is_string:
                continue
            key = (table, column_name, literal.this)
            if key in seen:
                continue
            seen.add(key)
            probes.append(LiteralProbe(table=table, column=column_name, literal=_unquote_literal(literal)))
    return probes, bool(probes)
