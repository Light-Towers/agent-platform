# -*- coding: utf-8 -*-
"""Postgres 连接池工厂（Plan-F runtime 层共享件）：显式配额 + 连接级只读 + 可观测统计。

来源：2026-10-17 nl2sql-service 连接池审计（该服务两个池此前全靠 psycopg_pool
默认值）。上移至此的理由是 AGENTS.md §90「单一实现：逻辑收敛 kernel，不在各 app
复制」——连接配额 / 超时 / 只读的解释不能每个服务一份，一家漏 `statement_timeout`
就是一家会挂死。此前平台内已有连接层复制品三例（nl2sql 自建池工厂、
`agent_server/sql/pipeline.py:76` 每次新建连接、`vector_backend.py:253` asyncpg
另建一池），本件是收敛的第一步。

固化审计三结论：

1. **配额裸奔**：`AsyncConnectionPool(dsn)` 默认 `min_size=4 / max_size=None`
   ⇒ 需求超过 min_size 时**无限新建后端**，真正的天花板是 PG 的
   `max_connections`（默认 100），超限报 `FATAL: too many clients` 并以
   `psycopg.OperationalError` 冒出，被上层兜底成一次无解释的失败。
   本工厂强制显式 min/max，并把 `max_waiting` 设为 `2 * max_size`——
   排队到上限即 `TooManyRequests` 快速失败，比无限新建连接可排查得多。
2. **连接级无防线**：只读若只靠会话级 `SET default_transaction_read_only = on`
   可被绕过重置。本工厂在建连参数里就下发 `-c default_transaction_read_only=on`
   （与 `agent_server/sql/pipeline.py:78` 同款）——连接一出生就是只读，
   不依赖任何后续 SET。注意真正的第一道防线永远是账号级 `GRANT SELECT ONLY`。
3. **不可观测**：`pool.get_stats()` 的计数器此前没有任何出口。
   `pool_stats()` 派生 in_use / utilization，供各服务挂自己的观测端点。

另注意 `timeout`（取连接等待）**不会取消已经持有连接后正在执行的语句**，
所以 `statement_timeout` 必须走连接参数，而不是指望池的 timeout。

范本对齐：`agent_runtime/db.py` 的单例池五要素（显式 min/max、连接级 configure、
schema 前置保证）。差异点：本工厂只负责"建池"，**不持有单例**——单例归各服务
的 lifespan 组装（或 db.py 的 `init_pool`）。想用单例的走 `db.py`；想按 DSN
多池（如 nl2sql 的 meta / dw 双库）的用本件。

⚠️ libpq 限制：若 DSN 自身带 `options` 参数，与本工厂下发的 `options`
不会按预期合并（libpq 不拼接两个 options）。故 DSN 不要自带 options。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - 仅类型检查期可见
    from psycopg_pool import AsyncConnectionPool

#: 默认单语句超时（毫秒）。元知识库的检索/写入都应是毫秒级，超过它即缺索引。
DEFAULT_STATEMENT_TIMEOUT_MS = 5000

#: 排队上限 = max_size 的倍数。超过即 TooManyRequests，不无限堆积等待者。
MAX_WAITING_FACTOR = 2


def build_options(statement_timeout_ms: int, read_only: bool) -> str:
    """拼 libpq ``options`` 连接参数（建连时生效，非事务性，ROLLBACK 不会撤销）。"""
    parts = [f"-c statement_timeout={statement_timeout_ms}"]
    if read_only:
        parts.append("-c default_transaction_read_only=on")
    return " ".join(parts)


def create_pool(
    *,
    dsn: str,
    name: str,
    min_size: int = 1,
    max_size: int = 20,
    timeout: float = 5.0,
    statement_timeout_ms: int = DEFAULT_STATEMENT_TIMEOUT_MS,
    read_only: bool = False,
) -> AsyncConnectionPool:
    """建一个**未打开**的池；调用方负责 ``await pool.open()`` 与关闭。

    懒导入 `psycopg_pool`：本包不硬依赖它（与 `db.py` 同款纪律），
    未装 psycopg 的环境 import 本模块不炸，只有调本函数才需要。

    Args:
        dsn: 连接串。不要自带 ``options``（见模块 docstring 的 libpq 限制）。
        name: 池名，进日志与 ``get_stats()``，用于区分不同目标库。
        min_size: 常驻后端数。取 1 = 按需增长，不预占（默认值 4 会在启动就占 4 个）。
        max_size: 后端硬上限。必须显式给，否则等于把天花板交给 PG max_connections。
        timeout: 取连接的等待上限（秒）。只约束"等连接"，不取消已持有连接上的查询。
        statement_timeout_ms: 单语句超时，经连接参数下发。
        read_only: True 时连接级只读。**只给"执行 LLM 生成 SQL"的业务库用**；
            元知识库自己要有构建入口写数据，不能只读。
    """
    from psycopg.rows import dict_row
    from psycopg_pool import AsyncConnectionPool

    if min_size < 0:
        raise ValueError(f"min_size 不能为负: {min_size}")
    if max_size < 1:
        raise ValueError(f"max_size 至少为 1: {max_size}")
    if min_size > max_size:
        raise ValueError(f"min_size({min_size}) > max_size({max_size})")
    if timeout <= 0:
        raise ValueError(f"取连接超时必须为正: {timeout}")
    if statement_timeout_ms <= 0:
        raise ValueError(f"statement_timeout_ms 必须为正: {statement_timeout_ms}")

    return AsyncConnectionPool(
        conninfo=dsn,
        min_size=min_size,
        max_size=max_size,
        max_waiting=max_size * MAX_WAITING_FACTOR,
        timeout=timeout,
        # row_factory=dict_row：psycopg 3 默认 tuple_row 返回纯 tuple，业务代码
        # 按列名取值（dict(r)）会全线失败——这是真 PG 端到端才暴露的（假池模拟
        # Row._mapping 故单测全绿）。dict_row 让 fetchall() 直接返回 dict。
        kwargs={"options": build_options(statement_timeout_ms, read_only), "row_factory": dict_row},
        name=name,
        open=False,
    )


def pool_stats(pool: AsyncConnectionPool) -> dict[str, Any]:
    """池的可观测快照：psycopg 原始计数器 + 派生占用指标（JSON 安全）。

    ``utilization`` > 0.8 且 ``requests_waiting`` 持续 > 0 ⇒ 该扩配额，
    或该治慢查询（大概率是缺 ANN 索引导致的顺序扫描）。
    """
    raw: dict[str, Any] = pool.get_stats()
    size = raw.get("pool_size", 0)
    available = raw.get("pool_available", 0)
    pool_max = raw.get("pool_max")
    return {
        **raw,
        "in_use": size - available,
        "utilization": round((size - available) / pool_max, 3) if pool_max else 0.0,
    }


__all__ = [
    "DEFAULT_STATEMENT_TIMEOUT_MS",
    "MAX_WAITING_FACTOR",
    "build_options",
    "create_pool",
    "pool_stats",
]
