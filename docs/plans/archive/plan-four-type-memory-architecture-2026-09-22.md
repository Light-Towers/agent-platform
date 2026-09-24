# Plan: 四类 Memory 架构（Working / Episodic / Semantic / Procedural）

> 日期：2026-09-22
> 状态：✅ 全部完成（三阶段 + PG 持久化 + 记忆闭环 + 9 项隐性问题修复 + agent_server 接入）
> 前置：V3 Execution Platform P0+P1 已完成（fencing / effect contract / awaitable / scheduler / recovery / state migration / payload externalization / control plane / forensic / skill lifecycle / cost governance / human task）

## 1. 问题

旧方案把完全不同性质的信息都叫 Memory，全塞进 Vector DB，导致 Context Pollution。
四类划分按"记住的东西是什么"分类，不同类型用不同存储 / 不同写入机制 / 不同召回策略。

## 2. 现状映射

| 四类 | 已有实现 | 缺口 |
|------|---------|------|
| Working | Checkpoint + ExecutionStatus(10态) + Await9 + Ownership/Lease + SideEffect + Idempotency | 三套 Store 各自独立，未统一抽象为 WorkingMemory 接口 |
| Episodic | ① TrajectoryRecord（执行轨迹→replay）② typed.MemoryType.EPISODIC（对话沉淀→向量召回） | 两套并行互不相通；Trajectory 未作为 episodic 召回源 |
| Semantic | ① knowledge-service（共享知识库：Milvus+Neo4j+MinIO+Mongo）② typed.MemoryType.SEMANTIC（用户级事实记忆） | 两套层级不同但无显式边界声明 |
| Procedural | SkillRegistry（name/version/lifecycle/effect_contract + 4 种执行器 + 中间件） | 进程内注册，非持久化，重启丢失 |

## 3. 三阶段任务

### 阶段 1：Working + Semantic 边界声明

| # | 任务 | 产出 |
|---|------|------|
| 1A | WorkingMemory 统一接口 | `working_memory.py`：组合 CheckpointStore + ExecutionStatusStore + AwaitableTaskStore 为一门面，提供 `snapshot(execution_id)` / `save_state()` / `load_state()` |
| 1B | SemanticMemory 边界声明 | `semantic_memory.py`：显式区分 SharedSemantic（knowledge-service 平台级）vs UserSemantic（agent-core 用户级），提供统一 `recall(query, scope)` 接口 |
| 1C | Memory 分类枚举 + 召回编排 | `memory_types.py`：MemoryCategory 枚举 + MemoryRetriever 协议 + ContextSelector（按任务类型选哪些 Memory 参与召回） |

### 阶段 2：Episodic Memory 沉淀管道

| # | 任务 | 产出 |
|---|------|------|
| 2A | Trajectory → Episodic 沉淀 | `episodic_memory.py`：从 TrajectoryRecord 提取有价值的 Episode（重要性判断 + 摘要/压缩），写入 episodic 召回源 |
| 2B | Episodic 召回 | 扩展 `recall(query, scope)` 支持 episodic 类型，按任务相似度召回历史经历 |
| 2C | 沉淀策略 | `EpisodicExtractor`：判断"这次经历有没有价值"（成功/失败/新颖/重复），决定是否沉淀 |

### 阶段 3：Procedural Memory 持久化

| # | 任务 | 产出 |
|---|------|------|
| 3A | Skill 持久化存储 | `procedural_memory.py` + DB 表：Skill 定义落库，重启后自动恢复注册 |
| 3B | 经验 → Skill 沉淀 | `ProceduralExtractor`：高频成功执行模式 → 候选 Skill（从 Episodic 中挖掘） |
| 3C | Skill 版本管理 | 版本化存储 + 兼容性检查 + 热更新（旧 Execution 继续用旧版本，新 Execution 用新版本） |

## 4. 约束

- 不自建对象存储 / 不自建 MQ / 不自建 K8s Scheduler（Part C 红线）
- 复用已有基础设施：agent-core memory / knowledge-service / trajectory / SkillRegistry
- 向后兼容：现有 typed.MemoryType 不破坏，新接口在其之上编排
- 测试纪律：不删用例凑绿!绿

## 5. 依赖图

```
1A WorkingMemory 接口 ──┐
1B SemanticMemory 边界 ─┤
1C Memory 召回编排 ─────┘── 2A Episodic 沉淀 ── 2B Episodic 召回 ── 2C 沉淀策略
                                                                    │
                                                                    └── 3A Skill 持久化 ── 3B 经验沉淀 ── 3C 版本管理
```

## 6. 完成记录

### 三阶段（2026-09-22 完成）

| 阶段 | 产出 | 文件 |
|------|------|------|
| 1A | WorkingMemory 统一接口 | `working_memory.py` |
| 1B | SemanticMemory 边界声明 | `semantic_memory.py` |
| 1C | Memory 分类枚举 + 召回编排 | `memory_types.py` |
| 2A | Episodic Memory 沉淀管道 | `episodic_memory.py` |
| 3A | Procedural Memory 持久化 | `procedural_memory.py` |

### PG 持久化后端（2026-09-23 完成）

| 产出 | 文件 |
|------|------|
| episodic_memories + procedural_memories 表 | `db.py` |
| PgEpisodicStore + PgProceduralStore | `memory_pg.py` |

### 记忆闭环（2026-09-23 完成）

| 缺口 | 产出 | 文件 |
|------|------|------|
| 自动触发 | EpisodicSink + ProceduralSink + post_execution_hooks | `memory_sink.py` |
| 反馈闭环 | SkillUsageTracker → lifecycle 升降级 | `memory_sink.py` |
| 去重压缩 | EpisodeDeduplicator | `episode_dedup.py` |
| 语义召回 | bigram Jaccard 相似度 | `memory_recall.py` |

### 9 项隐性问题修复（2026-09-23 完成）

| # | 问题 | 产出 | 文件 |
|---|------|------|------|
| 1 | recency 衰减 | recency_score + three_factor_score | `memory_recall.py` |
| 2 | 候选 Skill 空壳 | pattern_steps 验证 | `memory_sink.py` |
| 3 | Reflection 机制 | ReflectionEngine（LLM + 统计反思） | `reflection.py` |
| 4 | 记忆模糊 | EmbeddingRecall（embedding + hash mock） | `embedding_recall.py` |
| 5 | 记忆冲突 | outcome 权重（SUCCESS/PARTIAL/FAILURE） | `episodic_memory.py` |
| 6 | TTL/过期 | MemoryDecayManager（max_age_seconds） | `memory_decay.py` |
| 7 | 容量上限 | LRU 淘汰（max_size + importance） | `memory_decay.py` |
| 8 | 冷启动 | MemorySeeder（种子记忆） | `memory_seed.py` |
| 9 | 幻觉检测 | detect_hallucination（连续相同 action+result） | `episodic_memory.py` |

### agent_server 接入（2026-09-23 完成）

| 产出 | 文件 |
|------|------|
| _build_memory_hooks + post_execution_hooks 注入 | `applications/agent_server/main.py` |

### 验证

- agent-runtime: 495 passed
- agent_server: 34 passed
- 根测试: 406 passed, 15 skipped（HA 真实 PG 测试 Windows 自动 skip）
- lint: All checks passed
