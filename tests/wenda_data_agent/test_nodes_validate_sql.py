"""守卫节点测试（复用 app/sql/guard 语义）。"""


from wenda_data_agent.agent.nodes.validate_sql import validate_sql


async def test_valid_select_passes():
    state = {"sql": "SELECT * FROM orders LIMIT 10", "sql_max_rows": 1000}
    result = await validate_sql(state)
    assert result["sql_valid"] is True


async def test_delete_rejected():
    state = {"sql": "DELETE FROM users", "sql_max_rows": 1000}
    result = await validate_sql(state)
    assert result["sql_valid"] is False
    assert "SELECT" in result["error"]


async def test_multi_statement_rejected():
    state = {"sql": "SELECT 1; SELECT 2", "sql_max_rows": 1000}
    result = await validate_sql(state)
    assert result["sql_valid"] is False


async def test_drop_rejected():
    state = {"sql": "DROP TABLE users", "sql_max_rows": 1000}
    result = await validate_sql(state)
    assert result["sql_valid"] is False


async def test_limit_enforced():
    state = {"sql": "SELECT * FROM orders", "sql_max_rows": 100}
    result = await validate_sql(state)
    assert result["sql_valid"] is True
    assert "LIMIT 100" in result["sql"]


async def test_limit_capped():
    state = {"sql": "SELECT * FROM orders LIMIT 9999", "sql_max_rows": 100}
    result = await validate_sql(state)
    assert result["sql_valid"] is True
    assert "LIMIT 100" in result["sql"]


async def test_empty_sql_rejected():
    state = {"sql": "", "sql_max_rows": 1000}
    result = await validate_sql(state)
    assert result["sql_valid"] is False
