"""PostgreSQL + pgvector 连接池（agent_federation 单一池，遵守 ADR-0003）。

设计要点：
- agent_federation 不自建 asyncpg 双池；pg 模式语义/类型记忆统一走 agent_runtime 单池。
- 池 URL 取 ``AGENT_PLATFORM_DATABASE_URL``（WS-5：旧名 ``DEEPAGENTS_DATABASE_URL``
  兼容一个小版本，回退 ``DATABASE_URL``；与 app 共享库时指向同一库）。
- 懒加载加锁 + lifespan 预热，避免竞态；schema（含 ``memories`` 表）由
  ``agent_runtime.db`` 的迁移统一拥有，本模块不再自带 DDL。
- ``register_vector_async`` 必须在打开连接池前先 ``CREATE EXTENSION vector``，否则报
  "vector type not found"（与 app/infra/db.py 同一坑；该步在 runtime 迁移前完成）。
"""

from __future__ import annotations

from typing import Any

from agent_core.config import env_database_url
from agent_runtime.db import close_pool, get_pool
from agent_runtime.db import init_pool as _runtime_init_pool

__all__ = ["init_pool", "get_pool", "close_pool"]


async def init_pool(database_url: str | None = None, **kwargs: Any) -> Any:
    """按文档约定解析 DSN 后初始化内核单池。

    ``database_url`` 显式传入时优先；否则走 ``agent_core.config.env_database_url``
    （新名 → 旧名弃用警告 → ``DATABASE_URL`` 回退）。空 DSN 维持内核的内存模式。
    """
    url = env_database_url() if database_url is None else database_url
    return await _runtime_init_pool(url, **kwargs)
