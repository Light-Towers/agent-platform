# checkpoint 持久化直接采用 Postgres，跳过 SQLite 档

## Status

accepted（2026-08-12，production-action-plan.md P1.2 评审定案）

## Context

production-action-plan.md P1.2 原方案为文件级 SQLite（`AsyncSqliteSaver` + aiosqlite 单连接），生产再升级 Postgres。评审发现 SQLite 档隐含单 worker 约束（多 worker 各持连接写同一文件会锁竞争、thread 状态视图不一致），且 `VERIFICATION_REPORT.md` 已记录 `from_conn_string` 两种写法均失败的历史坑。项目目标是生产级，分级演进反而留下一个"看起来能用、实际约束苛刻"的中间态。

## Decision

**直接从 `AsyncPostgresSaver`（连接池）起步**，不落地 SQLite 档：

- docker-compose（refactor-plan D11 的单一 compose）新增 postgres 服务，专用于 checkpoint；
- 依赖 `langgraph-checkpoint-postgres`（psycopg pool），连接池纳入 lifespan 创建与关闭；
- checkpointer 存 `app.state`，静态 agent 与 P5.4 动态 agent 统一注入同一实例（P5.4 中 `await _create_checkpointer()` 自建 InMemorySaver 的写法作废）；
- 解除单 worker 约束，uvicorn 可多 worker，验收标准"进程重启对话历史不丢"在多 worker 下成立。

## Considered Options

- **SQLite + WAL 单节点档 → 生产再迁 Postgres**（否决）：SQLite 档要求 workers=1 且并发写入串行化，是一个约束苛刻的中间态；迁移时还要二次改 lifespan/依赖，两次改动不如一次。
- **维持 InMemorySaver**（否决）：进程重启全丢，达不到生产验收标准。

## Consequences

- 开发/preview 环境也要起 postgres（compose 一键起，成本可接受）；无 Postgres 时的本地冒烟用 InMemorySaver fallback，仅作测试态。
- P1.3 的清理策略、P7.6 durable execution 均建立在 Postgres checkpoint 之上。
