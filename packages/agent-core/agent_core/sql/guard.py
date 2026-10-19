# -*- coding: utf-8 -*-
"""SQL 白名单守卫：sqlglot 解析校验，只放行单条只读 SELECT。

规则：
1. 只允许单条语句，禁止分号堆叠；
2. 语句类型必须是 SELECT（WITH 开头的 CTE 由 sqlglot 归一为 Select）；
3. 禁止 DROP/DELETE/UPDATE/INSERT/CREATE/ALTER/GRANT 等节点出现（含子查询内）；
4. 缺失 LIMIT 时强制追加 LIMIT max_rows，已有时校验不超过上限；
5. 禁止危险函数调用（`pg_sleep` 家族、`dblink`、`lo_import/lo_export`、
   `pg_read_file` 家族、`pg_terminate_backend`、`set_config`、MySQL 的
   `sleep`/`benchmark`）——它们是合法 SELECT，语句类型白名单挡不住，
   但能在只读连接上制造阻塞或改会话参数。schema 限定名（`pg_catalog.pg_sleep`）
   由 sqlglot 归一为裸函数名后同样命中。**#114 起加家族前缀拒**
   （`pg_advisory_`/`lo_`/`pg_ls_`/`dblink_`）——逐个补精确名是打地鼠；
6. （#120）表/列级策略对**多表未限定列**与 **SELECT *** 补敏感判定——
   二者曾是 L2 的静默绕过路径（见 `_unqualified_sensitive_hits` /
   `_star_sensitive_hits`）。

框架无关：sqlglot 为可选 extra ``sql``，未安装时 import 抛 ImportError。
"""

from __future__ import annotations

from dataclasses import dataclass

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

#: 合法 SELECT 但能阻塞连接 / 读写服务端文件 / 改会话参数的函数（2026-10-18 S-11）。
#: 覆盖 PG 与 MySQL 两侧最常用的 DoS 与越权面；不含聚合/字符串等正常函数。
FORBIDDEN_FUNCTIONS = frozenset(
    {
        # PostgreSQL：阻塞
        "pg_sleep",
        "pg_sleep_for",
        "pg_sleep_until",
        # PostgreSQL：外部连接（可绕过只读语义）
        "dblink",
        "dblink_exec",
        "dblink_connect",
        "dblink_disconnect",
        # PostgreSQL：服务端文件
        "lo_import",
        "lo_export",
        "pg_read_file",
        "pg_read_binary_file",
        "pg_ls_dir",
        "pg_stat_file",
        # PostgreSQL：运维面
        "pg_terminate_backend",
        "pg_cancel_backend",
        "pg_reload_conf",
        "set_config",  # 可把 statement_timeout 改回 0
        "pg_switch_wal",  # WAL 切换（#114 实测放行，运维面）
        # MySQL：阻塞
        "sleep",
        "benchmark",
    }
)

#: 危险函数**家族前缀**（#114）：这些家族的全体成员都不该由 LLM 生成的 SQL
#: 调用——逐个补精确名是打地鼠（实测 `dblink` 精确名拦不住 `dblink_send_query`：
#: 函数名归一后是全名匹配）。schema 限定名由 `_function_name` 归一后同样受益。
FORBIDDEN_FUNCTION_PREFIXES = (
    "pg_advisory_",  # 咨询锁：会话级持有 ⇒ DoS（pg_advisory_lock 实测放行）
    "lo_",  # 大对象读写（lo_open 实测放行）
    "pg_ls_",  # 目录列举（pg_ls_waldir 实测放行）
    "dblink_",  # 外部连接（可绕过只读语义）
)


