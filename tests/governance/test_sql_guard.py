# guard 本体在 agent_core.sql.guard（平台共享件）；detect_dialect 随 agent_server/sql
# 退役迁到 agent_server.db_dialect（2026-10-18，ADR-0011 §7）
from agent_core.sql.guard import validate_sql
from agent_server.db_dialect import detect_dialect


def test_reject_non_select():
    for bad in ["DROP TABLE orders", "DELETE FROM orders", "UPDATE orders SET a=1",
                "INSERT INTO orders VALUES (1)", "CREATE TABLE x (id int)"]:
        ok, reason, _ = validate_sql(bad, "postgres", 100)
        assert not ok, bad


def test_reject_multi_statement():
    ok, reason, _ = validate_sql("SELECT 1; DROP TABLE orders", "postgres", 100)
    assert not ok
    assert "多语句" in reason


def test_limit_appended_when_missing():
    ok, reason, sql = validate_sql("SELECT * FROM orders", "postgres", 100)
    assert ok
    assert "LIMIT 100" in sql.upper()


def test_limit_capped_when_exceeding():
    ok, _, sql = validate_sql("SELECT * FROM orders LIMIT 500", "postgres", 100)
    assert ok
    assert "LIMIT 100" in sql.upper()


def test_limit_within_range_kept():
    ok, _, sql = validate_sql("SELECT * FROM orders LIMIT 10", "postgres", 100)
    assert ok
    assert "LIMIT 10" in sql.upper()


def test_cte_allowed():
    ok, _, sql = validate_sql(
        "WITH t AS (SELECT id FROM orders) SELECT * FROM t", "postgres", 100
    )
    assert ok


def test_reject_non_literal_limit():
    ok, reason, _ = validate_sql("SELECT * FROM orders LIMIT ?", "sqlite", 100)
    assert not ok


def test_detect_dialect():
    assert detect_dialect("sqlite:///demo.db") == "sqlite"
    assert detect_dialect("postgresql://u:p@h/db") == "postgres"
    assert detect_dialect("mysql://u:p@h/db") == "mysql"


def test_reject_postgres_blocking_or_privileged_functions():
    """S-11：合法 SELECT 但能阻塞连接/读服务端文件/改会话参数的函数必须拦下。"""
    for bad in [
        "SELECT pg_sleep(30)",
        "SELECT pg_catalog.pg_sleep(30)",
        "SELECT dblink('host=x', 'select 1')",
        "SELECT lo_import('/etc/passwd')",
        "SELECT set_config('statement_timeout', '0', false)",
    ]:
        ok, reason, _ = validate_sql(bad, "postgres", 100)
        assert not ok, bad
        assert "函数" in reason


def test_reject_mysql_blocking_functions():
    for bad in ["SELECT SLEEP(30)", "SELECT BENCHMARK(100000000, MD5('x'))"]:
        ok, _, _ = validate_sql(bad, "mysql", 100)
        assert not ok, bad


def test_reject_dangerous_function_families():
    """#114：家族前缀拒——逐个补精确名是打地鼠（`dblink` 精确名拦不住
    `dblink_send_query`：函数名归一后是全名匹配）。五个实测放行函数全覆盖。"""
    for bad in [
        "SELECT pg_advisory_lock(1)",
        "SELECT pg_advisory_xact_lock(2)",
        "SELECT lo_open(1, 262144)",
        "SELECT pg_ls_waldir()",
        "SELECT dblink_send_query('c', 'select 1')",
        "SELECT pg_switch_wal()",
        "SELECT pg_catalog.lo_open(1, 262144)",  # schema 限定同样归一后命中
    ]:
        ok, reason, _ = validate_sql(bad, "postgres", 100)
        assert not ok, bad
        assert "函数" in reason


def test_normal_functions_still_allowed():
    """黑名单不得误伤聚合/字符串/数值等正常函数。"""
    ok, reason, sql = validate_sql(
        "SELECT count(*), sum(amount), lower(name), round(avg(x), 2) FROM orders", "postgres", 100
    )
    assert ok, reason
    assert "LIMIT 100" in sql.upper()


# ---------------------------------------------------------------------------
# 表/列级白名单（§5.9 L2，2026-10-18）：policy=None 时老行为不变
# ---------------------------------------------------------------------------
from agent_core.sql.guard import SqlPolicy, validate_sql_with_policy


def test_policy_none_matches_plain_validate():
    """policy=None 与旧 validate_sql 逐结果一致（三服务共享件零影响）。"""
    sql = "SELECT phone FROM users"
    a = validate_sql(sql, "postgres", 100)
    b = validate_sql_with_policy(sql, "postgres", 100, None)
    assert a == b


def test_policy_rejects_unauthorized_table():
    pol = SqlPolicy(allowed_tables=frozenset({"orders"}))
    ok, reason, _ = validate_sql_with_policy("SELECT * FROM users", "postgres", 100, pol)
    assert not ok and "未授权表" in reason and "users" in reason


