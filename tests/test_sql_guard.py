from app.sql.guard import detect_dialect, validate_sql


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
