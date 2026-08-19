"""PostgresStore：生产实现（psycopg 异步 + JSONB 列存储 Tracker）。

无 MySQL 依赖；不依赖 LangGraph checkpointer（自建 Store 抽象，非 BaseCheckpointSaver）。
"""

import json

from psycopg import AsyncConnection

from dialogue_framework.core.tracker import Tracker
from dialogue_framework.shared.constants import TRACKER_TABLE_PREFIX


class PostgresStore:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def _ensure_table(self) -> None:
        async with self._conn.cursor() as cur:
            await cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {TRACKER_TABLE_PREFIX} (
                    session_id TEXT PRIMARY KEY,
                    data JSONB NOT NULL,
                    updated_at TIMESTAMPTZ DEFAULT now()
                )
                """
            )

    async def save_tracker(self, tracker: Tracker) -> None:
        await self._ensure_table()
        async with self._conn.cursor() as cur:
            await cur.execute(
                f"""
                INSERT INTO {TRACKER_TABLE_PREFIX} (session_id, data)
                VALUES (%s, %s)
                ON CONFLICT (session_id) DO UPDATE SET data = EXCLUDED.data, updated_at = now()
                """,
                (tracker.session_id, json.dumps(tracker.to_dict(), ensure_ascii=False)),
            )
        await self._conn.commit()

    async def load_tracker(self, session_id: str) -> Tracker | None:
        await self._ensure_table()
        async with self._conn.cursor() as cur:
            await cur.execute(
                f"SELECT data FROM {TRACKER_TABLE_PREFIX} WHERE session_id = %s",
                (session_id,),
            )
            row = await cur.fetchone()
        if row is None:
            return None
        return Tracker.from_dict(row[0])
