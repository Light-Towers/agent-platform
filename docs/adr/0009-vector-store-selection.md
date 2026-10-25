# ADR-0009: 两套向量存储并存（Milvus / pgvector）——决策记录

- 状态：**未决（本文不替用户拍板；只把约束与代价摆清）**
- 日期：2026-10-16
- 来源：roadmap `plan-production-delivery-roadmap-2026-10-09.md` 阶段3 #24「3 项技术选型悬置」之二
- 关联：`ADR-0003`（双 **驱动** asyncpg+psycopg 已决"不强制统一"——注意：那份定的是驱动，不是存储引擎，别把已决项当成未决项重开）

## 1. 现状（本轮逐个实读定位，不是模式猜测）

| 服务 | 向量存储 | 混合检索怎么做的 | 证据 |
|---|---|---|---|
| knowledge-service | **Milvus** | **dense + sparse 双路**（稀疏向量原生在引擎侧），`metric_type=IP` | `applications/knowledge-service/knowledge_service/clients/milvus_utils.py:139-157` |
| agent_server | **pgvector** | pgvector 召回 + **BM25 关键词召回（本服务自己实现）** + RRF 融合 | `applications/agent_server/rag/store.py:1`（模块头）、`:106`（`vector_search`，走 `agent_runtime.db`） |

⇒ 同平台两套向量栈是**事实**，且各自的选择都有功能理由，不是历史巧合：
KS 要稀疏向量（引擎侧），agent_server 要"向量列与业务表同库同事务"。

## 2. 未决的是什么

**「要不要收成一套」以及收成哪一套。** 三选项与代价：

| 选项 | 做法 | 代价 / 风险（按当前实测证据） |
|---|---|---|
| **A 统一到 Milvus** | agent_server 的 RAG/长期记忆迁 Milvus | ① 要放弃"向量列与业务表同库"的同事务假设；② BM25 那层在 Milvus 侧要换实现（KS 已有稀疏路，可复用但要跨服务抽公共件）；③ **运维可用性代价有现网实证**：Milvus 会随宿主磁盘 IO 抖动自行退出（etcd `slow fdatasync` → lease 保活失败，`AGENTS.md` 内网环境第 6 条，累计 15 次），把 agent_server 也接到这条链上等于扩大受影响的链路数 |
| **B 统一到 pgvector** | KS 的 chunks 迁 pgvector | **稀疏检索这条路会被削平**：`milvus_utils.py:139-157` 的 dense+sparse 双路是 KS 混合检索的承重点，pgvector 无等价的引擎侧稀疏向量；迁过去意味着检索质量变化，而 KS 有**已冻结的检索回归基准**（roadmap #17 记「检索类回归基准已冻结入库并被门禁引用」）⇒ 这不是"换个库"，是可能把基线打穿 |
| **C 明确并存**（现状 + 把边界写成契约） | 不迁，只在 `ARCHITECTURE.md` 写清「哪类数据落哪套、为什么」+ 加一条 lint 禁止新服务自起第三套 | 零行为风险；代价是长期维护两套运维面与两套客户端代码；`docs/TODO.md` 需登记"第三套禁止"这条不变量 |

## 3. 否决理由（已可排除的判断）
- **「两套并存是疏漏、应当合并」**：不成立。上表两列功能差异是有意选择（A 要同事务，KS 要稀疏路）。
  合并的前提是先回答"用哪一方的能力去承载另一方的需求"，而 §2 显示两条方向各有一个硬缺口。
- **「迁移成本低，顺手做掉」**：不成立。KS 侧改动会打到已冻结的检索基线（B），agent_server 侧改动会打到
  现网 Milvus 的稳定性账（A）。

## 4. 重启条件
1. Milvus 现网稳定性根因（单盘 `ROTA=1` + IO stall，见 `docs/operations/env-126-inventory.md`）**被消除** ⇒ A 的代价显著下降，值得重算。
2. pgvector 出现可用的稀疏/BM25 等价方案（官方扩展或成熟第三方）且能在 KS 的冻结基线上跑出**不降**的读数 ⇒ B 重新可选。
3. 出现**第三个**要接向量存储的服务/应用 ⇒ 必须当场定 C 的"禁止第三套"不变量，否则会从 2 套变 3 套。

## 5. 待用户回答
- A / B / C（选 C 的话，我把"哪类数据落哪套"的边界写进 `ARCHITECTURE.md`，并加 lint 禁第三套；
  选 A 或 B 都属跨服务迁移，需单独立项出实施方案，我不会直接动手）。
