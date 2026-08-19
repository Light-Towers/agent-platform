# -*- coding: utf-8 -*-
"""SQL 守卫薄封装（优化 E / P4.2 / E-2）。

将 B 侧 SQL 校验统一委托到内核 ``agent_core.sql.guard.validate_sql``，
通过 ``dialect="mysql"`` 适配 wenda/MySQL 场景（内核已支持方言透传，无需新增分支）。

保留 B 原 ``_ensure_limit`` 语义（无 LIMIT 时补 100）由内核 guard 的 max_rows 兜底覆盖。
``USE_CORE_GUARD`` 开关（默认 on）用于快速回滚到原 ``sql_validation`` 实现（S-2）。
"""

import os

from tools.sql_validation import _ensure_limit, _validate_sql_select_only

_USE_CORE_GUARD = os.getenv("USE_CORE_GUARD", "on").lower() in ("1", "true", "yes", "on")

try:
    from agent_core.sql.guard import validate_sql as _core_validate_sql

    _HAS_CORE_GUARD = True
except Exception:  # pragma: no cover - 兜底：内核缺失时走本地实现
    _core_validate_sql = None
    _HAS_CORE_GUARD = False

_MYSQL_MAX_ROWS = int(os.getenv("SQL_GUARD_MAX_ROWS", "100"))


def validate_sql_mysql(sql: str) -> tuple[bool, str, str]:
    """校验单条只读 SELECT（MySQL 方言）。

    返回 (是否放行, 原因, 规整后 SQL)。
    """
    if _USE_CORE_GUARD and _HAS_CORE_GUARD:
        return _core_validate_sql(sql, dialect="mysql", max_rows=_MYSQL_MAX_ROWS)
    # 回退：原 B 侧实现（sqlparse）
    try:
        cleaned = _validate_sql_select_only(sql)
        cleaned = _ensure_limit(cleaned, default_limit=_MYSQL_MAX_ROWS)
        return True, "ok", cleaned
    except ValueError as exc:
        return False, str(exc), sql
