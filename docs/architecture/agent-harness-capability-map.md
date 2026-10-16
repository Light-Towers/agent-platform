# Agent Harness 能力全景图（代码为准 · 四档交底）

**版本：** V1
**定位：** 企业级 Agent 平台的**能力盘点表**——回答「这个平台到底具备哪些 Agent Harness 能力、各自处于什么状态」
**状态：** Reference（参照文档，非施工图、非对外承诺口径）
**适用范围：** 面试/评审/对外介绍时的「已接线 / 开关托管 / 未接线 / 目标态」交底；内部排缺项优先级
**创建日期：** 2026-10-14
**快照基线：** `main @ 48c25fe`（2026-10-14 会话起点）

> **本文是快照，不是活文档。** 表内每一条状态判定绑定上面的 rev；换 rev 后若要对外引用，先按 §1.3 的命令复跑一遍。理由同 `AGENTS.md` 观测硬规矩第 3 条：**读数必须绑定当时的 rev**。

---

## 0. 本文覆盖什么 / 不覆盖什么

### 覆盖

- 按 10 个能力域罗列平台**实际具备**的 Agent Harness 能力，逐条给状态与文件证据
- 每个 `已实现·默认关` 项给出**开关变量名与默认值**
- 每个 `半成品·零生产调用` 项给出复核方式
- 缺项补全清单（按 P0–P2 排序）与四条一致性残口（§4）

### 不覆盖（由其他文档承载）

| 不覆盖的内容 | 承载文档 |
|---|---|
| 分层契约、依赖图、各包子模块清单 | `ARCHITECTURE.md` |
| V3 八层架构语义与十大缺口 | `docs/plans/plan-v3-execution-platform-final-architecture-2026-09-22.md` |
| Capability/Execution Boundary 概念框架 | `docs/architecture/agent-execution-platform.md` |
| 已识别待办台账（唯一真相源） | `docs/TODO.md` |
| 技术债 D1–D10 / 多 Agent / Skill 收敛 | `docs/plans/plan-tech-debt-followup-2026-09-22.md` 等 |
| 现网部署快照与 126 环境事实 | `docs/operations/env-126-inventory.md` |

**与红线的关系：** 本文不修改任何架构红线，只描述现状。文中任何「已实现」**不得**顺势读作「已上线/已生产验证」——见 §1.2 与 `AGENTS.md` V3 段落（端到端双实例物理故障转移验收未达）。

---

## 1. 状态口径

### 1.1 图例（四档交底法 + 两档修饰）

| 记号 | 含义 |
|---|---|
| ✅ | 已实现 · **默认开** |
| 🔽 | 已实现 · **默认关（opt-in）**，附开关名 |
| 🟡 | 半成品 · 代码+单测齐备但**零生产调用方** |
| 🧪 | 脚手架 / 仅 demo（数据源硬编码或占位待接） |
| ❌ | 不存在（全仓检索零命中） |
| ⚠️ | 状态之外需同时交底的**边界或不对称** |

对外表述规则（沿用既有纪律）：**一律 opt-in——报「已就绪」前必须先说默认关。**

### 1.2 三个不可混用的维度

1. **代码在位 ≠ 已接线**：`🟡` 共 13 项（§6），实现与单测齐全，但 applications 层无人调用。
2. **已接线 ≠ 默认生效**：`🔽` 共 14 项（§5），接线完整，被开关挡住。
3. **默认生效 ≠ 现网已验收**：现网 `DATABASE_URL`/`scheduler_enabled` 等实际取值见 `docs/operations/env-126-inventory.md`，与本文的仓库默认值不是同一件事。

### 1.3 证据来源与已复核范围（不粉饰）

证据由三路合成：**① 本仓库全仓 import/符号扫描（主）**、② `noctilucent-lamp` wiki 的既有术语体系（决定用词）、③ 业界 2026 口径（决定「缺项」判据）。

其中**只有以下 4 条由本次会话逐条亲自复核**（其余为扫描结果转述，对外引用前建议抽验）：

| 结论 | 复核方式与结果 |
|---|---|
| A2A / Agent Card / `.well-known` 不存在 | `grep -i 'a2a\|agent_card\|agent-card\|\.well-known'` on `**/*.py` → **0 命中** |
| MCP 客户端走 stdio + **SSE** | `packages/agent-runtime/agent_runtime/mcp_client.py:146` `sse_client(url=...)` |
| `ReflectionEngine` / `slice_skill_context` / `run_admitted` 零生产调用 | 全仓检索仅命中 `tests/**` 与 `docs/plans/archive/**` |
| 三条 `NOT WIRED (P1-7)` 自述 | 模块头 docstring 原文 |

**复跑验证命令**（在本仓根执行，可复现 §5/§6 两张台账）：

```bash
# 1) 默认关开关台账：逐个确认默认值未被改动
rg -n 'enabled\s*[:=]\s*(bool\s*=\s*)?False|env_bool\("[A-Z_]+",\s*False\)' \
   applications/agent_server/config.py packages/agent-core/agent_core/config.py \
   packages/agent-runtime/agent_runtime/identity.py applications/agent_federation/agent

# 2) 零生产调用模块：模块名在全仓出现处是否只有 tests/ 与自身
for m in reflection working_memory memory_seed episode_dedup embedding_recall \
         state_migration payload_externalization human_task execution_recovery skill_router; do
  echo "== $m"; rg -l "$m" --glob '!**/tests/**' --glob '!docs/**'
done

# 3) 文档-代码同步门禁（路径存在性以 git 清单为准）
uv run --with ruff ruff check . && python scripts/check_doc_sync.py
```

### 1.4 路径基准（本文所有反引号路径 = **仓库根相对路径**）

- 表内证据一律写成可从仓库根直接定位的完整路径（如 `packages/agent-core/agent_core/tracing.py`），**不使用裸文件名或相对包名**——main.py / config.py / query_router.py / Makefile 在本仓各有 2–6 个同名文件，缩写即歧义。
- 校验基准 = **版本控制清单**（`git ls-files`），与 `scripts/check_doc_sync.py` 同口径；本机才有、不入库的文件（例：§2.8 登记的 KS 65 条 real golden 集）**故意不用反引号**，防止别人 clone 后成死链。
- 本次成文已按此规则跑过一轮全量路径校验，**改掉 4 条不实/歧义引用**：KS 无自有 Makefile（eval-rag 六目标在根 `Makefile:69-120`）；golden_queries.real.jsonl 被 `.gitignore:129` 忽略；exhibition 的只读 golden 在 `applications/exhibition-agent/skills/...` 而非包内；`agent/subagents`、`clients`、`repositories/pgvector` 等缩写目录已补全归属。

---

## 2. 能力全景（10 域）

一级列沿用对外定稿的 6 类公共能力（编排 / 上下文 / 工具 / 安全 / 可靠性 / 可观测）+ 评测治理，另将**记忆**、**知识数据**、**平台产品面**单列为 7–10 域（该切法与 6 类口径的关系见 §7 待拍板第 1 条）。

### 2.1 编排与范式 Orchestration & Planning

| 能力 | 状态 | 证据 / 开关 |
|---|---|---|
| Agent Loop（TAO 循环） | ✅ | 四套并存：`applications/agent_federation/agent/main_agent.py:542-673`（`FED_RECURSION_LIMIT=50`、`FED_MAX_STEPS=20` 超限主动中止）· `applications/agent_server/planners/deterministic.py:187-224`（`max_iterations=2`）· `applications/exhibition-agent/exhibition_agent/skill_loader/agent.py`（`MAX_TOOL_ROUNDS=6`）· `applications/nl2sql-service/nl2sql_service/agent/graph.py:23-28`（校验-纠错回环） |
| ReAct / agentic | 🔽 `PLANNER=agentic` | `packages/agent-runtime/agent_runtime/planner/agentic.py` · `applications/agent_federation/planners/agentic_runtime_bridge.py` |
| Plan-and-Execute | 🔽 `PLANNER=graph` | `applications/agent_server/planners/graph.py` · `packages/agent-runtime/agent_runtime/planner/graph_compose.py:1-22`（LLM 只从 `registry.discover` 候选选，**禁止生成任意 Python/执行器**） |
| Re-plan（执行期重规划） | ✅ | `packages/agent-runtime/agent_runtime/planner/protocol.py:44`（`StreamEventType` 含 `replan`）· `applications/agent_server/planners/graph.py:150-172`（`max_execution_replans=1`）· `packages/agent-runtime/agent_runtime/planner/protocol.py:200`（`TOOL_RESULT_SUGGESTS_REPLAN`） |
| Reflexion（单任务自评估） | 🔽 `REFLEXION_ENABLED=false` | `applications/agent_federation/agent/main_agent.py:167-184` → deepagents `RubricMiddleware(max_iterations=3)` |
| Reflection（洞察生成 / Generative-Agents 式） | 🟡 | `packages/agent-runtime/agent_runtime/reflection.py`（取最近 N 条 Episode → LLM 生成问题 → 回答 → 存 Insight）**零生产调用，且未自述 P1-7** |
| Self-evolution（反思 + 记忆 + **固化**） | ✅ 无 flag | `packages/agent-runtime/agent_runtime/memory_sink.py` → `packages/agent-runtime/agent_runtime/procedural_memory.py`（`ProceduralExtractor` + `SkillUsageTracker` 生命周期升降级）→ `packages/agent-runtime/agent_runtime/skill_lifecycle.py`；装配 `applications/agent_server/main.py:122-126,396` |
| Mode Selector（范式自动选择） | 🔽 `PLANNER=auto` | `applications/agent_server/planners/unified.py` · `packages/agent-runtime/agent_runtime/planner/mode_selector.py:67`（`agentic_enabled=False`）；优先级 force override > 复用已注册 Workflow > Dynamic Graph > Agentic |
| Supervisor / multi-agent / sub-agent | ✅ | `applications/agent_server/agent/graph.py:14-27`（LangGraph 静态 supervisor）· `applications/agent_server/subagents/{search,rag,sql_agent,mcp}.py` · 联邦 `applications/agent_federation/agent/subagents/` + `packages/agent-runtime/agent_runtime/skills/agent.py:as_agent_skill` · 动态角色 `_plan_roles`（`DYNAMIC_AGENT_ENABLED=false`） |
| delegate（Agent-as-Tool） | ✅ | `packages/agent-runtime/agent_runtime/planner/protocol.py:599`；**架构不变量**：Skill→Skill 组合唯一合法路径，白名单外直调 `registry.execute` 即 CI 红（`scripts/lint_architecture.py` P4） |
| **A2A / Agent Card / 跨组织互操作** | ❌ | 全仓零命中。实际互操作走 LangGraph Agent Protocol + 自有 REST：`applications/agent_federation/agent/async_subagents.py`、`applications/agent_federation/agent/config.py:31-77` |
| Commander（目标对齐 + 结构编排）/ Handoff 控制权移交 | ❌ | 仅 supervisor 图 + `delegate`；无 Commander 角色层、无移交语义 |
| debate / voting / blackboard | ❌ | |
| 动态 map-reduce（LangGraph `Send`） | 🟡 有替代物 | 自建分层并行 `packages/agent-runtime/agent_runtime/planner/execution_graph.py:1-16`（同层 `asyncio.gather` + 层间顺序 + deadline 检查） |
| 意图路由 L1/L2 + 澄清反问 | ✅（app）/ 🔽 `INTENT_ENABLED=false`（联邦） | `packages/agent-core/agent_core/intent/`（`L1_THRESHOLD=0.8`、`CLARIFY_THRESHOLD=0.5`）· `applications/agent_server/agent/router.py:1-8,91` |
| 查询改写 / 子问题分解 | 🔽 随 `INTENT_ENABLED` | `applications/agent_federation/agent/rewrite/rewrite_node.py` · `applications/agent_federation/agent/rewrite/subquery_decompose.py` |
| 声明式 Workflow（YAML → Skill） | ✅ 语料仅 1 条 | `packages/agent-runtime/agent_runtime/skills/workflow.py`（`$input.<key>` / `$node.<id>` 映射）· `packages/agent-runtime/workflows/qa_pipeline.yaml` |
| 静态 DAG 包装为能力 | ✅ | `packages/agent-runtime/agent_runtime/skills/dag.py` → 注册 `general_qa`（`applications/agent_server/capabilities.py:226-235`） |

