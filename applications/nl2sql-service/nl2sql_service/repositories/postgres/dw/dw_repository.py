"""业务数仓 Postgres 仓储：只读执行 + 只读探针。

2026-10-18（P0-9）：`execute_probe` 是取值匹配探针的**唯一**执行形态——
带 per-statement 超时（事务内 `SET LOCAL`，退出即撤，不污染池连接）、
取连接超时、以及和 `execute_readonly` 相同的只读语义。探针与普通查询
分两个方法，是为了让"探针预算"（C7：LIMIT + 超时 + 信号量）有单一落点。
"""

from typing import Any

from agent_core.logging import get_logger

logger = get_logger(__name__)


class DwRepository:
    """业务数仓只读仓储。"""

    def __init__(self, pool=None) -> None:
        self._pool = pool

    async def execute_readonly(self, sql: str, params: tuple | None = None) -> list[dict[str, Any]]:
        async with self._pool.connection() as conn:
            await conn.execute("SET default_transaction_read_only = on")
            cur = await conn.execute(sql, params)
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    async def execute_probe(
        self,
        sql: str,
        params: tuple | None = None,
        statement_timeout_ms: int = 2000,
        connect_timeout: float = 2.0,
    ) -> list[dict[str, Any]]:
        """只读探针执行：短语句超时 + 短取连接超时，超时即抛（上层降级）。

        语句超时走**事务内 SET LOCAL**：会话级 `SET statement_timeout` 会
        留在池连接上污染后续查询（C7 的预算必须探针独享、退出即撤）。

        2026-10-18 真库实测抓出的 bug（golden 首跑暴露）：`SET LOCAL` 是 PG
        **工具命令，不接受绑定参数**——`SET LOCAL statement_timeout = %s` 带参
        直接被服务端拒（`syntax error at or near "$1"`），配了 linkable 的部署
        里探针从来没成功跑过（假池不校验 PG 的参数化规则，故单测全绿）。
        修法：int 强转 + 非负校验后**内联进 SQL 文本**（值来自配置而非用户
        输入，无注入面；%s 形式在这个位置根本不可能合法）。
        """
        timeout_ms = int(statement_timeout_ms)
        if timeout_ms < 0:
            raise ValueError(f"statement_timeout_ms 必须非负: {statement_timeout_ms}")
        async with self._pool.connection(timeout=connect_timeout) as conn:
            async with conn.transaction():
                await conn.execute(f"SET LOCAL statement_timeout = {timeout_ms}")
                cur = await conn.execute(sql, params)
                rows = await cur.fetchall()
                return [dict(r) for r in rows]

    async def get_table_schema(self, table_name: str) -> list[dict[str, Any]]:
        sql = (
            "SELECT column_name, data_type, column_comment "
            "FROM information_schema.columns "
            "WHERE table_name = %s ORDER BY ordinal_position"
        )
        return await self.execute_readonly(sql, (table_name,))

    async def list_tables(self, schema: str = "public") -> list[dict[str, Any]]:
        sql = (
            "SELECT table_name, obj_description((quote_ident(table_schema)||'.'||quote_ident(table_name))::regclass) as table_comment "
            "FROM information_schema.tables WHERE table_schema = %s"
        )
        return await self.execute_readonly(sql, (schema,))
