# ADR-0003: 双数据库驱动并存（asyncpg + psycopg）

- 状态：已采纳（Accepted）
- 日期：2026-08-17
- 关联：ADR-0002（Postgres checkpoint 从起步即用连接池）

## 背景

仓库内存在两条 PostgreSQL 访问路径，且刻意并存：

1. **业务/平台层（app）**：`app/infra/db.py` 使用 **asyncpg**（`AsyncConnectionPool`）
   管理连接池，承载 RAG chunks、long-term memories 等业务表读写。
2. **agent-core 内核层**：`PgVectorMemoryBackend`（语义记忆）与 `MongoCheckpointer`/
   `AsyncPostgresSaver` 链路使用 **psycopg / psycopg_pool**（LangGraph 官方 checkpoint
   后端硬性要求 psycopg3，不可用 asyncpg）。

历史上 `psycopg.pool: 'coroutine' object has no attribute 'register'` 的坑，正是
asyncpg 池与 psycopg 的 `register_vector` 不兼容所致（见 `docs/tb7-smoke.md`）。

## 决策

两条驱动**不强制统一**，按边界各司其职：

| 层 | 驱动 | 职责 | 生命周期 |
|----|------|------|----------|
| app 业务层 | asyncpg | RAG chunks / memories 业务读写，平台自管池 | `app/infra/db.py` 统一 `close_pool()` |
| agent-core 内核 | psycopg / psycopg_pool | 向量语义记忆、LangGraph checkpoint（AsyncPostgresSaver） | 内核后端自建/复用 LangGraph 池 |
| deepagents 编排 | psycopg_pool | LangGraph `AsyncPostgresSaver` 连接池（ADR-0002） | lifespan 创建/关闭 |

内核层**不得**为了复用 app 的 asyncpg 池而引入 asyncpg 依赖——这违反 §3 零依赖铁律
（agent-core 内核仅依赖 stdlib，psycopg 为可选 extra）。app 层向内核 `PgVectorMemoryBackend`
传入它**自己** `psycopg` 风格的连接/池，或内核在 `database_url` 非空时自建 psycopg 池。

## 后果

- **正向**：LangGraph checkpoint 走官方 psycopg 后端，避免 asyncpg/pgvector register
  不兼容；内核保持零硬依赖，可选 psycopg extra 懒加载。
- **负向**：两套池并存，连接数翻倍风险——需分别设 `pool_max_size` / `MYSQL_POOL_SIZE`
  等价上限，并监控（见 deepagents 生产行动计划的连接池监控项）。
- **运维约束**：DSN 仅走 `.env`，不入库；两池各自 `pool_timeout` 与上限需协调，防止
  单实例连接数膨胀压垮 Postgres `max_connections`。

## 备注（优化 ③ #5/#6 同步项）

本次把内核内**同步阻塞式 SDK 调用**移出事件循环，与双驱动策略一致：

- `MilvusMemoryBackend`：`recall`/`remember` 的 `pymilvus` 调用与 `embed` 经
  `ThreadPoolExecutor`（`_run_sync` + `_aembed` 优先 `aembed`）包裹，避免 LangGraph
  `astream` 被阻塞；构造期不再硬 import pymilvus（懒加载 + 可单测）。
- `MongoCheckpointer`：所有 `pymongo` 同步调用（`find_one`/`update_one`/`delete_many`）
  经 `_run` 投入 `ThreadPoolExecutor`，消除 async 方法内阻塞事件循环的问题。