def test_policy_allows_authorized_table():
    pol = SqlPolicy(allowed_tables=frozenset({"orders", "users"}))
    ok, reason, _ = validate_sql_with_policy("SELECT id FROM orders", "postgres", 100, pol)
    assert ok, reason


def test_policy_rejects_sensitive_qualified_column():
    pol = SqlPolicy(sensitive_columns=frozenset({"users.phone"}))
    ok, reason, _ = validate_sql_with_policy("SELECT users.phone FROM users", "postgres", 100, pol)
    assert not ok and "敏感列" in reason and "users.phone" in reason


def test_policy_resolves_unqualified_column_single_table():
    """单表未限定列归属该表：SELECT phone FROM users 命中 users.phone。"""
    pol = SqlPolicy(sensitive_columns=frozenset({"users.phone"}))
    ok, reason, _ = validate_sql_with_policy("SELECT phone FROM users", "postgres", 100, pol)
    assert not ok and "敏感列" in reason


def test_policy_cte_name_not_treated_as_table():
    """CTE 派生表名不算未授权表（WITH t AS (...) SELECT FROM t 放行）。"""
    pol = SqlPolicy(allowed_tables=frozenset({"orders"}))
    ok, reason, _ = validate_sql_with_policy(
        "WITH t AS (SELECT id FROM orders) SELECT id FROM t", "postgres", 100, pol
    )
    assert ok, reason


def test_policy_empty_lists_behave_as_no_policy():
    """allowed/sensitive 都空 = 无策略（回退纯语句级）。"""
    ok, reason, _ = validate_sql_with_policy("SELECT phone FROM users", "postgres", 100, SqlPolicy())
    assert ok, reason


# ---------------------------------------------------------------------------
# #120：多表未限定列 / SELECT * / 别名——L2 的静默绕过路径回归
# （`SELECT phone AS p FROM a JOIN b` 曾既不拒也不脱：限定路径核不到未限定列，
#   L3 又只按结果键脱敏，别名 p 不在敏感集）
# ---------------------------------------------------------------------------
def test_policy_rejects_multi_table_unqualified_sensitive_column():
    pol = SqlPolicy(sensitive_columns=frozenset({"users.phone"}))
    ok, reason, _ = validate_sql_with_policy(
        "SELECT phone FROM users JOIN orders ON users.id = orders.user_id",
        "postgres",
        100,
        pol,
    )
    assert not ok and "多表未限定列" in reason


def test_policy_rejects_aliased_multi_table_sensitive_column():
    """#120 本体：别名不救场——`SELECT phone AS p FROM a JOIN b` 必须拒。"""
    pol = SqlPolicy(sensitive_columns=frozenset({"users.phone"}))
    ok, reason, _ = validate_sql_with_policy(
        "SELECT users.phone AS p FROM users JOIN orders ON users.id = orders.user_id",
        "postgres",
        100,
        pol,
    )
    assert not ok and "敏感列" in reason  # 限定列走主路径


def test_policy_rejects_when_sensitive_on_any_join_side():
    """任一脸命中即拒：敏感列在 JOIN 的另一侧也算。"""
    pol = SqlPolicy(sensitive_columns=frozenset({"orders.phone"}))
    ok, reason, _ = validate_sql_with_policy(
        "SELECT phone FROM users JOIN orders ON users.id = orders.user_id",
        "postgres",
        100,
        pol,
    )
    assert not ok and "多表未限定列" in reason


def test_policy_allows_multi_table_unqualified_non_sensitive_column():
    """多表未限定列但两侧都不敏感 ⇒ 放行（不误伤；猜归属的代价由配置面控制）。"""
    pol = SqlPolicy(sensitive_columns=frozenset({"users.phone"}))
    ok, reason, _ = validate_sql_with_policy(
        "SELECT amount FROM users JOIN orders ON users.id = orders.user_id",
        "postgres",
        100,
        pol,
    )
    assert ok, reason


def test_policy_rejects_star_expanding_sensitive_table():
    pol = SqlPolicy(sensitive_columns=frozenset({"users.phone"}))
    ok, reason, _ = validate_sql_with_policy(
        "SELECT * FROM users JOIN orders ON users.id = orders.user_id",
        "postgres",
        100,
        pol,
    )
    assert not ok and "SELECT *" in reason


def test_policy_allows_star_when_no_candidate_table_is_sensitive():
    """`SELECT * FROM orders`（候选表无敏感列）不误伤。"""
    pol = SqlPolicy(sensitive_columns=frozenset({"users.phone"}))
    ok, reason, _ = validate_sql_with_policy("SELECT * FROM orders", "postgres", 100, pol)
    assert ok, reason


def test_policy_star_check_needs_sensitive_policy():
    """未配敏感列时 SELECT * 逐字节老行为（policy 默认 None 的调用方零影响）。"""
    ok, reason, _ = validate_sql_with_policy(
        "SELECT * FROM users JOIN orders ON users.id = orders.user_id",
        "postgres",
        100,
        SqlPolicy(allowed_tables=frozenset({"users", "orders"})),
    )
    assert ok, reason

