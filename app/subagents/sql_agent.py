"""SQL 子能力：Vanna 式管线封装为图节点可调用的证据生产者。"""

from app.sql.pipeline import format_result, text_to_sql


async def sql_query(query: str, llm=None) -> list[str]:
    from agent_runtime.db import get_pool

    payload = await text_to_sql(get_pool(), query, llm=llm)
    return [format_result(payload)]