### 2.2 上下文工程 Context Engineering

| 能力 | 状态 | 证据 / 开关 |
|---|---|---|
| 分层 token 预算（7 层 + 未用余量按优先级回流） | ✅ | `packages/agent-runtime/agent_runtime/context/budget.py:17-31`（system 5% / tool_defs 8% / task 6% / conversation 20% / memory 8% / tool_results 35% / execution 18%） |
| 摘要压缩 compaction | ✅ | `packages/agent-runtime/agent_runtime/context/compact.py`（LLM 摘要为一条 system，保留最近 4 条原文，≤500 字）· 开关 `applications/agent_server/config.py:70-75`（`compaction_enabled=True`, `ratio=0.8`）⚠️ 见 §4.1 |
| 窗口滑动（与旧阈值语义兼容） | ✅ | `applications/agent_server/context.py:53-59` |
| Context Manager 三段分离 + snapshot 跨轮 | ✅ | `packages/agent-runtime/agent_runtime/planner/context_manager.py`（`ConversationContext` / `TaskState` / `ExecutionState`；Skill Definition 不遗忘）· 读写链 `applications/agent_server/api/query_router.py:258` → `applications/agent_server/planners/deterministic.py:234` → `packages/agent-runtime/agent_runtime/planner/protocol.py:426-428` |
| Assembler 五段管线 + 固定注入顺序 | ✅ | `packages/agent-runtime/agent_runtime/context/assembler.py:1-19`（collect→rank→budget→compress→trim）· 不可裁顺序 `:10-12` |
| Context Governance 管道 Select→Recall→**Authorize→Validate→QualityScore**→Assemble | ✅ 无 flag | `packages/agent-runtime/agent_runtime/context/governor.py` · 装配 `applications/agent_server/main.py:129-171,397` ⚠️ `ContextBudget(model_window=32_000)` 硬编码，见 §4.2 |
| 记忆门控（top-k → 归一化哈希去重 → 同类取最新消解冲突 → 预算内取 N） | ✅ | `packages/agent-runtime/agent_runtime/context/memory_gate.py`（`memory_gate_top_k=5`） |
| Memory 权限过滤（tenant/user/workspace × visibility） | ✅ | `packages/agent-runtime/agent_runtime/context/authorizer.py` |
| 跨来源一致性校验（stale 降权 / conflict 降权或剔除 / invalid 剔除） | ✅ | `packages/agent-runtime/agent_runtime/context/validator.py` |
| 记忆质量三维评分（relevance + freshness + conflict，α+β+γ=1） | ✅ | `packages/agent-runtime/agent_runtime/context/quality.py` |
| 工具结果压缩 + Artifact 外置（`read_tool_result(ref)` 按需取回，刻意不用 LLM 摘要） | 🔽 `tool_result_compression_enabled=False` | `packages/agent-runtime/agent_runtime/context/tool_result.py` · 中间件 `packages/agent-runtime/agent_runtime/skills/middleware.py:122` · 装配 `applications/agent_server/capabilities.py:184-191` |
| Skill-local context 切片（Isolate，嵌套 token 加法化） | 🟡 | `packages/agent-runtime/agent_runtime/context/skill_context.py` 零调用 ⇒ 子上下文仍全量传 |
| token 单一尺子（tiktoken 精确 + 启发式降级） | ✅ | `packages/agent-core/agent_core/tokenizer.py` |
| KV-Cache 守护 / prompt cache 稳定性（工具定义不动态增删、`tools/list` 确定性排序） | ❌ | |
| 上下文利用率（55% 经验阈值）/ context rot 监控 | ❌ | |
| 四类上下文失败模式防护 | 🟡 仅覆盖冲突与过期 | `packages/agent-runtime/agent_runtime/context/validator.py` 管 stale/conflict/invalid；**投毒面（不可信工具返回 → 上下文/记忆）无隔离** |

### 2.3 记忆体系 Memory

| 能力 | 状态 | 证据 / 开关 |
|---|---|---|
| 四类契约 WORKING/EPISODIC/SEMANTIC/PROCEDURAL + `ContextSelector` 按 task_type 选类 | ✅ | `packages/agent-runtime/agent_runtime/memory_types.py:24-31,206-251` |
| 会话历史 thread state + Checkpointer 三后端降级链（PG → Mongo（按 tenant 隔离）→ InMemory） | ✅ | `packages/agent-core/agent_core/memory/__init__.py:67-117` · `packages/shared-schemas/shared_schemas/thread.py` · 装配 `applications/agent_server/main.py:46-62` |
| 精确回忆（按 `thread_id` 回溯原文，与语义回忆正交） | ✅ | `applications/agent_server/memory/recall_exact.py` → `/history` |
| 长期语义记忆（PG + pgvector；评分 `type_weight × importance × time_decay`） | ✅ 依赖 `DATABASE_URL` | `packages/agent-core/agent_core/memory/typed.py`（`remember_typed:235` / `recall_typed:328` / `consolidate` / `forget`）· `applications/agent_server/memory/longterm.py:89-110` · migration 见 `packages/agent-runtime/agent_runtime/migrations/`（003_memory / 004_memory_tenant_id / 005_memory_tenant_enforcement / 008_memories_dual_scope 的 .up.sql） |
| **用户画像（跨 workspace 双 scope）** | 🔽 `MEMORY_DUAL_SCOPE=false` | `packages/agent-core/agent_core/memory/typed.py:138-149` · `recall_user_profile:355-377` · 融合点 `applications/agent_server/memory/memory_backend.py:176`；关时画像召回返回空（「宁可画像暂不可用」） |
| LLM 结构化事实抽取（写入质量） | 🔽 `memory_extraction_enabled=False` | `applications/agent_server/config.py:47` · 退化分支 `applications/agent_server/memory/longterm.py:123,148`（存整条原文、importance 硬编码 0.5） |
| 遗忘 / 淘汰（语义层：低 importance + 超龄才删） | ✅ | `applications/agent_server/memory/longterm.py:163-182`（`memory_forget_threshold=0.1`）· `packages/agent-core/agent_core/config.py:144 MEMORY_FORGET_AGE_DAYS=30` |
| 衰减 / 容量淘汰（情景层：TTL 30d + 10000 条按 importance LRU） | ✅ 无 flag | `packages/agent-runtime/agent_runtime/memory_decay.py` · 作为 post-execution hook 装配 `applications/agent_server/main.py:125` |
| 情景 → 程序性自动沉淀（trajectory → episode → 候选 Skill） | ✅ 无 flag | `packages/agent-runtime/agent_runtime/memory_sink.py`（`EpisodicSink`/`ProceduralSink`, `trigger_interval=10`）· 持久化 `packages/agent-runtime/agent_runtime/memory_pg.py` |
| WorkingMemory 快照门面（Checkpoint+Status+Awaitable 三 store 统一） | 🟡 | `packages/agent-runtime/agent_runtime/working_memory.py` 零调用（**底层三 store 本身是接线的**，缺的只是门面消费方） |
| 语义召回相似度 | ⚠️ **降级形态** | `packages/agent-runtime/agent_runtime/memory_recall.py:1-13` 用**字符 bigram Jaccard**（自述「生产可替换为 embedding+pgvector」）；替换件 `packages/agent-runtime/agent_runtime/embedding_recall.py` 🟡 零调用 |
| Episode 模糊去重 | 🟡 | `packages/agent-runtime/agent_runtime/episode_dedup.py:11-14`（自述当前不支持，`similarity_threshold` 预留） |
| 冷启动种子记忆 | 🟡 | `packages/agent-runtime/agent_runtime/memory_seed.py` 零调用 |
| 租户漏传 fail-fast 门（绝不静默落 `default`） | ✅ | `packages/agent-core/agent_core/memory/_tenant_gate.py:14-27` + 治理测试 `tests/governance/test_tenant_default_forbidden.py` |
| 内核语义记忆总开关与 app 路径**不同源** | ⚠️ 语义裂缝 | `SEMANTIC_MEMORY_ENABLED=false`（`packages/agent-core/agent_core/config.py:135`）只门 `recall_memories`/`remember_memory` 旧门面；`agent_server` typed PG 路径只看连接池（`applications/agent_server/memory/longterm.py:8-13` 自述） |
| 记忆能力探测（防「配了但没记忆」） | ✅ | `packages/agent-core/agent_core/memory/store.py` `CapabilityReport.probe()`（永不抛异常，供 `/health` 序列化） |
| 记忆写入防投毒（外部内容不得借「写入记忆」指令入库） | ❌ | 仅读侧 `authorizer`，无写侧来源可信度门禁（OWASP ASI06） |
| append-only 事件流 + 异步物化视图（冲突可回放/可回滚） | ❌ | 设计见笔记，代码未落地 |
| L0 原始对话 → L1 原子 → L2 场景 → L3 画像 归纳流水线 | ❌ | 只有 L3 的开关与召回路，L1/L2 无流水线 |
| 冲突时反问确认（不让模型自行拍板） | ❌ | `packages/agent-runtime/agent_runtime/context/validator.py` 做降权/剔除，不反问 |