def _function_name(node: exp.Func) -> str:
    """取函数名（小写、去 schema 前缀）；专用节点回落类名。"""
    if isinstance(node, exp.Anonymous):
        raw = node.this
        name = raw if isinstance(raw, str) else getattr(raw, "name", "")
        return str(name).rsplit(".", 1)[-1].lower()
    return type(node).__name__.lower()


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
        if isinstance(node, exp.Func):
            name = _function_name(node)
            if name in FORBIDDEN_FUNCTIONS or name.startswith(FORBIDDEN_FUNCTION_PREFIXES):
                return False, f"包含禁止的函数调用: {name}", sql

    limit = stmt.args.get("limit")
    if limit is None:
        stmt = stmt.limit(max_rows)
    else:
        limit_expr = limit.expression
        if isinstance(limit_expr, exp.Literal) and limit_expr.is_int:
            if int(limit_expr.this) > max_rows:
                stmt = stmt.limit(max_rows)
        else:
            return False, "LIMIT 必须是整数字面量", sql

    return True, "ok", stmt.sql(dialect=dialect)


# ---------------------------------------------------------------------------
# 生成期表/列级白名单（§5.9 L2 纵深防御，2026-10-18）
#
# 语句级白名单（上面那只）不看查了哪些表、SELECT 列表有哪些列。L2 在其上叠加
# 可选的表/列策略：把 LLM 生成的 SQL 与授权表清单、敏感列清单比对，幻觉出的
# 敏感表名 / 敏感列在**生成期**就被拒，而不是等到执行期报错或结果外泄。
#
# 定位是纵深防御的一层：LLM 生成的是自由文本，应用层拦截天然是黑名单对抗，
# 漏一个模式就是全量泄露。第一道永远是 L1（账号 GRANT + 脱敏视图，DB 侧）；
# L2 挡"模型幻觉"，L3 做结果层投影。三者叠加，任一被绕过都还有另一道。
#
# 向后兼容：policy=None（默认）时行为与旧版逐字节一致——三服务共享本组件，
# 未配策略的调用方零影响。
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SqlPolicy:
    """表/列级授权策略。

    - `allowed_tables`：授权表名集合（小写）。None/空 = 不校验表（老行为）。
    - `sensitive_columns`：敏感列全限定名集合（小写，`table.column`）。
      None/空 = 不校验列。
    """

    allowed_tables: frozenset[str] | None = None
    sensitive_columns: frozenset[str] | None = None


def _cte_names(stmt: exp.Select) -> set[str]:
    """收集 WITH 子句里的 CTE 别名（小写）——它们是派生表，不是真实表，校验要排除。"""
    names: set[str] = set()
    for with_clause in stmt.find_all(exp.With):
        for cte in with_clause.expressions:
            alias = cte.alias
            if alias:
                names.add(alias.lower())
    return names


def _real_tables(stmt: exp.Select) -> set[str]:
    """语句引用的真实表名（小写；排除 CTE 派生表）。"""
    cte = _cte_names(stmt)
    return {t.name.lower() for t in stmt.find_all(exp.Table) if t.name and t.name.lower() not in cte}


def _referenced_columns(stmt: exp.Select) -> set[str]:
    """语句显式引用的列，尽量补全为 `table.column`（小写）。

    - 限定列直接用限定符；
    - 未限定列：仅当只有一个真实表时归属该表（`SELECT phone FROM users`），
      多表时不猜（歧义列跳过——猜错就是把 A 列当 B 列核）；多表未限定列的
      敏感判定走 `_unqualified_sensitive_hits`（#120）；
    - `SELECT *` / 计算列不含可解析列名，自然不进集合（无 schema 不展开）；
      星号的敏感判定走 `_star_sensitive_hits`（#120）。
    """
    tables = _real_tables(stmt)
    single = next(iter(tables)) if len(tables) == 1 else ""
    cols: set[str] = set()
    for col in stmt.find_all(exp.Column):
        qualifier = col.table
        name = col.name
        if not name:
            continue
        if qualifier:
            cols.add(f"{str(qualifier).lower()}.{name.lower()}")
        elif single:
            cols.add(f"{single}.{name.lower()}")
    return cols


