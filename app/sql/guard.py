"""SQL 白名单守卫：sqlglot 解析校验，只放行单条只读 SELECT。

规则（MVP）：
1. 只允许单条语句，禁止分号堆叠；
2. 语句类型必须是 SELECT（WITH 开头的 CTE 由 sqlglot 归一为 Select）；
3. 禁止 DROP/DELETE/UPDATE/INSERT/CREATE/ALTER/GRANT 等节点出现（含子查询内）；
4. 缺失 LIMIT 时强制追加 LIMIT max_rows，已有时校验不超过上限。
"""

import sqlglot
from sqlglot import exp

FORBIDDEN_NODES = (
    exp.Drop,
    exp.Delete,
    exp.Update,
    exp.Insert,
    exp.Create,
    exp.Alter,
    exp.Command,
    exp.Transaction,
    exp.Commit,
    exp.Rollback,
    exp.Set,
    exp.Into,  # SELECT ... INTO
)


def detect_dialect(dsn: str) -> str:
    if dsn.startswith("sqlite"):
        return "sqlite"
    if dsn.startswith("postgres"):
        return "postgres"
    if dsn.startswith("mysql"):
        return "mysql"
    return "postgres"


def validate_sql(sql: str, dialect: str, max_rows: int) -> tuple[bool, str, str]:
    """返回 (是否放行, 原因, 规整后的 SQL)。"""
    cleaned = sql.strip().rstrip(";").strip()
    if not cleaned:
        return False, "空 SQL", sql
    if ";" in cleaned:
        return False, "禁止多语句", sql

    try:
        statements = [s for s in sqlglot.parse(cleaned, read=dialect) if s is not None]
    except sqlglot.errors.ParseError as exc:
        return False, f"SQL 解析失败: {exc}", sql
    if len(statements) != 1:
        return False, "只允许单条语句", sql

    stmt = statements[0]
    if not isinstance(stmt, exp.Select):
        return False, "只允许 SELECT 查询", sql
    for node in stmt.walk():
        if isinstance(node, FORBIDDEN_NODES):
            return False, f"包含禁止的 SQL 操作: {type(node).__name__}", sql

    limit = stmt.args.get("limit")
    if limit is None:
        stmt = stmt.limit(max_rows)
    else:
        limit_expr = limit.expression
        if isinstance(limit_expr, exp.Literal) and limit_expr.is_int:
            if int(limit_expr.this) > max_rows:
                stmt = stmt.limit(max_rows)
        # 非字面量 LIMIT（变量等）保守拒绝
        else:
            return False, "LIMIT 必须是整数字面量", sql

    return True, "ok", stmt.sql(dialect=dialect)