### 2.4 缓存与成本 Cache & Cost

> ⚠️ 存在**两套互不共享数据**的语义缓存（内核只统一接口与 key 构造，`packages/agent-core/agent_core/cache/base.py:5-9` 明示）。

| 能力 | 状态 | 证据 / 开关 |
|---|---|---|
| 语义缓存（命中判定 = **纯 embedding 余弦距离**，`<-> < 0.05`；距离不是相似度） | ✅ 默认开 | `packages/agent-runtime/agent_runtime/cache.py:38-72` · `cache_enabled=True` · 门控 `applications/agent_server/api/query_router.py:160-179` |
| key 构造（`sha256(intent\|rewritten\|kb_versions\|tenant\|gray)`）**故意不参与命中** | ✅ | `packages/agent-core/agent_core/cache/base.py:41-62`；app 侧 intent/kb 缺省 ⇒ 退化为 `sha256("\|query\|{}\|\|0.0)` |
| ⚠️ 空租户串 → 全局无过滤命中（跨租户可读） | 风险 | `packages/agent-runtime/agent_runtime/cache.py:49-55` 仅 `tenant_id` 非空加 WHERE；`applications/agent_server/api/query_router.py:162` 传 `req.tenant_id or ""` |
| **缓存失效 / TTL / 淘汰（agent_server 轨）** | ❌ | `packages/agent-runtime/agent_runtime/cache.py` 只有 lookup/write，无 delete ⇒ `semantic_cache` 表只增不减 |
| 分层 L1 精确 hash / L2 向量（Valkey HNSW, COSINE > 0.92）/ L3 检索 + NullCache 负缓存 + `invalidate_by_kb_version` | 🔽 `CACHE_ENABLED=false` | 联邦 `applications/agent_federation/agent/cache/layers.py:57-259` · `applications/agent_server/config.py:16,23`；⚠️ valkey 缺失/ping 失败 ⇒ 整层静默 no-op（`applications/agent_federation/agent/cache/layers.py:27-52`） |
| 缓存击穿防护 singleflight（同 key 并发只真跑一次 LLM） | ✅ | `packages/agent-runtime/agent_runtime/singleflight.py`（引用计数锁，P2-2 修竞态） |
| 命中率统计上报事件面 | ✅ | `packages/agent-core/agent_core/cache/stats.py` · `applications/agent_federation/agent/main_agent.py:488,490` |
| **provider prompt caching / 响应级 LLM 缓存** | ❌ | 全仓无 `cache_control`；只有语义问答缓存 + LLM 客户端对象 LRU（`packages/agent-core/agent_core/llm/registry.py:114-165`，缓存的是连接对象非响应） |
| 成本治理（requests/tokens/cost 三维 + window，超限 429） | 🔽 `cost_governance_enabled=False` | `packages/agent-runtime/agent_runtime/cost_governance.py` + `packages/agent-runtime/agent_runtime/cost_governance_pg.py` · 装配 `applications/agent_server/main.py:486-524` ⚠️ 三个 `budget_limit_*` **默认 0=不限制**（`applications/agent_server/config.py:156-159`），开了也不限；`PlannerRuntime.max_tokens/max_cost` 参数在位但 app 未传 |
| 模型主备降级（可复位熔断 + **流式契约：未产出 chunk 才切换重放**） | ✅ | `packages/agent-core/agent_core/llm/fallback.py`（组合 `resilience.CircuitBreaker`）· ⚠️ 同名 = 没有备，且结构化出参恒绑 primary（`.env.example:76`） |
| 模型路由（数据分级 + 出域 + 任务类型 + 成本 + 延迟；deny → `EGRESS_DENIED`） | 🧪 仅 exhibition | `applications/exhibition-agent/exhibition_agent/model_router.py` + `applications/exhibition-agent/exhibition_agent/foundation/data_egress.py` |
| 成本归因回路（按租户/Skill/步骤出报表） | 🟡 | `packages/agent-runtime/agent_runtime/trajectory/` 记 tokens/cost，无聚合与出数面 |

### 2.5 工具与能力接入 Tools / MCP / Skill

| 能力 | 状态 | 证据 / 开关 |
|---|---|---|
| Capability Registry 四执行器（Function / Agent / Remote / Workflow） | ✅ | `packages/agent-runtime/agent_runtime/skills/registry.py:1-15` · `execute()` 边界 `:361-367`（入参 schema 校验 → 中间件洋葱 → 执行器统一超时 → 产出校验）· 装配 `applications/agent_server/capabilities.py:167-239` |
| MCP **客户端**（stdio + SSE、per-server CircuitBreaker、工具白名单、超时、PG 审计） | 🔽 `mcp_enabled=False` | `packages/agent-runtime/agent_runtime/mcp_client.py`（`:146` 用 `mcp.client.sse`）⚠️ 见 §3 缺项 P1：SSE 属 MCP 2026-07-28 已弃用传输 |
| MCP 工具自动注册为 Skill（`mcp.{server_id}.{tool_name}` 三段式防跨 server 冲突） | 🔽 随 `mcp_enabled` | `packages/agent-runtime/agent_runtime/skills/mcp.py` · 装配 `applications/agent_server/main.py:359-364` |
| **MCP 服务端**（把本平台 Skill 暴露成 MCP server） | ❌ | 全仓无 `FastMCP` / `mcp.server`；`packages/agent-core/agent_core/tools/adapters/mcp.py` 是客户端适配器 |
| MCP 企业授权面（OAuth 2.1 资源服务器 / RFC 9728 元数据发现 / RFC 8707 token 绑定 / CIMD / EMA） | ❌ | |
| MCP Tasks / MCP Apps / elicitation / sampling | ❌ | |
| Skill 渐进披露与路由（选错 Skill 的排查面） | 🟡 | `applications/exhibition-agent/exhibition_agent/foundation/skill_router.py:3-22` 自带 `STATUS: NOT WIRED`；`route()` 零调用 |
| 工具级权限 ACL（`permissions: frozenset[str]` + `discover(caller_permissions=)` 过滤 + policy 第 5 项校验） | ✅ | `packages/agent-runtime/agent_runtime/skills/registry.py:78,306-337` · `packages/agent-runtime/agent_runtime/planner/policy.py:1-16` · workflow yaml 声明 `permissions` |
| Workflow 最小权限 CI 门禁（缺顶层 `permissions:` 或 `write-all` 即红，目录不存在也 fail-closed） | ✅ | `scripts/lint_architecture.py` P11 |
| 中间件洋葱（熔断 / 超时+失败降级真取消 / 重试 / 审计 redact / ToolObserved 最外层） | ✅ 部分 | `packages/agent-runtime/agent_runtime/skills/middleware.py:34-296` · 装配 `applications/agent_server/capabilities.py:176-191`；⚠️ `RateLimitMiddleware:198` 已实现但**未在装配链**（`:10-12` 自述「rate limit 待接入」） |
| 组合治理（`max_skill_depth=4` / `max_steps=20` / `max_duration` + **计划期**静态校验） | ✅ | `packages/agent-runtime/agent_runtime/planner/protocol.py:349-432,578,599` · `packages/agent-runtime/agent_runtime/skills/composition.py`（存在性/成环/权限闭包） |
| 循环预防指纹 | 🔽 `enable_loop_fingerprint=False` | `applications/agent_server/config.py:116`（注释：避免误伤合法重放/重规划）；**语义余弦 >0.95 那层没有** |
| 沙箱（`--network=none --read-only --tmpfs /tmp --memory=512m --cpus=1 --security-opt=no-new-privileges --user=nobody` + 双超时 + 安全 env 白名单） | ✅ **无条件装配** | `packages/agent-runtime/agent_runtime/sandbox.py` · 注册为 Skill `packages/agent-runtime/agent_runtime/skills/sandbox.py` · `applications/agent_server/main.py:366-372`；⚠️ Docker 不可用时 subprocess 降级（**无网络隔离，仅日志警告** `:210`） |
| tool explosion 治理（分组 / 动态发现 top-K / 约束解码屏蔽不可用工具） | ❌ | |
| Tool Contract Test（dispatch 前可解析可校验 + schema 漂移检测） | ❌ | |
| 联网搜索 | 🔽 `search_api_key=""` 即不注册 | `applications/agent_federation/tools/tavily_tool.py` · `applications/agent_server/subagents/search.py` |
| Computer Use / 浏览器 / GUI 自动化 | ❌ | |
| 旧工具注册表（内核，维护模式，不再新增能力） | ✅ 仅服务存量 | `packages/agent-core/agent_core/tools/registry.py` · `packages/agent-core/agent_core/tools/guarded.py:10-20`（超时=放弃等待，故 8 线程有界池） |
| 远程重服务 Skill（HTTP，5 个 URL 空即不注册） | 🔽 | `applications/agent_server/capabilities.py:241-388` · `applications/agent_server/config.py:134-138`；`_sanitize_identity` 把 tenant/user 从 LLM 可填参数剔除（ADR-0007）+ 治理测试 |

