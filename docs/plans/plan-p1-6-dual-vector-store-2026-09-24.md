# P1-6 Milvus / pgvector 双库互通方案

> **状态**：方案待审批（AGENTS.md 红线：先方案后编码）  
> **创建**：2026-09-24  
> **审计来源**：`arch-audit-2026-09-24.md` P1-6

---

## 1. 问题陈述

当前平台存在两套向量存储，职责分裂且无互通：

| 存储 | 使用方 | 内容 | 删除/GC |
|------|--------|------|---------|
| **Milvus** | knowledge-service | RAG 文档 chunk（商品知识） | `node_import_milvus.py:316` 有删 |
| **pgvector** | agent_server | chunks + sql_ddl/docs/examples + memories | **全仓无 DELETE FROM chunks**（本次补齐） |

分裂后果：
- `vector_backend.py:386-396` 按 `VECTOR_BACKEND` 二选一（非双写），typed memory 落 pgvector 而知识库走 Milvus
- 同一平台的"语义知识"分散在两套存储，无一致性校验
- 知识删除后 pgvector 残留（已通过本次补 `delete_document()` 修复 agent_server 侧）

## 2. 影响面

- `packages/agent-runtime/agent_runtime/memory/` — typed memory 写 pgvector
- `packages/agent-core/agent_core/config.py:137` — 默认 `VECTOR_BACKEND=milvus`
- `applications/knowledge-service/` — 全链路 Milvus
- `applications/agent_server/rag/` — 全链路 pgvector

## 3. 方案选项

### A. 统一为 pgvector（推荐长期）

**理由**：
- monorepo 核心运行时已依赖 psycopg + pgvector，引入 Milvus 增加运维复杂度
- knowledge-service 量级（万级 chunk）在 pgvector 性能范围内
- 统一存储简化 GC、备份、一致性

**代价**：
- knowledge-service 需要大改检索层（Milvus 特有 API：dense+sparse 双向量、partition_key）
- 需评估 HNSW/IVFFlat 在千万级是否够用

### B. 维持双库 + 加同步层

**理由**：最小改动，不破坏 knowledge-service 现有链路

**代价**：
- 需定义同步契约（哪些数据双写、冲突解决）
- 运维复杂度增加（两个存储都要监控）
- 长期技术债不清

### C. 维持双库 + 明确职责边界（推荐短期）

**理由**：
- 当前两库服务不同场景（Milvus=商品知识库检索、pgvector=Agent 运行时记忆+SQL 元知识）
- 强行统一是 premature optimization
- 只需文档化边界 + 补齐 GC 路径

**实施**：
1. ✅ `delete_document()` 补齐（本次已完成）
2. 文档化"哪些数据在哪"，AGENTS.md 或 ARCHITECTURE.md 补一段
3. 如未来 typed memory 需要 sparse 检索，再评估 A

## 4. 决策建议

**短期选 C**（本次已落地 GC 补齐），**长期视 knowledge-service 量级增长再评估 A**。

## 5. 验收标准（C 方案）

- [x] agent_server pgvector chunks 有 delete 路径
- [ ] AGENTS.md / ARCHITECTURE.md 中补充向量存储边界说明
- [ ] `VECTOR_BACKEND` 配置项加 docstring 说明何时用哪个
