# 双向量库（Milvus / pgvector）统一收益判据（#86）

- 日期：2026-10-19
- 来源：GitHub issue #86 / TODO §0.2 C 组第 2 条
- 交付物：**收益判据**（解锁动作），零代码改动；拍板后另立实施 issue

## 0. 现状事实（2026-10-19 实取，命令可复跑）

| 面 | Milvus | pgvector |
|---|---|---|
| 主要使用方 | **knowledge-service**（导入/检索/评测全链路：`node_import_milvus`/`node_search_embedding`/`node_rrf`/`eval/`）+ agent-core `MilvusMemoryBackend` | agent-core `PgVectorMemoryBackend` + agent-server（rag/store、memory）+ agent-runtime（memory_recall/db）+ federation + **nl2sql-service**（meta 知识库三表） |
| 切换机制 | `create_memory_backend(mode)` 工厂按 `VECTOR_BACKEND` 切换，**默认 milvus**（`memory/semantic.py:66`） | 同工厂 `pg` 分支 |
| 检索能力 | **稠密 + 稀疏混合**（dense COSINE + sparse IP 双路 schema，RRF 融合，零依赖中文稀疏向量器 `lm/sparse_vectorizer.py`） | 稠密（`<=>`/余弦）+ 全文 `tsvector`（nl2sql value_repository 已用）；**agent-core pg 后端无稀疏向量** |
| 租户隔离 | `tenant_id` VARCHAR 标量字段 + filter expr（转义守门，`escape_milvus_string_utils.py`） | `tenant_id` 列 + WHERE 恒过滤（nl2sql 为 tenant/workspace/datasource 三列）；**无 RLS**（全仓 `.sql` 零 `ROW LEVEL SECURITY`） |
| 仓库供给 | **compose/k8s 均不供给 Milvus 服务**（`docker-compose.yml`/`ha.yml` 只有 postgres；k8s 文档记 Milvus 在共用测试机 126 的 ks 栈里，外部依赖） | compose `pgvector/pgvector:pg16` 官方镜像在仓内 |
| 运维实录 | k8s 文档实记：etcd 的 `slow fdatasync` **把 Milvus 带死过 31 次**（`deploy/k8s/00-config.yaml`）；部署面 = Milvus + etcd + MinIO 三件套 | 单 PG 实例，与应用库同栈 |

## 1. 六面判据

### 1.1 运维面

- pgvector：与应用 PG 同栈（compose 在仓、备份/监控/升级一套）；Milvus：**三件套**（Milvus+etcd+MinIO），etcd 的 fdatasync 抖动有 31 次带死 Milvus 的实录 ⇒ 独立故障域与调优面。
- 现状反讽：`VECTOR_BACKEND` 默认 milvus，但**仓库自己的 compose 不供 Milvus** ⇒ 默认值在仓内不可自举（dev/CI 需外部 Milvus 或显式切 pg）。

### 1.2 一致性（隔离语义等强性）

- 两边都是**标量过滤**（Milvus filter expr / PG WHERE），无 RLS ⇒ 隔离强度同代，统一不损失也不增益；
- 真正差异在**作用域维度**：pgvector 侧（nl2sql）已演进到 tenant/workspace/datasource 三列恒过滤；Milvus 侧仅 tenant_id 一维 ⇒ **统一到 pgvector 顺带收窄 Milvus 侧的作用域缺口**（这是统一的隐性收益，需在迁移方案里显式承接）。

### 1.3 迁移风险面

- ks 的 Milvus 数据 = 全量知识库（导入链路产物，**可由源文档重灌**）⇒ 重嵌/双写路径存在且已有 `--prune` 式重建先例（nl2sql 迁移脚本的铁律：向量一律重算）；
- 检索质量风险：稀疏+RRF 混合检索是 ks 的核心路线（B 路线），pgvector 侧无对等实现 ⇒ **统一 = 先在 pgvector 上复刻稀疏+RRF 再迁**，否则是检索质量回退；
- 回滚：双写期两库并存，切读路径可逆。

### 1.4 功能面（对等物清点）

| 能力 | Milvus | pgvector（0.5.1） |
|---|---|---|
| 稠密 ANN | HNSW/IVF 等 | ivfflat/hnsw（`<=>` 余弦/L2/IP） |
| 稀疏向量 | 原生（IP） | `sparsevec` 类型存在，但**仓内零使用**（agent-core pg 后端未接） |
| 混合 + RRF | 原生 reranker | 需 SQL 手写 RRF（或 halfvec+tsvector 近似） |
| 标量过滤 | filter expr | WHERE（SQL 全表达力，**更强**：可 JOIN） |
| 分区/分区键 | partition key | 表分区（DDL 层） |

⇒ 统一的功能债 = **稀疏+RRF 复刻**；统一的功能增益 = SQL JOIN/事务/单栈查询力。

### 1.5 成本面

- Milvus 三件套的内存/调优/巡检成本 vs 单 PG；etcd 故障域是主要风险项（31 次实录）；
- 人力：复刻稀疏+RRF ≈ 一个中等工程（估 3–5 人日，含评测回归）；ks 数据重灌 ≈ 已有迁移脚本形态可复用（1–2 人日）。

### 1.6 结论框架（三选项触发条件，不预结论）

| 选项 | 触发条件（全部满足才选） |
|---|---|
| **A 统一到 pgvector** | ① 稀疏+RRF 在 pgvector 复刻且 ks 评测（`make eval` 确定性层）不掉分；② etcd 故障域成本被运维侧认定为不可接受；③ 三列作用域缺口在 pgvector 侧补齐 |
| **B 维持双轨** | ① ks 混合检索短期无法复刻；② Milvus 面已有稳定运维归属（专人/专栈）；③ 双轨的认知成本被接受（两套 filter 语义、两套备份） |
| **C 按服务收敛（分阶段）** | ① 新服务（nl2sql 已是）默认 pgvector；② Milvus 只服务 ks 且显式登记为"混合检索特化栈"；③ 设复盘点（如下次 etcd 事故或稀疏复刻完成）再重判 A/B |

**当前证据的指向（非拍板）**：C 最贴近现状——nl2sql 已单栈 pgvector、ks 的混合检索是真实特化、`VECTOR_BACKEND` 默认值与仓库供给不一致（默认 milvus 但 compose 不供）这一条无论如何都该修（把默认改成 pg 或把 Milvus 写进 compose，二选一，属小改动）。

## 2. 本判据的使用方式

- 拍板时逐条对 §1.6 触发条件打勾，勾不齐的选项不选；
- 选 A/C 的复刻项另立实施 issue（先方案后编码）；
- §0 现状表任何一项过时（如 pgvector 接了稀疏）⇒ 先更新本表再判，**不拿过期事实拍板**。
