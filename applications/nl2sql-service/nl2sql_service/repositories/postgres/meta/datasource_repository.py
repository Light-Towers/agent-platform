"""部署级数据源注册表仓储（G3 刀 3）。

表 `nl2sql_datasources` 是部署级（P4 拍板）：全企业共享，不按 tenant/workspace 分片。
CRUD 全部参数化（列名仅来自本模块常量，值全参数化，禁止拼接）；credential_ref
只存引用名，本层绝不接触口令形状。

注意 001 是唯一真相源：本文件的列清单/表名必须与 007_datasources.up.sql 逐字对齐。
"""
from __future__ import annotations

from typing import Any

from agent_core.logging import get_logger
from agent_core.sql.identifiers import validate_identifier

logger = get_logger(__name__)


class DataSourceRepository:
    """datasources 表仓储：列出/读取/创建/更新/设默认。"""

    def __init__(self, pool=None, table_prefix: str = "nl2sql_") -> None:
        # 表前缀来自配置，与表名一样是外部输入：构造期校验，非法前缀在第一次查询前就炸。
        validate_identifier(table_prefix, "数据源表前缀")
        self._pool = pool
        self._prefix = table_prefix

    @property
    def _table(self) -> str:
        return f"{self._prefix}datasources"

    _COLUMNS = (
        "id", "label", "dialect", "scope_label", "credential_ref",
        "is_default", "status", "updated_by", "updated_at",
    )

    def _select(self) -> str:
        return (
            f"SELECT {', '.join(self._COLUMNS)} FROM {self._table}"
        )

    async def list_datasources(self) -> list[dict[str, Any]]:
        """列出全部数据源（默认源在前，便于前端置顶）。"""
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"{self._select()} ORDER BY is_default DESC, id ASC"
            )
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    async def get_datasource(self, ds_id: str) -> dict[str, Any] | None:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"{self._select()} WHERE id = %s", (ds_id,)
            )
            row = await cur.fetchone()
            return dict(row) if row is not None else None

    async def create_datasource(
        self, data: dict[str, Any], updated_by: str = ""
    ) -> dict[str, Any]:
        """插入一行；id 与 credential_ref 必填（调用方已校验）。"""
        params = (
            data["id"],
            data.get("label", ""),
            data.get("dialect", "postgres"),
            data.get("scope_label", ""),
            data["credential_ref"],
            bool(data.get("is_default", False)),
            data.get("status", "active"),
            updated_by,
        )
        sql = (
            f"INSERT INTO {self._table} "
            f"(id, label, dialect, scope_label, credential_ref, is_default, status, updated_by, updated_at) "
            f"VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now()) "
            f"RETURNING {', '.join(self._COLUMNS)}"
        )
        async with self._pool.connection() as conn:
            cur = await conn.execute(sql, params)
            row = await cur.fetchone()
            return dict(row)

    async def update_datasource(
        self, ds_id: str, data: dict[str, Any], updated_by: str = ""
    ) -> dict[str, Any] | None:
        """按白名单更新可写列（label/dialect/scope_label/credential_ref/status）。"""
        whitelist = {
            "label": data.get("label"),
            "dialect": data.get("dialect"),
            "scope_label": data.get("scope_label"),
            "credential_ref": data.get("credential_ref"),
            "status": data.get("status"),
        }
        whitelist = {k: v for k, v in whitelist.items() if v is not None}
        if not whitelist:
            return await self.get_datasource(ds_id)
        set_clause = ", ".join(f"{k} = %s" for k in whitelist)
        params = list(whitelist.values()) + [updated_by, ds_id]
        sql = (
            f"UPDATE {self._table} SET {set_clause}, updated_by = %s, updated_at = now() "
            f"WHERE id = %s RETURNING {', '.join(self._COLUMNS)}"
        )
        async with self._pool.connection() as conn:
            cur = await conn.execute(sql, params)
            row = await cur.fetchone()
            return dict(row) if row is not None else None

    async def set_default(self, ds_id: str, updated_by: str = "") -> None:
        """把目标源设为唯一默认源（部分唯一索引约束下，先清旧默认再置新）。

        两步在同一连接事务内（pool.connection 即一事务），原子性由事务保证。
        """
        async with self._pool.connection() as conn:
            await conn.execute(
                f"UPDATE {self._table} SET is_default = false, updated_at = now() "
                f"WHERE is_default = true"
            )
            await conn.execute(
                f"UPDATE {self._table} SET is_default = true, updated_by = %s, updated_at = now() "
                f"WHERE id = %s",
                (updated_by, ds_id),
            )