### 2.6 安全 · 权限 · 治理 Safety & Governance

| 能力 | 状态 | 证据 / 开关 |
|---|---|---|
| HITL 底座（Skill 返 `__awaitable__` → 建 AwaitableTask → 抛 `ExecutionSuspended`；外部回调幂等唤醒） | ✅ 部分 | `packages/agent-runtime/agent_runtime/planner/protocol.py:642-671` · `applications/agent_server/api/callback.py:31-40`（重复回调不重复 resume）· `packages/agent-runtime/agent_runtime/execution_status.py`（`WAITING_HUMAN` 合法态 + 转换矩阵）⚠️ **`AwaitableKind` 四类中只有 `EXTERNAL` 真被创建** |
| HITL 人工审批应用层（谁批 / 批什么 / 批完怎么继续） | 🟡 **P1-7** | `packages/agent-runtime/agent_runtime/human_task.py:1-27` 自带 NOT WIRED；`HumanTaskStore`/`Resolver` 零调用 ⇒ **能挂起能被唤醒，但「人」这一类没有任何产出入口** |
| 软 HITL（澄清反问）/ 高风险二次确认 | ✅ | `packages/agent-core/agent_core/intent/models.py:73`（`need_clarify`）· `applications/agent_federation/agent/main_agent.py:461-466` · KS `applications/knowledge-service/knowledge_service/query_process/agent/nodes/node_item_name_confirm.py` |
| 输入护栏（PII 四类 + injection，**先脱敏再查缓存**） | 🔽 双 app 都关 | `packages/agent-core/agent_core/guardrails/input_guard.py` · `guard_enabled=False`（`applications/agent_server/config.py:104`）/ `GUARD_ENABLED=false`（`applications/agent_federation/agent/main_agent.py:145,426,658`）· `GUARD_BLOCK_INJECTION` 默认 true |
| 输出护栏（PII + 幻觉标记词） | ⚠️ **仅告警不拦截** | `applications/agent_federation/gateway/output_guard.py:15-27` → `applications/agent_federation/agent/main_agent.py:658-665` 命中后 `logger.warning`，答案照发（与输入侧不对称） |
| 纵深防御四层（指令-数据分离 / prompt 加固 / 随机哨兵令牌） | ❌ | |
| 致命三要素（私有数据 + 不可信内容 + 对外通信）一票否决门禁 | ❌ | |
| SQL 守卫（sqlglot AST、单条必须 SELECT、13 类禁止节点含子查询、缺 LIMIT 强制补、非整数字面量 LIMIT 直接拒） | ✅ | `packages/agent-core/agent_core/sql/guard.py` · 执行层只读双保险（sqlite `mode=ro` / PG `default_transaction_read_only`）· 治理测试 `tests/governance/test_sql_guard.py` |
| 路径 containment / 异常不回显堆栈（SSE 帧级脱敏）/ `compare_digest` 防时序 / Content-Length 413 / 滑动窗口限流 | ✅ | `packages/agent-core/agent_core/guardrails/{fs,errors,web}.py` · 工厂 `packages/agent-core/agent_core/guardrails/app_factory.py` + lint P2/P7/P8 |
| 租户身份 RS256 JWT（按 kid 选公钥、强制 exp/iat/sub、max TTL 3600、skew 60、缺 `tenant_id` claim 即拒） | ✅ 代码 / 🔽 **默认 observe 放行** | `packages/agent-runtime/agent_runtime/identity.py` · 中间件挂载 `applications/agent_server/main.py:571` · `DEPLOY_ENFORCE_IDENTITY=false`、`TENANT_JWT_ENFORCE=false`、`TENANT_HEADER_ENFORCE=false`、未设 `SINGLE_TENANT` ⇒ 三态里的 `insecure` |
| 服务端唯一取值点 + 内部签名头（`v1.<b64url{t,u,ts}>.<hmac_sha256>`，max age 300s） | ✅ | `packages/agent-runtime/agent_runtime/workspace_registry.py:1-22` · `packages/agent-core/agent_core/internal_header.py` · KS `resolve_server_tenant`（优先级：签名断言 > provided > default，客户端自报 `tenant_id="EVIL"` 被覆盖）+ 治理测试 |
| 凭据处理三条链已彻底拆除（本模块不再含 `hashlib/hmac`） | ✅ | `packages/agent-core/agent_core/guardrails/auth.py:14-24` + lint P6（白名单为空 + 4 个退役入口名黑名单）+ lint P12（AST 级，禁凭据形参外流） |
| 入站鉴权 + 会话劫持防护（API_KEY 非空时忽略客户端 thread_id） | ✅ `api_key=""` 则不鉴权 | `applications/agent_server/api/auth.py` `resolve_thread_id` · 联邦 `applications/agent_federation/api/server.py:150,177,216`（⚠️ `DISABLE_AUTH` 是「关鉴权」旁路开关） |
| 数据分级 5 级 + 出域策略（未分类按 CONFIDENTIAL 从严；出域未过 → deny **不得降级到云模型**；PII 入模前脱敏；100% 审计） | 🧪 脚手架 | `applications/exhibition-agent/exhibition_agent/foundation/data_egress.py`（`route_model`/`mask_pii` 为占位 TODO）· 真实调用点 `applications/exhibition-agent/exhibition_agent/graph/nodes.py:110,148,163`；⚠️ 该 app 6 道生产就绪门**全部 `NOT_READY`**（`applications/exhibition-agent/exhibition_agent/foundation/readiness_gate_manifest.json`） |
| Agent 独立身份 NHI（owner / 凭证轮换 / offboarding） | ❌ | |
| kill switch / 级联遏制 | 🟡 | `packages/agent-runtime/agent_runtime/control_plane.py`（pause/cancel/terminate）在位，但随 `scheduler_enabled=False` 不装配 |
| 不可篡改审计日志（append-only / 签名链） | 🟡 | `AuditMiddleware(redact=True)` + `packages/agent-runtime/agent_runtime/forensic.py`；无防篡改结构 |
| 准入控制（PG 持久化队列、事务内原子判 admitted+queued 是否达 capacity、崩溃遗留 queued 标 rejected、**队列不存 question 全文**） | 🔽 `admission_enabled=False` | `packages/agent-runtime/agent_runtime/admission.py` · `applications/agent_server/main.py:174-198,289-297` · 配额 `applications/agent_server/config.py:85-87`；⚠️ `runtime_mode=distributed` 绕过该开关直接建 PG 控制器；⚠️ 统一入口 `run_admitted` 零调用（§6），`query_router` 手写准入 |
| OWASP Agentic Top 10（ASI01–ASI10）→ 模块映射 | ❌ | 缺「哪条 ASI 由哪个模块挡住」的可锚定映射 |

### 2.7 状态 · 可靠性 · 分布式正确性 State & Reliability