def _unqualified_sensitive_hits(stmt: exp.Select, sensitive: frozenset[str]) -> set[str]:
    """多表未限定列：在**任一**候选表里是敏感列即命中（#120）。

    单表未限定列已由 `_referenced_columns` 补全归属；多表时不猜归属（猜错就是
    把 A 列当 B 列核），但敏感判定不能靠猜——A/B 都有 `phone` 时
    `SELECT phone FROM a JOIN b` 放行即泄露 ⇒ 任一脸命中即拒。误杀面由
    `sensitive_columns` 配置控制（策略面，不是代码面）。
    """
    tables = _real_tables(stmt)
    if len(tables) < 2:
        return set()
    hits: set[str] = set()
    for col in stmt.find_all(exp.Column):
        if col.table:
            continue  # 限定列由 _referenced_columns 主路径核
        name = col.name.lower()
        if name and any(f"{t}.{name}" in sensitive for t in tables):
            hits.add(name)
    return hits


def _star_sensitive_hits(stmt: exp.Select, sensitive: frozenset[str]) -> set[str]:
    """`SELECT *` 且任一候选表带敏感列 ⇒ 命中该表（#120）。

    星号展开不可静态核（无 schema 不展开）⇒ 只要候选表里有敏感列就拒；
    候选表全干净时放行（`SELECT * FROM orders` 无敏感列 ⇒ 不误伤）。
    """
    if not list(stmt.find_all(exp.Star)):
        return set()
    return {t for t in _real_tables(stmt) if any(c.startswith(f"{t}.") for c in sensitive)}


def check_policy(stmt: exp.Select, policy: SqlPolicy) -> str:
    """表/列白名单校验；合规返回 ""，否则返回可读拒绝原因。"""
    if policy.allowed_tables:
        unauthorized = _real_tables(stmt) - policy.allowed_tables
        if unauthorized:
            return "查询涉及未授权表: " + ", ".join(sorted(unauthorized))
    if policy.sensitive_columns:
        hit = _referenced_columns(stmt) & policy.sensitive_columns
        if hit:
            return "查询涉及敏感列: " + ", ".join(sorted(hit))
        # #120：多表未限定列与 SELECT * 曾是 L2 的两条静默绕过路径
        # （`SELECT phone AS p FROM a JOIN b` 既不拒也不脱——限定路径核不到
        # 未限定列，L3 又只按结果键脱敏，别名 p 不在敏感集）。
        unqualified = _unqualified_sensitive_hits(stmt, policy.sensitive_columns)
        if unqualified:
            return "查询涉及敏感列（多表未限定列，任一脸命中即拒）: " + ", ".join(sorted(unqualified))
        star = _star_sensitive_hits(stmt, policy.sensitive_columns)
        if star:
            return "SELECT * 展开含敏感列的表: " + ", ".join(sorted(star))
    return ""


def validate_sql_with_policy(
    sql: str, dialect: str, max_rows: int, policy: SqlPolicy | None = None
) -> tuple[bool, str, str]:
    """语句级白名单 + 表/列级策略（§5.9 L2）。policy=None 时等同 validate_sql。"""
    ok, reason, normalized = validate_sql(sql, dialect, max_rows)
    if not ok or policy is None:
        return ok, reason, normalized
    try:
        statements = [s for s in sqlglot.parse(normalized, read=dialect) if s is not None]
    except sqlglot.errors.ParseError:
        return ok, reason, normalized
    if len(statements) == 1 and isinstance(statements[0], exp.Select):
        policy_reason = check_policy(statements[0], policy)
        if policy_reason:
            return False, policy_reason, sql
    return ok, reason, normalized


__all__ = [
    "FORBIDDEN_FUNCTION_PREFIXES",
    "FORBIDDEN_FUNCTIONS",
    "FORBIDDEN_NODES",
    "SqlPolicy",
    "check_policy",
    "validate_sql",
    "validate_sql_with_policy",
]
