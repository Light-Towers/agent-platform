"""Episodic + Procedural Memory PG 持久化后端。

给四类 Memory 的 Episodic 和 Procedural 提供 PG 后端实现，
替换 InMemory store，使重启不丢。
"""

from __future__ import annotations

import json
import time
from typing import Any

from agent_core.memory._tenant_gate import _TENANT_UNSET, resolve_tenant

from agent_runtime.episodic_memory import Episode, EpisodeOutcome, EpisodicStore
from agent_runtime.procedural_memory import ProceduralEntry, ProceduralStore


class PgEpisodicStore(EpisodicStore):
    """PG 持久化 Episodic Memory：episodic_memories 表。"""

    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def save(self, episode: Episode, *, tenant_id: str = _TENANT_UNSET) -> None:
        tenant = resolve_tenant(tenant_id)
        async with self._pool.connection() as conn:
            await conn.execute(
                "INSERT INTO episodic_memories "
                "(tenant_id, episode_id, execution_id, task_summary, outcome, key_steps, "
                " lessons, skill_names, total_tokens, total_cost, duration, "
                " importance, created_at, metadata) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (episode_id) DO UPDATE SET "
                " task_summary = EXCLUDED.task_summary, "
                " outcome = EXCLUDED.outcome, "
                " key_steps = EXCLUDED.key_steps, "
                " lessons = EXCLUDED.lessons, "
                " skill_names = EXCLUDED.skill_names, "
                " importance = EXCLUDED.importance, "
                " metadata = EXCLUDED.metadata",
                (
                    tenant,
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

    async def recall(
        self, query: str, top_k: int = 10, *, tenant_id: str = _TENANT_UNSET
    ) -> list[Episode]:
        tenant = resolve_tenant(tenant_id)
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT episode_id, execution_id, task_summary, outcome, key_steps, "
                "       lessons, skill_names, total_tokens, total_cost, duration, "
                "       importance, created_at, metadata "
                "FROM episodic_memories "
                "WHERE tenant_id = %s AND (task_summary ILIKE %s OR key_steps::text ILIKE %s) "
                "ORDER BY importance DESC LIMIT %s",
                (tenant, f"%{query}%", f"%{query}%", top_k),
            )
            rows = await cur.fetchall()
            return [self._row_to_episode(r) for r in rows]

    async def get(self, episode_id: str, *, tenant_id: str = _TENANT_UNSET) -> Episode | None:
        tenant = resolve_tenant(tenant_id)
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT episode_id, execution_id, task_summary, outcome, key_steps, "
                "       lessons, skill_names, total_tokens, total_cost, duration, "
                "       importance, created_at, metadata "
                "FROM episodic_memories WHERE episode_id = %s AND tenant_id = %s",
                (episode_id, tenant),
            )
            row = await cur.fetchone()
            return self._row_to_episode(row) if row else None

    async def list_by_execution(
        self, execution_id: str, *, tenant_id: str = _TENANT_UNSET
    ) -> list[Episode]:
        tenant = resolve_tenant(tenant_id)
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT episode_id, execution_id, task_summary, outcome, key_steps, "
                "       lessons, skill_names, total_tokens, total_cost, duration, "
                "       importance, created_at, metadata "
                "FROM episodic_memories WHERE execution_id = %s AND tenant_id = %s "
                "ORDER BY created_at DESC",
                (execution_id, tenant),
            )
            rows = await cur.fetchall()
            return [self._row_to_episode(r) for r in rows]

    async def list_all(
        self, limit: int = 10000, *, tenant_id: str = _TENANT_UNSET
    ) -> list[Episode]:
        tenant = resolve_tenant(tenant_id)
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT episode_id, execution_id, task_summary, outcome, key_steps, "
                "       lessons, skill_names, total_tokens, total_cost, duration, "
                "       importance, created_at, metadata "
                "FROM episodic_memories WHERE tenant_id = %s "
                "ORDER BY created_at DESC LIMIT %s",
                (tenant, limit),
            )
            rows = await cur.fetchall()
            return [self._row_to_episode(r) for r in rows]

    async def delete(self, episode_id: str, *, tenant_id: str = _TENANT_UNSET) -> bool:
        tenant = resolve_tenant(tenant_id)
        async with self._pool.connection() as conn:
            result = await conn.execute(
                "DELETE FROM episodic_memories WHERE episode_id = %s AND tenant_id = %s",
                (episode_id, tenant),
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

    async def save(self, entry: ProceduralEntry, *, tenant_id: str = _TENANT_UNSET) -> None:
        tenant = resolve_tenant(tenant_id)
        now = time.time()
        async with self._pool.connection() as conn:
            await conn.execute(
                "INSERT INTO procedural_memories "
                "(tenant_id, name, version, kind, description, input_schema, output_schema, "
                " effect_contract, lifecycle, definition, created_at, updated_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (tenant_id, name, version) DO UPDATE SET "
                " kind = EXCLUDED.kind, "
                " description = EXCLUDED.description, "
                " input_schema = EXCLUDED.input_schema, "
                " output_schema = EXCLUDED.output_schema, "
                " effect_contract = EXCLUDED.effect_contract, "
                " lifecycle = EXCLUDED.lifecycle, "
                " definition = EXCLUDED.definition, "
                " updated_at = EXCLUDED.updated_at",
                (
                    tenant,
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
        self, name: str, version: str | None = None, *, tenant_id: str = _TENANT_UNSET
    ) -> ProceduralEntry | None:
        tenant = resolve_tenant(tenant_id)
        if version is not None:
            async with self._pool.connection() as conn:
                cur = await conn.execute(
                    "SELECT name, version, kind, description, input_schema, "
                    "       output_schema, effect_contract, lifecycle, definition, "
                    "       created_at, updated_at "
                    "FROM procedural_memories WHERE tenant_id = %s AND name = %s AND version = %s",
                    (tenant, name, version),
                )
                row = await cur.fetchone()
                return self._row_to_entry(row) if row else None

        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT name, version, kind, description, input_schema, "
                "       output_schema, effect_contract, lifecycle, definition, "
                "       created_at, updated_at "
                "FROM procedural_memories WHERE tenant_id = %s AND name = %s "
                "ORDER BY "
                "  CASE lifecycle WHEN 'stable' THEN 0 ELSE 1 END, "
                "  version DESC "
                "LIMIT 1",
                (tenant, name),
            )
            row = await cur.fetchone()
            return self._row_to_entry(row) if row else None

    async def list_all(self, *, tenant_id: str = _TENANT_UNSET) -> list[ProceduralEntry]:
        tenant = resolve_tenant(tenant_id)
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT name, version, kind, description, input_schema, "
                "       output_schema, effect_contract, lifecycle, definition, "
                "       created_at, updated_at "
                "FROM procedural_memories WHERE tenant_id = %s ORDER BY name, version DESC",
                (tenant,),
            )
            rows = await cur.fetchall()
            return [self._row_to_entry(r) for r in rows]

    async def list_by_name(
        self, name: str, *, tenant_id: str = _TENANT_UNSET
    ) -> list[ProceduralEntry]:
        tenant = resolve_tenant(tenant_id)
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT name, version, kind, description, input_schema, "
                "       output_schema, effect_contract, lifecycle, definition, "
                "       created_at, updated_at "
                "FROM procedural_memories WHERE tenant_id = %s AND name = %s ORDER BY version DESC",
                (tenant, name),
            )
            rows = await cur.fetchall()
            return [self._row_to_entry(r) for r in rows]

    async def delete(
        self, name: str, version: str, *, tenant_id: str = _TENANT_UNSET
    ) -> bool:
        tenant = resolve_tenant(tenant_id)
        async with self._pool.connection() as conn:
            result = await conn.execute(
                "DELETE FROM procedural_memories WHERE tenant_id = %s AND name = %s AND version = %s",
                (tenant, name, version),
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
