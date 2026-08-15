# 长期记忆采用 PostgresStore + pgvector 语义检索

## Status

accepted（2026-08-12，production-action-plan.md P2.2 评审定案）

## Context

P2.2 要做跨会话长期记忆，原方案用 `InMemoryStore`——进程重启失忆，且多 worker（ADR-0002 已解禁）下记忆碎片化在不同进程，与"长期记忆"定义矛盾。checkpointer 已因同样原因迁到 Postgres（ADR-0002），基础设施已就位。

## Decision

- **`PostgresStore` 本期落地**，与 checkpointer 同一 Postgres 实例、独立 schema，纳入 lifespan 生命周期；本地无 Postgres 的测试态回退 `InMemoryStore`。
- **pgvector 语义检索本期启用**：Postgres 镜像改用 `pgvector/pgvector`（官方 postgres 镜像不含扩展）；`PostgresStore(index=IndexConfig(dims=…, embed=…))` 建向量索引。
- **embedding 后端固定复用 Phase 3 已定的本地 sentence-transformers（bge-small-zh）**，与意图原型/缓存 embedding 解耦策略保持一致（refactor-plan X1-3"永不切换"教训），避免向量空间漂移导致记忆索引重建。

## Considered Options

- **InMemoryStore**（否决）：重启失忆 + 多 worker 碎片化，不满足"长期"语义。
- **PostgresStore 先键值、语义检索后置**（否决）：prompt 已承诺"新会话检索相关历史记忆"，键值检索撑不起该承诺；后置会导致记忆数据按旧 schema 积累后再迁移。

## Consequences

- embedding 模型与向量维度成为锁定项：更换模型需重建全部记忆向量（故固定 bge-small-zh）。
- 新增依赖：`langgraph` store postgres 支持 + `pgvector` python 包；compose 的 postgres 镜像变更需在 ADR-0002 的 postgres 服务定义上叠加。
- 记忆写入涉及用户数据，后续需明确保留策略（与 checkpoint retention 口径对齐）。
