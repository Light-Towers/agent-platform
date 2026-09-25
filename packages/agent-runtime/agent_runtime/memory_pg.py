"""Episodic + Procedural Memory PG 持久化后端。

给四类 Memory 的 Episodic 和 Procedural 提供 PG 后端实现，
替换 InMemory store，使重启不丢。
"""

from __future__ import annotations

import json
import time
from typing import Any

from agent_runtime.episodic_memory import Episode, EpisodeOutcome, EpisodicStore
from agent_runtime.procedural_memory import ProceduralEntry, ProceduralStore


class PgEpisodicStore(EpisodicStore):
    """PG 持久化 Episodic Memory：episodic_memories 表。"""

    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def save(self, episode: Episode) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                "INSERT INTO episodic_memories "
                "(episode_id, execution_id, task_summary, outcome, key_steps, "
                " lessons, skill_names, total_tokens, total_cost, duration, "
                " importance, created_at, metadata) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (episode_id) DO UPDATE SET "
                " task_summary = EXCLUDED.task_summary, "
                " outcome = EXCLUDED.outcome, "
                " key_steps = EXCLUDED.key_steps, "
                " lessons = EXCLUDED.lessons, "
                " skill_names = EXCLUDED.skill_names, "
                " importance = EXCLUDED.importance, "
                " metadata = EXCLUDED.metadata",
                (
                    episode.episode_id,
                    episode.execution_id,
                    episode.task_summary,
                    episode.outcome.value,
                    json.dumps(episode.key_steps),
                    json.dumps(episode.lessons),
                    json.dumps(episode.skill_names),
                    episode.total_tokens,
                    episode.total_cost,
                    episode.duration,
                    episode.importance,
                    episode.created_at,
                    json.dumps(episode.metadata),
                ),
            )

    async def recall(self, query: str, top_k: int = 10) -> list[Episode]:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT episode_id, execution_id, task_summary, outcome, key_steps, "
                "       lessons, skill_names, total_tokens, total_cost, duration, "
                "       importance, created_at, metadata "
                "FROM episodic_memories "
                "WHERE task_summary ILIKE %s OR key_steps::text ILIKE %s "
                "ORDER BY importance DESC LIMIT %s",
                (f"%{query}%", f"%{query}%", top_k),
            )
            rows = await cur.fetchall()
            return [self._row_to_episode(r) for r in rows]

    async def get(self, episode_id: str) -> Episode | None:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT episode_id, execution_id, task_summary, outcome, key_steps, "
                "       lessons, skill_names, total_tokens, total_cost, duration, "
                "       importance, created_at, metadata "
                "FROM episodic_memories WHERE episode_id = %s",
                (episode_id,),
            )
            row = await cur.fetchone()
            return self._row_to_episode(row) if row else None

    async def list_by_execution(self, execution_id: str) -> list[Episode]:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT episode_id, execution_id, task_summary, outcome, key_steps, "
                "       lessons, skill_names, total_tokens, total_cost, duration, "
                "       importance, created_at, metadata "
                "FROM episodic_memories WHERE execution_id = %s "
                "ORDER BY created_at DESC",
                (execution_id,),
            )
            rows = await cur.fetchall()
            return [self._row_to_episode(r) for r in rows]

    async def list_all(self, limit: int = 10000) -> list[Episode]:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT episode_id, execution_id, task_summary, outcome, key_steps, "
                "       lessons, skill_names, total_tokens, total_cost, duration, "
                "       importance, created_at, metadata "
                "FROM episodic_memories ORDER BY created_at DESC LIMIT %s",
                (limit,),
            )
            rows = await cur.fetchall()
            return [self._row_to_episode(r) for r in rows]

    async def delete(self, episode_id: str) -> bool:
        async with self._pool.connection() as conn:
            result = await conn.execute(
                "DELETE FROM episodic_memories WHERE episode_id = %s",
                (episode_id,),
            )
            return (result.rowcount if hasattr(result, "rowcount") else 0) > 0

    @staticmethod
    def _row_to_episode(row: tuple) -> Episode:
        return Episode(
            episode_id=row[0],
            execution_id=row[1],
            task_summary=row[2],
            outcome=EpisodeOutcome(row[3]),
            key_steps=json.loads(row[4]) if row[4] else [],
            lessons=json.loads(row[5]) if row[5] else [],
            skill_names=json.loads(row[6]) if row[6] else [],
            total_tokens=row[7],
            total_cost=row[8],
            duration=row[9],
            importance=row[10],
            created_at=row[11],
            metadata=json.loads(row[12]) if row[12] else {},
        )


