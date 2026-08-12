"""SQL 执行端到端：临时 sqlite 库验证只读执行与写操作拦截。"""

import sqlite3

import pytest

from app.sql.pipeline import execute_readonly, extract_sql


@pytest.fixture
def sqlite_dsn(tmp_path, monkeypatch):
    db_path = tmp_path / "demo.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE orders (region TEXT, amount INTEGER)")
    conn.executemany(
        "INSERT INTO orders VALUES (?, ?)", [("east", 100), ("west", 200), ("east", 50)]
    )
    conn.commit()
    conn.close()
    dsn = f"sqlite:///{db_path.as_posix()}"
    monkeypatch.setenv("SQL_DSN", dsn)
    from app.config import get_settings

    get_settings.cache_clear()
    yield dsn
    get_settings.cache_clear()


async def test_select_executes_readonly(sqlite_dsn):
    result = await execute_readonly("SELECT region, SUM(amount) AS total FROM orders GROUP BY region", 100)
    assert set(result["columns"]) == {"region", "total"}
    totals = dict(result["rows"])
    assert totals["east"] == 150 and totals["west"] == 200


async def test_write_rejected_at_connection_level(sqlite_dsn):
    # mode=ro 连接上执行写语句必须失败（守卫之外的第二道保险）
    with pytest.raises(Exception):
        await execute_readonly("DELETE FROM orders", 100)


def test_extract_sql_from_code_fence():
    text = "好的，SQL 如下：\n```sql\nSELECT 1\n```\n以上。"
    assert extract_sql(text) == "SELECT 1"


def test_extract_sql_plain_text():
    assert extract_sql("SELECT 2") == "SELECT 2"
