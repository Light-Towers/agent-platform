"""取证面 PG 往返探针（只读，不需要真库）。

证明三件事，全部用实跑读数而不是源码推断：
1. `PgTrajectoryStore.save` 发出的 INSERT **不含 forensic 列**，绑定参数里也没有那个 dict；
2. 因此 `get` 回来的 `record.forensic is None` —— 记录级取证在 PG 侧丢失（内存存储因存对象而保留）；
3. `get` 回来的 `steps` 元素是 `dict` 而不是 `TrajectoryStep` ⇒ 任何属性访问抛 `AttributeError`
   （`replay.py` 正是按 `record.steps[i].name` / `.error` / `.result` 写的）。

做法：用一个记录 SQL 的伪连接喂 `save`，再用一行合成游标结果喂 `get`，全程不连 PG。

跑法（仓库根）：`uv run python scripts/evidence/forensic_pg_roundtrip_probe.py`
出处：`docs/plans/plan-unfinished-completion-schedule-2026-10-16.md` §25。
"""

from __future__ import annotations

import asyncio
import inspect
import pathlib

from agent_runtime.forensic import ForensicContext, StepForensic
from agent_runtime.trajectory.models import TrajectoryRecord, TrajectoryStep
from agent_runtime.trajectory.store_pg import PgTrajectoryStore

_SRC = pathlib.Path(inspect.getfile(PgTrajectoryStore)).read_text(encoding="utf-8")


class _Cursor:
    async def fetchone(self):
        return (
            "exec-1", None, "sess-1", "deterministic", {},
            [{"name": "search", "forensic": {"skill_version": "v9"}}],
            3, 0.0, {}, None,
        )


class _Connection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple]] = []

    async def execute(self, sql, params=None):
        self.calls.append((sql, params))
        return _Cursor()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _Pool:
    def __init__(self) -> None:
        self.conn = _Connection()

    def connection(self):
        return self.conn


async def _main() -> None:
    print(f"A) store_pg.py 全文 'forensic' 命中次数 : {_SRC.lower().count('forensic')}")

    rec = TrajectoryRecord(
        execution_id="exec-1",
        session_id="sess-1",
        planner="deterministic",
        steps=[TrajectoryStep(
            name="search",
            forensic=StepForensic(skill_name="search", skill_version="v9").to_dict(),
        )],
        forensic=ForensicContext(model="qwen-max", planner_version="deterministic").to_dict(),
    )

    store = PgTrajectoryStore(_Pool())
    await store.save(rec)
    sql, params = store._pool.conn.calls[0]
    columns = sql.split("INSERT INTO")[1].split("(")[1].split(")")[0]
    print(f"B) 实际 INSERT 列清单                   : {', '.join(c.strip() for c in columns.split(','))}")
    print(f"   列里是否含 forensic                  : {'forensic' in columns}")
    print(f"   绑定参数是否含 forensic dict          : {any(isinstance(p, dict) and p.get('model') for p in params)}")

    back = await store.get("exec-1")
    print(f"C) 读回 record.forensic                 : {back.forensic!r}")
    print(f"   读回 steps[0] 类型                    : {type(back.steps[0]).__name__}")
    try:
        _ = back.steps[0].name
        print("   属性访问 steps[0].name                : OK")
    except AttributeError as e:
        print(f"   属性访问 steps[0].name                : AttributeError: {e}")
    print(f"   内存里原始 record.forensic            : 非 None（{bool(rec.forensic)}）⇒ 差异只在存储往返")


if __name__ == "__main__":
    asyncio.run(_main())