class PgProceduralStore(ProceduralStore):
    """PG 持久化 Procedural Memory：procedural_memories 表。"""

    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def save(self, entry: ProceduralEntry) -> None:
        now = time.time()
        async with self._pool.connection() as conn:
            await conn.execute(
                "INSERT INTO procedural_memories "
                "(name, version, kind, description, input_schema, output_schema, "
                " effect_contract, lifecycle, definition, created_at, updated_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (name, version) DO UPDATE SET "
                " kind = EXCLUDED.kind, "
                " description = EXCLUDED.description, "
                " input_schema = EXCLUDED.input_schema, "
                " output_schema = EXCLUDED.output_schema, "
                " effect_contract = EXCLUDED.effect_contract, "
                " lifecycle = EXCLUDED.lifecycle, "
                " definition = EXCLUDED.definition, "
                " updated_at = EXCLUDED.updated_at",
                (
                    entry.name,
                    entry.version,
                    entry.kind,
                    entry.description,
                    json.dumps(entry.input_schema) if entry.input_schema else None,
                    json.dumps(entry.output_schema) if entry.output_schema else None,
                    json.dumps(entry.effect_contract) if entry.effect_contract else None,
                    entry.lifecycle,
                    json.dumps(entry.definition),
                    entry.created_at,
                    now,
                ),
            )

    async def load(
        self, name: str, version: str | None = None
    ) -> ProceduralEntry | None:
        if version is not None:
            async with self._pool.connection() as conn:
                cur = await conn.execute(
                    "SELECT name, version, kind, description, input_schema, "
                    "       output_schema, effect_contract, lifecycle, definition, "
                    "       created_at, updated_at "
                    "FROM procedural_memories WHERE name = %s AND version = %s",
                    (name, version),
                )
                row = await cur.fetchone()
                return self._row_to_entry(row) if row else None

        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT name, version, kind, description, input_schema, "
                "       output_schema, effect_contract, lifecycle, definition, "
                "       created_at, updated_at "
                "FROM procedural_memories WHERE name = %s "
                "ORDER BY "
                "  CASE lifecycle WHEN 'stable' THEN 0 ELSE 1 END, "
                "  version DESC "
                "LIMIT 1",
                (name,),
            )
            row = await cur.fetchone()
            return self._row_to_entry(row) if row else None

    async def list_all(self) -> list[ProceduralEntry]:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT name, version, kind, description, input_schema, "
                "       output_schema, effect_contract, lifecycle, definition, "
                "       created_at, updated_at "
                "FROM procedural_memories ORDER BY name, version DESC"
            )
            rows = await cur.fetchall()
            return [self._row_to_entry(r) for r in rows]

    async def list_by_name(self, name: str) -> list[ProceduralEntry]:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT name, version, kind, description, input_schema, "
                "       output_schema, effect_contract, lifecycle, definition, "
                "       created_at, updated_at "
                "FROM procedural_memories WHERE name = %s ORDER BY version DESC",
                (name,),
            )
            rows = await cur.fetchall()
            return [self._row_to_entry(r) for r in rows]

    async def delete(self, name: str, version: str) -> bool:
        async with self._pool.connection() as conn:
            result = await conn.execute(
                "DELETE FROM procedural_memories WHERE name = %s AND version = %s",
                (name, version),
            )
            return (result.rowcount if hasattr(result, "rowcount") else 0) > 0

    @staticmethod
    def _row_to_entry(row: tuple) -> ProceduralEntry:
        return ProceduralEntry(
            name=row[0],
            version=row[1],
            kind=row[2],
            description=row[3],
            input_schema=json.loads(row[4]) if row[4] else None,
            output_schema=json.loads(row[5]) if row[5] else None,
            effect_contract=json.loads(row[6]) if row[6] else None,
            lifecycle=row[7],
            definition=json.loads(row[8]) if row[8] else {},
            created_at=row[9],
            updated_at=row[10],
        )


__all__ = [
    "PgEpisodicStore",
    "PgProceduralStore",
]