| 能力 | 状态 | 证据 / 开关 |
|---|---|---|
| 十态 Execution 状态机 + `can_transition` 转换矩阵（含 `WAITING_EXTERNAL/WAITING_HUMAN/PAUSED/CANCEL_REQUESTED`） | ✅ 代码 / 🔽 落库随 scheduler | `packages/agent-runtime/agent_runtime/execution_status.py:29-95` · ⚠️ 未开 scheduler 时 `status_store=None` ⇒ **执行状态不落库**（`applications/agent_server/main.py:484-485`） |
| 双轨 checkpoint（**会话轨** LangGraph checkpointer / **执行轨** `execution_checkpoints`） | ✅ | `packages/agent-runtime/agent_runtime/planner/durability.py`（Durability 属 Runtime 而非 Planner 业务；按节点落 checkpoint，同 `execution_id` resume，复用已完成节点、尊重依赖边）· `packages/agent-runtime/agent_runtime/planner/durability_pg.py` |
| Lease + `generation` fencing（异 owner 抢过期租约 +1、同 owner 续租不变；`WHERE EXCLUDED.generation >= table.generation` 原子守卫；`ExecutionNotOwned`/`FencedWriteError` fail-closed） | ✅ | `packages/agent-runtime/agent_runtime/planner/durability_pg.py`（`execution_leases`）· `packages/agent-core/agent_core/runtime/lease.py`（`AsyncLease` 幂等 release）· 消费 `applications/agent_server/api/query_router.py:131-146,153,164,211,373`；⚠️ **fencing 覆盖 3/5 类 durable write**（2026-10-14 逐个实读复核）：有守卫 = `PgCheckpointStore`（`packages/agent-runtime/agent_runtime/planner/durability_pg.py:113-146`）、`PgExecutionOwnershipStore`（同文件 `:215-274`，takeover 时 generation+1）、`PgExecutionStatusStore`（`packages/agent-runtime/agent_runtime/execution_state_pg.py:85-110`，SQL 层原子拒绝）；**无守卫 = `packages/agent-runtime/agent_runtime/awaitable_task_pg.py`（全文 `generation` 0 命中）与 `PgSideEffectStore`（`packages/agent-runtime/agent_runtime/planner/durability_pg.py:400` 起）**。~~旧口径「2/5」把 scheduler ownership 记成缺项，来自 2026-09-24 笔记，已被 `docs/plans/production-delivery-anchor-map-2026-10-09.md`「防覆盖保护」行与本轮复核取代~~ |
| Durable Admission / AwaitableTask（crash recovery：据 `provider_task_id` **先 query 外部真实状态**而非盲目重调） | ✅ | `packages/agent-runtime/agent_runtime/awaitable_task.py:1-22` · `packages/agent-runtime/agent_runtime/awaitable_task_pg.py` · 装配 `applications/agent_server/main.py:398-407` |
| 失败决策矩阵（异常分类 × 副作用语义 → `RETRY_SAFE` / `QUERY_BEFORE_RETRY` / `NO_RETRY` / `ABORT`） | ✅ | `packages/agent-runtime/agent_runtime/effect_contract.py:77-192` · 消费 `packages/agent-runtime/agent_runtime/planner/execution_graph.py:23,372`；⚠️ 同文件 `:6-8` 明确**平台不承诺 effectively-once** |
| 重试 / 退避 / 异常分类 / 熔断（Engine+Policy 分离：`ConsecutiveFailurePolicy` + `SlidingWindowPolicy`） | ✅ | `packages/agent-core/agent_core/resilience.py`（585 行）· `packages/agent-runtime/agent_runtime/circuit_breaker.py`（带 fallback、半开试探、兼容 `"half-open"`）· 阈值 `applications/agent_server/config.py:49-50` |
| Scheduler（priority → **per-tenant fairness** → FIFO、全局+per-tenant 槽位、backpressure、`FOR UPDATE SKIP LOCKED`）+ Reaper（lease 回收） | 🔽 `scheduler_enabled=False` | `packages/agent-runtime/agent_runtime/execution_scheduler.py` · 装配 `applications/agent_server/main.py:431-482` · 消费 `applications/agent_server/api/query_router.py:78-102,375-389`（超并发 → 503 + `Retry-After: 5`） |
| Control Plane 6 操作（inspect/pause/resume/cancel/retry/terminate）+ REST（未启用 503、非法转换 409） | 🔽 随 scheduler | `packages/agent-runtime/agent_runtime/control_plane.py` · `applications/agent_server/api/control.py:17-115` |
| 会话并发协调（同 session 串行） | ✅ **process-local** | `packages/agent-runtime/agent_runtime/coordinator.py:1-27` 明示 workers>1 或 replicas>1 下不成立；P4-1 可插拔 `LeaseBackend`（`PgAdvisoryLeaseBackend`）⚠️ **装配未注入 lease_backend**（`applications/agent_server/main.py:281-287`）⇒ 多副本语义未启用；P4-3 诚实改名：`coalesce` 已从策略枚举移除 |
| 幂等 | 🟡 **装配缺口** | `PgIdempotencyStore` 在 `applications/agent_server/main.py:73` 构建 → `:224` 解包 → 此后无使用；`PlannerRuntime.__init__` 无该参数（`packages/agent-runtime/agent_runtime/planner/protocol.py:364-386`）⇒ 现仅 callback 层「终态 no-op」 |
| SideEffectStore（副作用证据） | 🟡 仅联邦接线 | 联邦 `applications/agent_federation/planners/__init__.py:44-57` 传了；**agent_server 未传** ⇒ 双轨 HA 语义不对等（B 接管 resume 时无法判断哪些 step 真落地）；HA 测试 `tests/ha/test_h8_side_effect_before_checkpoint.py` |
| Execution Recovery（Reaper / RecoveryManager / Rescheduler / `MARK_HUMAN`） | 🟡 **P1-7** | `packages/agent-runtime/agent_runtime/execution_recovery.py:1-16` NOT WIRED（在位的是功能更窄的 `SchedulerReaper`） |
| State Schema Migration（链式 `v1→v2→…`） | 🟡 **P1-7** | `packages/agent-runtime/agent_runtime/state_migration.py:1-19` NOT WIRED；实际只打版本戳（`packages/agent-runtime/agent_runtime/planner/durability.py:60-61`），`load()` 不跑迁移链 |
| Large Payload Externalization（`{"__external__":true,...,"checksum":"sha256:..."}`） | 🟡 **P1-7** | `packages/agent-runtime/agent_runtime/payload_externalization.py` NOT WIRED；在位替代 = `packages/agent-runtime/agent_runtime/context/tool_result.py`（默认关） |
| Outbox Pattern（第三方副作用与本地事务一致） | ❌ | |
| checkpoint 保留清理（每 `(tenant,thread,ns)` 留最新 N 条） | ❌ **app 侧无** | 等价实现只在联邦 `applications/agent_federation/agent/checkpoint_cleaner.py`（`CHECKPOINT_KEEP_PER_THREAD=5`） |
| revert 会话回退（原子单事务、不删历史 checkpoint 支持 redo、跨用户禁止、`revert_audit` 列） | ✅ | `packages/agent-runtime/agent_runtime/revert.py` · 装配 `applications/agent_server/main.py:299-303` · REST `applications/agent_server/api/session_router.py:51` |
| Schema migration 系统（`schema_migrations` 元表 + `pg_advisory_xact_lock` 跨实例互斥 + baseline stamp + `{{vector_dim}}` 模板） | ✅ 11 个迁移 | `packages/agent-runtime/agent_runtime/migrations/runner.py` · 红线：禁在 `packages/agent-runtime/agent_runtime/db.py` 内联 `CREATE TABLE` |
| 限流四层（入站拒绝式 + 出站阻塞式保护第三方 API + admission 三维配额 + 联邦 tenant token bucket + 并发闸） | ✅ 部分 | `packages/agent-core/agent_core/guardrails/ratelimit.py` · `applications/agent_federation/gateway/rate_limit.py`（RPM 60 / burst 10）· `applications/agent_federation/api/server.py:201`（`MAX_CONCURRENT_TASKS=10`）· ⚠️ Skill 级中间件未装配 |
| HA 验证套件（真 kill -9 双进程 + 双副本 compose + CI `.github/workflows/ha.yml`/`.github/workflows/ha-assembly.yml` + k8s manifests） | ✅ 脚本级 | `scripts/ha_real_kill_verify.py` · `tests/ha/` 19 文件 · `docker-compose.ha.yml` · `deploy/k8s/`；⚠️ **端到端双实例物理故障转移验收未达**，不得当作已上线能力声明 |

### 2.8 可观测 · 评测 · 学习 Observability & Evals

| 能力 | 状态 | 证据 / 开关 |
|---|---|---|
| OTel tracing（懒导入 + no-op 铁律、幂等 init、统一属性 `config_hash/request_id/user_query_hash`、OTLP gRPC/HTTP/console） | 🔽 `otel_enabled=False` | `packages/agent-core/agent_core/tracing.py` · 装配 `applications/agent_server/main.py:238-260` · `AGENT_CORE_TRACE_ENABLED=false` |
| **tracing 三态可诊断**（UNINITIALIZED / DISABLED / DEGRADED(记真因) / ACTIVE） | ✅ | `packages/agent-core/agent_core/tracing.py:49-56` · `/health` `otel_status`；设计目的=让「显式关」与「坏了」可区分 |
| 装配顺序硬约束（`init_tracing` **必须早于** `build_chat_model()`） | ✅ | `applications/agent_server/main.py:226-237` 注释；反序 ⇒ Langfuse 抢全局 provider、Jaeger 面静默而 `/health` 仍报 ACTIVE（D-LF-1，2026-10-13 现网实测） |
| W3C traceparent 跨服务传播 / 请求级 span 中间件（旁路不失明，覆盖 429/409/cache_hit/断连） | ✅ | `packages/agent-core/agent_core/tracing_propagation.py` · `packages/agent-core/agent_core/tracing_middleware.py` · lint L-1/L-2/L-3 |
| Jaeger | 仅 OTLP 接收端 | thrift exporter 已归档（`applications/agent_server/main.py:229-231`） |
| Langfuse（意愿灯 `langfuse_enabled` vs 运行态灯 `langfuse_ready` 分离；判据在启动期算，绝不在探针里构造客户端） | 🔽 三键齐才启 | `applications/agent_server/config.py:53-55,166-167` · 装配单点 `applications/agent_server/agent/llm.py:12-18`（primary+fallback 全路径）· 联邦 `applications/agent_federation/agent/tracing/langfuse_adapter.py` |
| 统一事件面 `EventBus`（多 sink 扇出 + 逐 sink 异常隔离）+ 4 通道 monitor | ✅ | `packages/agent-core/agent_core/events.py` · `packages/agent-core/agent_core/monitor.py`（WebSocket/LegacyStream/Callback/**OTelSpan**）· `request_id` uuid4 |
| `/health` 能力灯（实测响应 **25 键 = 共享基类 13 + 本 app 独有 12**；报运行态真值 = 装配与否，不报 settings 意愿值） | ✅ | 由 `18b6954`（2026-10-10）落地并同批新增契约测试；`applications/agent_server/api/health_router.py:32-62` · `applications/agent_server/schemas.py:114-154` · `applications/agent_server/tests/test_health_fields.py`（2026-10-14 实跑 **14 passed**）；⚠️ 两点边界：①仅 `scheduler`/`control_plane` 有「拨 `SCHEDULER_ENABLED` 返回值必须变」的断言，`cost_governance`/`forensic` 无开关跟随断言；②`forensic` 位是 `trajectory_store` 非空的**代理语义**（`:50`），不等于 ForensicContext 装配态 |
| 配置指纹 `config_hash` 注入 span（生产与评测同源，防「生产反向 import eval」倒挂） | ✅ | KS `applications/knowledge-service/knowledge_service/conf/config_hash.py` + `packages/agent-core/agent_core/tracing.py` |
| OTel **GenAI 语义约定**对齐（`gen_ai.*` 键名常量表 + 键存在性断言 + lint；18 个 well-known 操作名；content capture 是 Opt-In） | 🟡 | 现用自研属性名，无 `gen_ai.*` 键表 ⇒ 上游改键名后**查询静默返回空、不报错**的风险形状未被对冲 |
| 评测集 golden | ✅ | `eval/golden.jsonl` **15** · `eval/wenda_data_agent_golden.jsonl` 5 · `eval/dialogue_framework_golden.jsonl` 8 · KS `applications/knowledge-service/eval/golden_queries.jsonl` **73** · exhibition `applications/exhibition-agent/exhibition_agent/foundation/golden_cases/sample_golden.json` + `applications/exhibition-agent/skills/exhibition-readonly/tests/golden_cases.json` |
| ⚠️ 本机有、**不入库**的评测集 | 非门禁 | KS 另有 65 条 real golden 集与 30 条 adjudication 模板两份文件均被 .gitignore 显式忽略（第 129 / 133 行）⇒ **不得作为对外证据引用**，别人 clone 后取不到；本文按 `AGENTS.md` 规矩只以普通文本登记 |
| `eval/run_eval.py` **进 CI 唯一门禁**（`--fail-below 0.8`；`--require-llm` 缺 key 退出码 2 **不假装通过**） | ✅ | `eval/run_eval.py` · `Makefile:122 ci: lint test eval` |
| 双 Planner 同 golden 基线 | ✅ | `eval/run_planner_eval.py` · `eval/baselines/planner_{deterministic,agentic}_latest.jsonl`（各 12 条）；agentic 轨**只评协议结构不评能力匹配** |
| 检索指标库（recall@k / hit_rate@k / mrr / ndcg@k）+ 统计判定原语（配对 bootstrap CI、spearman/kendall、cohen κ，全接受 seed；退化输入返回中性值而非抛错，**防「把无法判定伪装成判定为显著」**） | ✅ | `packages/agent-core/agent_core/metrics/{retrieval,compare}.py` |
| KS 评测体系（RAGAS `applications/knowledge-service/eval/score_ragas.py`、路由消融、e2e、`applications/knowledge-service/eval/meta_eval_judge.py` 自述「打分 API 未接线 ⇒ 不计一致性、**不伪造**」、基线快照） | ✅ 成熟 | `applications/knowledge-service/eval/` · 六个 eval-rag 目标由**根 Makefile:69-120** 驱动（KS 自身无 Makefile，勿写成 KS 的 Makefile） |
| LLM-as-Judge 换 provider 去偏（缺配置则降级同主模型并告警） | ✅ | `applications/agent_federation/evaluation/judge.py` |
| Trajectory 持久化（plan/steps/latency/tokens/cost/snapshot） | ✅ | `packages/agent-runtime/agent_runtime/trajectory/{models,store,store_pg}.py` · 装配 `applications/agent_server/main.py:75` |
| Trajectory Replay（5 类 divergence：order / extra_call / missing_call / result_change / error_change，复用 `execute_plan` 真链） | 🟡 | `packages/agent-runtime/agent_runtime/trajectory/replay.py` 仅 `packages/agent-runtime/tests/test_replay.py` 使用，**无 HTTP 端点、无脚本入口** |
| 漂移诊断 forensic（model/prompt/skill/planner/policy 版本 + external receipt → `divergence_diagnosis` 定位漂移源） | ✅ 部分 | `packages/agent-runtime/agent_runtime/forensic.py` · 被 `packages/agent-runtime/agent_runtime/planner/execution_graph.py`/`packages/agent-runtime/agent_runtime/planner/protocol.py` 真实引用；⚠️ `/health` 的 `forensic` 字段被简化为「trajectory_store 非空」 |
| pass^k（k 次独立试验**全部**成功，与 pass@k 方向相反）/ flakiness（N=5~10 取 pass rate） | ❌ | |
| golden 治理机制（冻结/活跃/追加三区分、append-don't-replace、升级后 rebase、PSI 漂移触发） | ❌ 未成机制 | 设计已在 `noctilucent-lamp` 侧成文，仓库无落地 |
| 指标基线（错误率 / 超时率 / 降级率 / TTFT / TPOT 有基线且失败可分类） | ⚠️ **待标定** | 无 Metric Registry、无仪表盘；纪律：无基线数字标「待标定」、禁止自证 |
| 灰度（`sha256(user_id)%100 < GRAY_PCT`，比例进缓存 key 防串味） | 🔽 `GRAY_PCT=0.0` | `applications/agent_federation/gateway/gray.py`（因 user_id 属可识别信息而弃 MD5） |
| 金丝雀斜坡（1%→10%→100% + 回滚线先行）/ **影子流量旁路比对** | ❌ | |
| 混沌 / fault injection | ✅ 内部测试级 | `tests/ha/fault_injector.py` + `tests/ha/haprobe.py`；未平台化；⚠️ 无 **Omission 族**（HTTP 200 空内容绕过错误处理）注入 |
| 红队 / 越狱评测集 | ❌ | |
| 用户反馈信号闭环（点赞 / 转人工 / 换说法再问 / 提前退出） | ❌ | 有 WebSocket/Callback sink 通道，无反馈采集与回流面 |
| Prompt / Skill 版本与发布流水线 | 🟡 | `packages/agent-runtime/agent_runtime/skill_lifecycle.py`（EXPERIMENTAL/STABLE/DEPRECATED/RETIRED + `check_compatibility` 决定能否 resume，动机：热更新会破坏 Replay/Checkpoint/Workflow）在位，无发布/回滚流水线 |

### 2.9 知识与数据 Knowledge / RAG / NL2SQL

| 能力 | 状态 | 证据 |
|---|---|---|
| 导入链路（MinerU pdf→md → 图片 VL 摘要 → 分段 → 商品名识别 → bge embedding → 入 Milvus） | ✅ / 🔽 `IMG_SUMMARY_ENABLED` 默认空=关 | KS `applications/knowledge-service/knowledge_service/import_process/agent/main_graph.py:39-109` 与 6 个节点文件 |
| 四路并行检索（embedding / **HyDE** / KG / web-MCP）+ 虚拟分叉合并 + 逐路超时降级为「该路未召回」**绝不向上抛** | ✅ | KS `applications/knowledge-service/knowledge_service/query_process/agent/main_graph.py:24-33,71-78` · `applications/knowledge-service/knowledge_service/query_process/agent/fanout.py`（桥 `agent_core/tools/guarded.guarded_invoke`） |
| RRF（k=60、per-channel weights）+ 混合 dense 0.8 / sparse 0.2（bge-m3 稀疏向量） | ✅ | KS `applications/knowledge-service/knowledge_service/query_process/agent/nodes/node_rrf.py`（span 注入 k/weights/in_n/out_n）· `applications/knowledge-service/knowledge_service/conf/retrieval.yaml:7-18` |
| Rerank（bge-reranker-v2-m3、`Semaphore(8)` 防显存放大、异常 passthrough 保原序）+ **断崖式动态 TopK**（gap_ratio 0.25 / gap_abs 0.5 / min 1 / max 10） | ✅（KS）/ 🔽 `rerank_enabled=False`（agent_server） | KS `applications/knowledge-service/knowledge_service/query_process/agent/nodes/node_rerank.py:1-25` + `applications/knowledge-service/knowledge_service/conf/rerank.yaml` · `applications/agent_server/rag/rerank.py` |
| 知识生命周期 6 态 + 5 条合法边 + `REQUIRED_METADATA_FIELDS`；**只有 PUBLISHED 能进生产检索** | ✅ | `packages/shared-schemas/shared_schemas/knowledge_lifecycle.py:26-40` · KS `applications/knowledge-service/knowledge_service/core/knowledge_lifecycle_integration.py:44-62` |
| 多租户 ACL **检索入参下推**（`item_name + tenant_id + scope_type` 复合过滤，非召回后过滤，INV-8） | ✅ | KS `applications/knowledge-service/knowledge_service/query_process/agent/nodes/node_search_embedding.py:71-78` · 每端点 `resolve_server_tenant` |
| NL2SQL 12 节点（关键词抽取 → 并行召回 column/metric/value → 合并 → 并行过滤 table/metric → 生成 → 校验 → 执行/纠错回环 ≤3 次）+ 元知识 + 双库分离（meta + 只读 dw） | ✅ | `applications/nl2sql-service/nl2sql_service/agent/graph.py:37-48`（12 个 add_node） · `applications/nl2sql-service/nl2sql_service/services/meta_knowledge_service.py` · `applications/nl2sql-service/nl2sql_service/repositories/pgvector/` |
| agent_server 自有 RAG（pgvector + BM25 索引签名缓存 + RRF(60)；隔离 `(tenant 安全边界, workspace 归属维)` 成对出现） | ✅ | `applications/agent_server/rag/store.py:26-31,59-95`（ADR-0006 T9/W1）· `rag_top_k=4` 理由见 `applications/agent_server/config.py:58` |
| 存储栈（Milvus 4 集合 / **Neo4j** KG / MinIO / MongoDB 历史 / 硅基流动 embedding+rerank） | ✅ | KS `applications/knowledge-service/knowledge_service/core/config.py:79-89` · `applications/knowledge-service/knowledge_service/clients/` |
| SSE 流式检索 + 会话历史读写清 + 任务状态 | ✅ | KS `applications/knowledge-service/knowledge_service/api/query_router.py:313-325` · `applications/knowledge-service/knowledge_service/utils/sse_utils.py` |
| 压测 | ✅ | KS `applications/knowledge-service/benchmark/locustfile.py` |
| GraphRAG（实体抽取→关系→社区检测→检索→排序→生成 六步名义） | 🧪 仅 demo | `applications/kefu-service/kefu_agent/graph_rag.py:1-18` 数据源是**模块内硬编码 dict** `_KNOWLEDGE_BASE` |
| **citation（幻觉治理第 1 层）** | ❌ 未见实现 | |
| **claim-level faithfulness（NLI）/ abstention 低置信拒答** | ❌ | |
| 数据血缘 / 冲突标记（Conflict Warning） | ❌ | 分级仅有 exhibition 脚手架 |

### 2.10 平台产品面与接入 Platform Surface

| 能力 | 状态 | 证据 / 开关 |
|---|---|---|
| 多模型 provider 抽象 + registry（LRU、key 含不透明 `api_key_slot` 不再摘要密钥）+ fallback | ✅ | `packages/agent-core/agent_core/llm/{protocols,providers,registry,fallback,fallback_lc}.py`；`profile["max_input_tokens"]` 驱动摘要阈值自适应 |
| 结构化输出（**显式 `method="function_calling"`**，因三家 `json_schema` 行为互不相同；差异已实测记录） | ✅ | `applications/agent_server/agent/router.py:88-91` · `packages/agent-runtime/agent_runtime/planner/graph_compose.py:146-156` · `packages/agent-core/agent_core/llm/providers.py:78-80` · `.env.example:54-74` |
| Embedding provider 统一选型（远程/本地 bge/Mock；维度 512↔1024 由 provider 派生；启动预热 + 真值灯 `embedding_real`） | ✅ | `packages/agent-core/agent_core/memory/embedder.py`（328 行）· `applications/agent_server/main.py:79-98,278` · `EMBEDDING_REQUIRE_REAL=true` 为调用期硬失败（刻意不升级为启动 crash-loop） |
| SSE 统一契约（graph 路径与 Planner 路径事件同构，客户端无感） | ✅ | `packages/shared-schemas/shared_schemas/sse.py:13-30` · `packages/agent-runtime/agent_runtime/planner/protocol.py:738-780` |
| 运行时模式 `local / single_node / distributed`（distributed 无 `DATABASE_URL` **启动即拒**） | ✅ | `applications/agent_server/config.py:140-144` · `applications/agent_server/main.py:205-210,178-183` |
| **架构不变量 lint 16 条**（多数白名单为空 = fail-closed）+ 文档防漂移门禁 + 治理测试 28 + HA 测试 19 | ✅ 进 CI | `scripts/lint_architecture.py`（P2/P4/P5/P6/P7/P8/P9/P10/P11/P12/**P13** + L-1/L-2/L-3/L-4/**L-5**）· `scripts/check_doc_sync.py`（存在性基准 = `git ls-files`）｜ 计数口径（2026-10-16 更新，沿用 roadmap #9 定的三口径）：**门禁编号 16 条**（14→15 加 L-5 观测装配存在性，阶段2 #12；15→16 加 P13 身份装配存在性，阶段2 #11）／**实现函数 `check_*` 17 个**／**治理·HA 用「测试文件数」口径**（28 与 19，非用例数；本轮新增 `tests/governance/test_identity_gate_coverage.py`）。对外仍引用「门禁编号」这一口径 |
| 控制台前端（会话/准入/控制面可视化） | ✅ | `applications/agent_server/api/console_router.py` + `applications/agent_server/static/` |
| **Agent Registry / Agent 目录与市场**（登记、发现、owner、下线） | ❌ | |
| **Tool Gateway**（统一 API 资产 + RBAC + 计量 + 限流熔断配额降级） | ❌ | MCP 客户端不算（那是消费侧） |
| **触发器：Cron / 事件 / 主动式长时运行** | ❌ | 只有被动 `POST /api/callback/{task_id}` |
| 渠道接入（企微 / 钉钉 / Slack / 邮件 / Web / Voice） | 🟡 | KS `applications/knowledge-service/knowledge_service/query_process/page/`、`applications/knowledge-service/knowledge_service/import_process/page/` 内嵌 HTML 控制台；无 IM 渠道 SDK |
| 租户资源配额池（LLM 额度 / 向量库 / GPU / 日志存储） | 🟡 | `cost_governance` 默认关且 limit=0；资源级配额 ❌ |
| 微调 / 蒸馏 / SFT 数据飞轮 | ❌ | 与既有对外口径一致（本项目不声称训练侧动手深度） |
| 多模态（图像输入解析） | 🟡 | KS pdf→md + 图片 VL 摘要在位；端到端多模态对话 ❌ |
| 部署与分发（K8s manifests、rev 门禁 build/distribute、双运行时两套镜像库） | ✅ 运维面 | `deploy/k8s/` · `AGENTS.md` §内网测试环境 126 |

---

## 3. 缺项补全清单（按优先级）

| 级 | 缺项 | 为什么现在就该动 | 锚点 |
|---|---|---|---|
| **P0** | 循环**预防**三层指纹（精确 → 状态 → 语义余弦 >0.95） | 现状是「只有恢复、没有预防」，且 `enable_loop_fingerprint=False` 只做了第一层的一半 | `applications/agent_server/config.py:116` · `packages/agent-runtime/agent_runtime/planner/protocol.py:349-432` |
| **P0** | 语义缓存空租户串跨租户读 | 唯一一条「已实现代码里带安全语义的洞」，不是缺功能而是缺把关 | `packages/agent-runtime/agent_runtime/cache.py:49-55` + `applications/agent_server/api/query_router.py:162` |
| **P0** | 输出护栏从「仅告警」改为可拦截（与输入侧对称） | 输入拦、输出放，被追问「防得住泄露吗」答不硬 | `applications/agent_federation/gateway/output_guard.py` + `applications/agent_federation/agent/main_agent.py:658-665` |
| **P0** | **一个真实使用者** | 既有定性判定原话：「缺的不是程度，是一个真实使用者。这是质变点，不是量变点」 | `docs/TODO.md` §0 · `docs/plans/arch-audit-2026-09-24.md` |
| **P1** | provider prompt caching + 成本归因出数面 | 语义缓存 agentic 场景命中率仅 5–15%；真大头在输入输出 100:1 下的 prompt 缓存 | `packages/agent-core/agent_core/cache/`（无 `cache_control`）· `packages/agent-runtime/agent_runtime/trajectory/`（有数无面） |
| **P1** | 幻觉三层：citation → claim-level NLI → abstention | 第 1 层都不在代码里 | 全域无 |
| **P1** | MCP 传输换 Streamable HTTP + 规范级授权（OAuth2.1 RS / RFC 9728 / RFC 8707 / CIMD / EMA） | 现在绑的是**已弃用的 HTTP+SSE**，规范进入 12 个月弃用窗口 | `packages/agent-runtime/agent_runtime/mcp_client.py:146` · §5 参考来源 |
| **P1** | MCP **服务端** + Agent Registry + Tool Gateway | 平台要从「自己的运行时」变「别人的运行时」，这三件是入口面 | §2.5/§2.10 全 ❌ |
| **P1** | 补齐 4 个装配缺口：幂等注入 · `side_effect_store`（app 侧） · `lease_backend`（多副本） · checkpoint 保留清理（app 侧） | 都是「写了没注入」，且直接决定双轨 HA 语义是否对等 | §6 |
| **P1** | 评测治理机制：golden 三区分 + rebase + pass^k + 指标基线看板 | 评测是自评「已站对位置」的最高杠杆项，机制尚未落成代码 | §2.8 |
| **P2** | A2A（Agent Card + Opaque Execution） | 跨组织互操作，现为 0；按「规范未落地项进观察列表，不进排期」的纪律处置 | 外部：noctilucent-lamp 的 wiki/agi/a2a/a2a-protocol.md（本机路径，不入库，故不用反引号） |
| **P2** | 触发器 / Cron / 事件驱动 + 渠道接入 | 从「问答平台」到「长时运行 Agent 平台」的分水岭 | §2.10 |
| **P2** | 记忆写侧防投毒 + 事件流/物化视图 + 冲突反问 | 对应 OWASP ASI06（Memory & Context Poisoning），2026 新增类目 | §2.3 |
| **P2** | tool explosion（分组 / 懒加载 + 约束解码）+ Tool Contract Test | 工具 >20 后选择准确率显著下降；注意**别动态增删工具定义**（破 KV-Cache） | §2.5 |
| **P2** | NHI Agent 独立身份 + kill switch + 不可篡改审计 + ASI01–10 映射文档 | 治理从事后审查到内置控制 | §2.6 |
| **P2** | 影子流量 / 金丝雀斜坡 / 红队集 / 反馈信号闭环 | 上线后四层监控中目前只覆盖第二层（可观测） | §2.8 |

---

## 4. 一致性残口（4 条，未改代码，仅登记）

| # | 现象 | 位置 | 影响 |
|---|---|---|---|
| 4.1 | 压缩触发 `ratio=0.8`，而外部既有最佳实践建议 **60–70% 窗口**（留余量，避免触发时已来不及） | `applications/agent_server/config.py:70-75` | 128K 窗口下 102K 才压，长轨迹任务可能一轮 tool result 就溢出 |
| 4.2 | `ContextBudget(model_window=32_000)` 在 governor 装配处**硬编码**，与 `model_context_window=128000` 不同源 | `applications/agent_server/main.py:129-171` | 预算尺子与实际模型窗口不一致：governor 路径偏保守，`applications/agent_server/context.py` 路径偏激进 |
| 4.3 | workflow 文件名 `packages/agent-runtime/workflows/qa_pipeline.yaml` 与内部 `name: "search_pipeline"` 不一致 | `packages/agent-runtime/workflows/qa_pipeline.yaml` | `discover_workflows` 按文件注册，按名排查/引用时出现两个标识 |
| 4.4 | ~~**文档↔代码漂移**：README 与 TODO 仍声称 `/health` 不上报 V3 四组件~~ **已于 2026-10-14 回写完毕** | `README.md`（§`GET /health` 样例与说明）、`docs/TODO.md` §3、`docs/plans/plan-production-delivery-roadmap-2026-10-09.md` 阶段1 #6 + 阶段小计 + §四 #3、`docs/plans/production-delivery-anchor-map-2026-10-09.md` 健康检查行 | 原状：四处同源旧话由 `9921f203`（2026-09-24）写入，被 `18b6954`（2026-10-10）取代后未回写；README 样例还少列 15 个键并把 `status` 写成 `ok`（实测枚举为 `healthy`）。处置：全部按「只订正状态、不翻转复选框」处理（`git diff` 内无 `- [ ]` ↔ `- [x]`），§0 计数口径不受影响；#6 工时以「20 → 剩余 19」双口径写明。教训登记：`scripts/check_doc_sync.py` 只验路径存在性，**抓不到语义漂移** |

> 4.1–4.3 属代码内不一致，4.4 属文档与代码不一致；四条均**未改代码**，只登记事实。闭合 TODO 开项会改动该文件的计数口径，须按 `docs/TODO.md` 自己的规矩（先定义计数口径、逐条从文件生成）另行处理，本表不代作决定。

---

## 5. 默认关开关台账（14 条）

**agent_server（`applications/agent_server/config.py`，pydantic-settings，env 大写同名覆盖）**

| 开关 | 默认 | 连带影响 |
|---|---|---|
| `admission_enabled` | False | 且需 `db_enabled`；`runtime_mode=distributed` 绕过（直接建 PG 控制器） |
| `otel_enabled` | False | 且需 `otel_exporter != "none"`；连带 Langfuse/Jaeger 面无数据 |
| `mcp_enabled` | False | 且 `mcp_servers` 非空才装配 |
| `guard_enabled` | False | 输入护栏（PII + injection）整体关 |
| `scheduler_enabled` | False | **连带 control_plane / status_store / reaper 全部不装配**，执行状态不落库 |
| `cost_governance_enabled` | False | 且三个 `budget_limit_*` 默认 0 = 开了也不限 |
| `rerank_enabled` | False | agent_server 轨（KS 轨默认开） |
| `memory_extraction_enabled` | False | 记忆写入退化存原文 |
| `tool_result_compression_enabled` | False | 注释理由：「避免改变现有返回结构」 |
| `enable_loop_fingerprint` | False | 注释理由：「避免误伤合法重放/重规划」 |
| `planner` | `"deterministic"` | `auto`(Mode Selector) 为 opt-in；`graph`/`agentic` 需显式设 |
| `database_url` / `runtime_mode` | `""` / `"local"` | 无 PG ⇒ 内存模式，跨会话记忆恒空 |
| `api_key` | `""` | 空即不鉴权（限流与载荷护栏照常） |
| 5 个 `*_service_url` / `search_api_key` / `sql_dsn` / `langfuse_*` 三键 | `""` | 空即**不注册该能力**，`/health` 能力灯如实熄灭 |

**内核 / 身份 / 联邦（env 直读）**

`DEPLOY_ENFORCE_IDENTITY=false` · `TENANT_JWT_ENFORCE=false` · `TENANT_HEADER_ENFORCE=false` · `SINGLE_TENANT` 未设 ⇒ `insecure` 态 · `SEMANTIC_MEMORY_ENABLED=false` · `MEMORY_DUAL_SCOPE=false` · `AGENT_CORE_TRACE_ENABLED=false` · `CACHE_ENABLED=false` · `GUARD_ENABLED=false` · `INTENT_ENABLED=false` · `PLANNER_ENABLED=false` · `REFLEXION_ENABLED=false` · `DYNAMIC_AGENT_ENABLED=false` · `AGENT_MODE=local` · `GRAY_PCT=0.0` · `IMG_SUMMARY_ENABLED=""` · `DISABLE_AUTH=false`（注意这是「关鉴权」的旁路开关）

---

## 6. 零生产调用模块清单（13 条）

> **先定义口径，别与本仓其它计数混读**：本表判据是「**全仓生产代码零 import**（排除 `**/tests/**` 与 `docs/**`）」，共 13 条；而 `docs/plans/production-delivery-anchor-map-2026-10-09.md` 的「未接线 = **5 处**」判据是「**带 `STATUS: NOT WIRED` 自述标注**」，且该文件明确把 `forensic` / `effect_contract` / `skill_lifecycle` **排除**在未接线之外（它们在运行时生产链内部被调用，不是孤岛）。两个数都成立，回答的是不同问题：前者问「没人用」（含未自述的 9 条），后者问「账面声明过没接线」（5 条）。本表 §6 的前 4 条即那 5 处中的 4 个 `agent-runtime` 模块（第 5 处是 exhibition `skill_router`，另见 §2.5）。

`packages/agent-runtime/agent_runtime/reflection.py`（ReflectionEngine）· `packages/agent-runtime/agent_runtime/working_memory.py` · `packages/agent-runtime/agent_runtime/memory_seed.py` · `packages/agent-runtime/agent_runtime/episode_dedup.py` · `packages/agent-runtime/agent_runtime/embedding_recall.py` · `packages/agent-runtime/agent_runtime/context/skill_context.py` · `packages/agent-runtime/agent_runtime/admission_gateway.py:56 run_admitted` · `packages/agent-runtime/agent_runtime/trajectory/replay.py` · `packages/agent-runtime/agent_runtime/skills/middleware.py:198 RateLimitMiddleware` · `packages/agent-runtime/agent_runtime/human_task.py`（P1-7）· `packages/agent-runtime/agent_runtime/execution_recovery.py`（P1-7）· `packages/agent-runtime/agent_runtime/state_migration.py`（P1-7）· `packages/agent-runtime/agent_runtime/payload_externalization.py`（P1-7）

外加 4 处「构建但未注入 / 装配缺项」：`applications/agent_server/main.py:73,224` 幂等 · `applications/agent_server/main.py:408-424` side_effect_store（app 侧）· `applications/agent_server/main.py:282-285` lease_backend · `applications/exhibition-agent/exhibition_agent/foundation/skill_router.py`

**判定方法（可复现）**：模块名在全仓生产代码（排除 `**/tests/**` 与 `docs/**`）中的 import 命中数 = 0 ⇒ 归本表。P1-7 四条另有模块头 `STATUS: NOT WIRED` 自述作为第二证据。

---

## 7. 待拍板（3 条，均为口径决策，非技术缺口）

1. **对外是 6 类还是 9 类。** 既有定稿口径是「编排/上下文/工具/安全/可靠性/可观测」六类公共能力；但**记忆**（可靠 Agent 五章之 Ch2）与**评测治理**（本文自评最高杠杆项）不在六类词面里，本文又加了知识数据与平台产品面两域。要么对外固定为「6+3」并说明切法，要么明确「记忆算上下文子域」。两套口径并存会被追问。
2. **`已上线` 的边界。** 本文所有 ✅ 只声明「代码默认开」。V3 执行链路（Scheduler/ControlPlane/CostGov/Forensic）默认关，端到端双实例物理故障转移验收未达 ⇒ **不得读作已上线**（`AGENTS.md` V3 段落原文）。
3. ~~**本文是否进 `ARCHITECTURE.md` / `AGENTS.md` 索引。**~~ **2026-10-14 已定：进 `README.md`**（§架构 末「能力现状全景（四档交底）」小节）。⚠️ 操作约束登记给后人：`scripts/check_doc_sync.py` 的存在性判定基准是 `git ls-files`（版本控制清单），**未入库的文件被引用即把门禁跑红**——本轮实测先加指针后门禁报 `README.md:187: 路径未纳入版本控制`，`git add` 本文后才复绿。`ARCHITECTURE.md` / `AGENTS.md` 暂未加，是否加由使用者决定（加了同样须与本文同一次提交）。

---

## 8. 参考来源

**仓库内（本文主证据）**：`ARCHITECTURE.md` · `AGENTS.md` · `docs/TODO.md` · `docs/architecture/agent-execution-platform.md` · `docs/plans/arch-audit-2026-09-24.md` · `scripts/lint_architecture.py` · 以及 §2 各表内联的文件:行号。

**外部（用于确定「缺项判据」与协议现状）**

- Agent Harness / Framework / MCP 分层：https://aihot.news/items/cmu1sy0pb02s4rore3rgpnuj6
- Harness 是 Agent 可靠性瓶颈（ETCCL + O/V/G 分层）：https://blog.csdn.net/m0_55049655/article/details/164450739
- 2026 Agent 平台工程化实践（五模块必要条件）：https://blog.csdn.net/weixin_29048309/article/details/167238069
- Harness 分层与护栏引擎（网关/压缩/持久化/沙箱/验证）：https://m.blog.csdn.net/fitbit/article/details/165334536
- DeepSeek Harness（dsh）能力构成清单：https://blog.csdn.net/m0_58426858/article/details/164174651
- MCP 2026-07-28 规范拆解（无状态核心 / Tasks 扩展 / OAuth 六 SEP）：https://blog.csdn.net/deepseek23/article/details/167274978
- MCP 收缩协议边界（`Mcp-Method`/`Mcp-Name` 头、`ttlMs`/`cacheScope`、`tools/list` 确定性排序、12 个月弃用窗口）：https://developer.aliyun.com/article/1755212
- MCP Apps / Tasks / Roots·Sampling·Logging 弃用清单：https://blakecrosley.com/zh-Hans/guides/obsidian
- MCP 2026 路线图（Agent 身份：DPoP / Workload Identity Federation / WIMSE）：https://m.toutiao.com/article/7682238954141139471/
- Agent Registry / Tool Gateway / MCP-over-API 网关化：https://docs.cloud.google.com/api-gateway/docs/mcp-overview
