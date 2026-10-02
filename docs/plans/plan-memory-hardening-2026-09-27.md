# Memory 层加固实施计划

| 项 | 内容 |
|----|------|
| 日期 | 2026-09-27 |
| 状态 | **部分已执行**：T0 于 2026-10-02 入主干（内核协议下沉），T1 与 T9–T13 已在前序合流落地；T2–T8 尚未执行 |
| 范围 | `agent-runtime` 四类 Memory + `agent-core/memory/typed.py` |
| 结论 | **不重构**：保留架构优势，补齐「多租户一致性 / 检索质量 / 治理可审计性」三处硬伤 |
| 依据 | 本仓库代码实测 + 外部研究报告《AI Agent Memory 企业级落地方案研究报告》(2026-09-26) + 实现层源码级调研（Mem0 / Graphiti / LangGraph / LangMem） |
| 入库来源 | 随 2026-10-01 `integration/v3-into-main` 合流从 `feat/isolation-hardening`@`d4b6faa` 导入（`ARCHITECTURE.md` §5 与 `CHANGELOG.md` 的 09-27 条目引用本文件，而当时 `main`/`v3` 树内均无此文件，`check_doc_sync.py` 实测拦下）。 |
| 主干实态（2026-10-02 重核） | **已落地：T0**（`agent_core/memory/execution.py` 两协议 + `CapabilityReport.supports_episodic`，随 `feat/execution-memory-kernel-onto-main` 并入，两份契约测试新 base 实跑 5 passed）、**T1**（migration `006`–`010` 含 `010_episodic_tenant`、`tests/ha/test_tenant_isolation_real_pg.py`）与隔离域加固线的 T9–T13。**未落地：T2–T8**（T8 = `UserSemanticStore` 薄适配器，ADR-0005 §6 项 3 拍板为单独立项）。ADR-0005 状态据此从「提案」转「采纳」（逐条复验过程见其「状态转正的过程记录」条）。 |

---

## 1. 结论摘要

agent-platform 现有记忆实现**在架构分层与程序性记忆上已领先业界平均**（程序性记忆是业界公认的生产空白，本仓库已有完整沉淀管道）。因此**不推倒重做**，只做加固：

- **保留**：四类分类 + `ContextSelector` + Semantic 两层分离 + `SkillUsageTracker` 生命周期 + `memories` 表的严格租户语义。
- **补齐**：episodic/procedural 的租户隔离缺失、Episodic 检索质量、去重与 provenance、审计与真批删、衰减性能。
- **收口（架构层）**：`agent-runtime` 的执行记忆**不是重复实现，而是内核契约缺位下的必然自建**（内核只覆盖语义记忆）。故不是删一份，而是**协议下沉内核、实现留宿主**——见 ADR-0005 与 T0。

> 本计划是**执行层**文档；架构契约与替代方案论证见 `docs/adr/0005-execution-memory-kernel-contract.md`（提案，待评审）。

---

## 2. 现状盘点（实测）

### 2.1 已有能力

| 能力 | 位置 | 评价 |
|------|------|------|
| 四类分类 + 统一召回协议 | `agent_runtime/memory_types.py` | ✅ 含 `ContextSelector` 按 task_type 选类（qa/execute/analyze/approve），防 context pollution |
| 三因子评分 | `agent_runtime/memory_recall.py` | ✅ `alpha*recency + beta*importance + gamma*relevance` + bigram Jaccard（中文友好） |
| 写路径自动沉淀 | `agent_runtime/memory_sink.py` | ✅ `EpisodicSink` → `ProceduralSink`（每 10 次挖候选 Skill）→ `SkillUsageTracker`（draft/stable/deprecated 升降级） |
| 程序性记忆 | `procedural_memory.py` + `memory_pg.py` | ✅ **业界生产空白，本仓库已落地**，最大亮点 |
| PG 持久化 | `memory_pg.py`（`PgEpisodicStore` / `PgProceduralStore`） | ⚠️ 落库可用，但检索与隔离有缺陷（见 2.2） |
| 衰减 | `memory_decay.py` | ⚠️ 逻辑正确，实现为全表加载 + 逐条删除 |
| 类型化语义记忆 | `agent_core/memory/typed.py` | ✅ pgvector 余弦 + `type_weight × importance × 双曲衰减`；`consolidate` 遗忘；**租户精确匹配且拒绝 default 过渡读**（P0 审计修复，正确） |
| Semantic 两层分离 | `semantic_memory.py`（`SharedSemanticStore` / `UserSemanticStore`） | ✅ 正确区分「文档知识 RAG」与「用户事实 Memory」 |

### 2.2 硬伤清单

| # | 级别 | 问题 | 位置 | 后果 |
|---|------|------|------|------|
| G1 | **P0** | `episodic_memories` / `procedural_memories` **无 tenant_id 列**；`PgEpisodicStore.recall` 全表 `ILIKE`，无租户谓词 | `memory_pg.py:56-105`、migrations `001` | 与 `memories` 表 v5 严格租户语义不一致 → **跨租户可见/泄漏** |
| G2 | **P0** | Episodic 检索仅 ILIKE 关键词，无向量；且 `ORDER BY importance DESC`（非相关性） | `memory_pg.py:63-65` | 语义召回缺失；与 `typed.py` 已有 pgvector 能力割裂 |
| G3 | P1 | 无 `content_hash`，无去重 | `episodic_memories` 表 | 每次执行自动沉淀 → 重复 Episode 堆积 |
| G4 | P1 | 无 provenance（`source_execution_id` / `injected_by` / `confidence`） | 全表 | 工具/模型注入内容无法溯源（对应 MINJA 记忆投毒风险，OWASP ASI06） |
| G5 | P1 | 无审计/变更日志表，`DELETE` 直接生效 | `memory_pg.py:107-113`、`typed.py:320` | GDPR「可证明删除」与回滚能力缺失 |
| G6 | P1 | 衰减为 `list_all(limit=1000000)` + **逐条 delete** | `memory_decay.py:47-71` | O(n) 内存 + O(n) 往返，规模增长后崩塌 |
| G7 | P1 | `ProceduralSink` 每 10 次执行 `list_all()` **全量扫描**提取 pattern | `memory_sink.py:87` | 成本随记忆量线性增长 |
| G8 | P2 | 评分双轨：`typed.py` 用加权融合，`PgEpisodicStore` 用 `ORDER BY importance` | 两处 | 跨类型排序不可比 |
| G9 | P2 | 无生产指标（记忆命中率 / 事实一致性 / 用户纠错率） | `eval/memory_reuse_llm.py` 未产出指标 | 无法证明记忆带来价值 |
| G10 | **P1** | **语义记忆契约悬空**：`UserSemanticStore` 的 docstring 声明后端为「agent-core memory typed.SEMANTIC」，但全仓仅抽象定义 + 2 个测试 mock，**无生产实现**；且 `agent-runtime` 对 `agent_core` 的 import 数为 **0** | `semantic_memory.py:66-80` | 「用户事实」一旦有人另写实现，就会在 `memories` 表之外再造一份存储 → **真双份真相源**；当前属隐患非故障 |

### 2.3 全局架构定性（2026-09-27 修订，取代初版「两条链路各服务一个 app」的判断）

> **自纠**：初版判断「core 链路消费方只有 `agent_federation`」有误。实测 `agent_server/memory/longterm.py:22,90` 同样走 `agent_core.memory.typed`。修正后的定性见下。
> **完整论证见 ADR-0005**（`docs/adr/0005-execution-memory-kernel-contract.md`，提案）。

**核心论断：不是重复实现，而是「内核契约缺位导致的必然自建」。**

| 事实 | 证据 |
|------|------|
| `memory` 法定归属 `agent-core` | `ARCHITECTURE.md:38`（职责含「MemoryStore 统一门面」）；runtime 职责列表 `:39` 无 memory |
| 内核已立下收口纪律 | `agent_core/memory/__init__.py:20-21`「各子包不得再各自为政重复实现——统一从此处 import」 |
| 但内核契约**只覆盖语义记忆** | `store.py:37-60` 的 `CapabilityReport` 仅有 `supports_consolidate/forget/tenant_isolation`，**无 episodic/procedural/working 位** |
| → runtime 只能自建 | `packages/agent-runtime/agent_runtime/memory*.py` 对 `agent_core` import 数 = **0** |
| **反证**：内核一旦给契约，两侧自然收敛 | 语义记忆双侧均走内核：`agent_federation/agent/memory/semantic_memory.py:36-50` + `agent_server/memory/longterm.py:22` |

**修正后的链路表**：

| 链路 | 存的什么 | 消费方 | 落库表 |
|------|---------|--------|--------|
| `agent-core/memory`（`semantic.py` + `typed.py` + `store.py`） | 用户事实 / 偏好（跨会话长期） | `agent_federation` **+ `agent_server`**（双侧均已收口 ✅） | `memories` |
| `agent-runtime/memory_*` | 执行轨迹（episodic）+ 技能（procedural）+ 工作记忆 | `agent_server` + runtime 内部（governor/reflection/dedup/seed） | `episodic_memories` / `procedural_memories` |

**关键衍生事实：`agent_server` 单进程内并行两套记忆**（`main.py:84-100` `_build_memory_hooks` + `:118-135` `_build_context_governor` 走 runtime；`longterm.py:22` 走内核）。二者语义不同、不冲突，但**租户 / 评分 / 审计 / provenance 四处不对称会各自漂移**——这才是真风险。

**另一处命名冲突（易踩）**：`episodic` 在两层同名不同义——
- `typed.MemoryType.episodic` = `memories` 表内一条**情节型事实**；
- `runtime.MemoryCategory.EPISODIC` = `episodic_memories` 表内**一次执行的完整轨迹**。

**判断：两套不合并**（用户画像 vs 执行经验，语义与生命周期均不同，合并会毁掉程序性记忆沉淀管道）。**治理路径 = 协议下沉内核、实现留宿主**，沿用优化 E/P4.3 已验证范式，详见 ADR-0005。

---

## 3. 实施任务

### T0（P1，上位任务）执行记忆协议下沉内核（对应 ADR-0005）

> 本任务是 T1–T5、T8 的**上位依赖**：先把契约立起来，后续补字段/统一评分才有"一处定义、两处遵守"的落点。纯新增、灰度期零行为变更。

- 新增 `agent_core/memory/execution.py`：`Episode` / `ProceduralEntry` dataclass + `EpisodicStoreProtocol` / `ProceduralStoreProtocol`（`typing.Protocol`，`runtime_checkable`）。**仅 stdlib，不引 pydantic**（同 ADR-0004 决策 1 理由）。
- 协议方法签名**一律显式带 `tenant_id`**，沿用 `_tenant_gate.resolve_tenant` 语义（归属不明宁不可见，不跨租户可见）。
- 下沉 `memory_recall.three_factor_score`（bigram Jaccard，中文友好）为内核共享评分函数，供语义侧与执行侧共同调用（消 G8）。
- `CapabilityReport` 增加 `supports_episodic` / `supports_procedural` / `supports_working`。
- `agent_runtime/memory_pg.py` 的 `PgEpisodicStore` / `PgProceduralStore` 声明实现内核协议；SQL 实现保留原处。
- 新增开关 `EXECUTION_MEMORY_KERNEL_CONTRACT`（默认 false），true 时做 `isinstance` 断言，**不改运行时行为**。
- 协议 docstring 显式声明 `episodic` 两层同名不同义（见 §2.3），并加测试锁定语义。
- **内核零依赖 CI 断言**：`agent_core/memory/execution.py` 仅 import stdlib。

**不做**：不搬 SQL 实现、不搬 sink 编排、不搬 LLM 抽取（ADR-0004 决策 6）、不改表结构。

### T1（P0）补齐 episodic / procedural 租户维度

**迁移** `packages/agent-runtime/agent_runtime/migrations/006_episodic_tenant.up.sql`：

```sql
ALTER TABLE episodic_memories ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default';
UPDATE episodic_memories SET tenant_id = 'default' WHERE tenant_id = '';
ALTER TABLE episodic_memories ALTER COLUMN tenant_id SET DEFAULT 'default';
CREATE INDEX IF NOT EXISTS idx_episodic_tenant_imp
  ON episodic_memories (tenant_id, importance DESC);
CREATE INDEX IF NOT EXISTS idx_episodic_tenant_created
  ON episodic_memories (tenant_id, created_at DESC);
-- procedural_memories：多租户已确认（ADR-0006），必须同样补列；
-- 技能源于租户执行轨迹，跨租户共享即泄漏 → 定级「租户内共享、跨租户隔离」
```

**代码**（`memory_pg.py` + `episodic_memory.py` 协议）：
- `EpisodicStore` 协议方法增加 `tenant_id` 参数（save / recall / get / list_by_execution / list_all / delete）。
- `PgEpisodicStore` 所有 SQL 增加 `WHERE tenant_id = %s`；**不做 legacy `default` 桶过渡读**（沿用 `typed.py` 已确立的安全语义：归属不明的记忆宁可暂不可见，也不跨租户可见）。
- 调用方 `memory_sink.py` / `memory_types.py` 的 `MemoryRecallRequest.tenant_id` 透传到底（该字段已存在，当前未下传）。

**验收**：`tests/ha/test_tenant_isolation_real_pg.py` 扩展 episodic 用例——tenantA 写入、tenantB 召回为空。

### T2（P0）Episodic 检索升级为向量（保留降级）

```sql
ALTER TABLE episodic_memories ADD COLUMN IF NOT EXISTS summary_embedding vector(1536);
CREATE INDEX IF NOT EXISTS idx_episodic_emb ON episodic_memories USING hnsw (summary_embedding vector_cosine_ops);
```

- `PgEpisodicStore.recall` 改为 `ORDER BY summary_embedding <=> %s`；**embedding 由宿主层传入**（遵守 ADR-0004「内核不下沉 embedder」）。
- 无 embedding（列为 NULL）时降级为 ILIKE + `three_factor_score` 排序。
- 排序统一走 `memory_recall.three_factor_score(relevance, importance, created_at)`，消除 G8 双轨。

### T3（P1）零成本去重

```sql
ALTER TABLE episodic_memories ADD COLUMN IF NOT EXISTS content_hash TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS uq_episodic_hash ON episodic_memories (tenant_id, content_hash) WHERE content_hash IS NOT NULL;
```

- `content_hash = md5(task_summary + "|" + sorted(key_steps))`（对齐 Mem0 的 md5 hash 去重，**零 LLM 成本**）。
- `save` 改 `ON CONFLICT (tenant_id, content_hash) DO UPDATE SET importance = GREATEST(episodic_memories.importance, EXCLUDED.importance), updated_at = ...`。

### T4（P1）provenance 字段

```sql
ALTER TABLE episodic_memories
  ADD COLUMN IF NOT EXISTS source_execution_id TEXT,
  ADD COLUMN IF NOT EXISTS injected_by TEXT DEFAULT 'system',   -- user|model|tool|system
  ADD COLUMN IF NOT EXISTS confidence REAL DEFAULT 1.0;
```

- 语义记忆（`memories`）同步补三列；`typed.remember_typed` 增加可选形参（默认不破坏现有调用）。
- 检索排序对 `injected_by='tool'` 降权（对齐投毒防护最小实践）。

### T5（P1）审计日志表 + 真批删

```sql
CREATE TABLE IF NOT EXISTS memory_change_log (
    id BIGSERIAL PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    memory_kind TEXT NOT NULL,          -- semantic|episodic|procedural
    memory_id TEXT NOT NULL,
    event TEXT NOT NULL,                -- ADD|UPDATE|DELETE|EXPIRE|MERGE
    old_value JSONB,
    new_value JSONB,
    actor_id TEXT,
    reason TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_mcl_tenant ON memory_change_log (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_mcl_mem ON memory_change_log (memory_kind, memory_id);
```

（字段设计对齐 Mem0 `history` 表十列，并补其缺失的 `tenant_id`。）

- 所有写入/删除路径记一条；`forget` / GDPR 删除时写**一条 bulk 审计**而非逐条。
- **真批删替代循环**（G6）：`DELETE FROM episodic_memories WHERE tenant_id=%s AND created_at < %s`；容量淘汰改 `ORDER BY importance ASC LIMIT %s` 的 SQL 删除。

### T6（P1）ProceduralSink 增量化（G7）

- `list_all()` → `list_since(tenant_id, since_ts)`（新增 store 方法，SQL `WHERE tenant_id=%s AND created_at > %s`）。
- 维护 `last_extract_at` 水位（可存 `metadata` 表或内存 + 启动重建）。

### T7（P2）生产指标（G9）

新增 `agent_runtime/memory_metrics.py` 或在 `eval/` 扩展，采集四类（研究报告结论：无现成基准，必须自建）：
1. 记忆命中率（召回结果被 context 采纳比例）
2. 事实一致性（矛盾出现后是否给出当前真相）
3. 用户纠错率
4. 记忆贡献度（含/不含记忆的 A/B）

### T8（P1）语义记忆契约收口（G10）

目标：让「用户事实」永远只有一个真相源，把 `semantic_memory.py` 注释里已声明、但代码未接的虚线接通。

- 在 `agent-runtime` 新增 `CoreTypedUserSemanticStore(UserSemanticStore)`：**薄适配器**，内部调用 `agent_core.memory.typed` 的 `recall_typed` / `remember_typed`，**不自建表、不自建评分**。
- 依赖方向校验：此举在既有红线 `application → agent-runtime → agent-core` 之内（runtime 已声明依赖 `agent-core`），**不违反**内核零依赖铁律。
- 驱动对齐：遵守 ADR-0004 决策 4（pg 模式 typed 路径**接收宿主 psycopg 池**），适配器不新建池。
- **若评估后决定不接**：则在 `semantic_memory.py` 显式标注「本接口暂无生产实现，禁止自行实现后端，用户事实一律走 `agent_core.memory.typed`」，以注释形式封死重复实现路径。

**验收**：`UserSemanticStore` 至少有 1 个非 mock 实现且落 `memories` 表；或已加禁止性注释。

---

## 4. 明确不做（保留现有优势）

- ❌ 不替换四类分类体系 —— 它比"全类召回再排序"更精细。
- ❌ 不动 `ContextSelector` 与 `SkillUsageTracker` —— 前者防污染，后者是程序性记忆的核心价值。
- ❌ 不合并 `SharedSemantic` 与 `UserSemantic` —— 两层分离即 RAG/Memory 边界的正确落地。
- ❌ **不合并 `agent-core/memory` 与 `agent-runtime/memory_*` 两条链路** —— 二者语义不同（用户画像 vs 执行经验），合并会毁掉程序性记忆沉淀管道；收口只做在「用户事实」这一个交集上（T8）。
- ❌ 不引入 Mem0/Zep 等外部方案替代 —— 本仓库能力已覆盖，且 OSS 方案无租户维度（Mem0 `app_id` 属 Platform 专有）。
- ❌ 不改用 LangGraph `AsyncPostgresStore` —— 现有 PG 池 + ADR-0003「单一连接源」约束优先。

---

## 5. 验收清单

| 任务 | 验收用例 |
|------|---------|
| T0 | `agent_core/memory/execution.py` 仅 import stdlib（CI 断言）；`isinstance(PgEpisodicStore(pool), EpisodicStoreProtocol)` 通过；`CapabilityReport` 如实报告 `supports_episodic`；开关 false 时行为零变更（runtime 62 条 + federation 44 条全绿） |
| T1 | tenantA 写 Episode，tenantB `recall` 返回空；`list_all` 按 tenant 过滤；回归 `tests/ha/test_tenant_isolation_real_pg.py` |
| T2 | 语义相近但措辞不同的 query 能召回（`ILIKE` 召回不到、`<=>` 能召回的对照用例）；无 embedding 行走降级不报错 |
| T3 | 相同 task_summary + key_steps 连续 save 两次 → 只有一行，importance 取较大值 |
| T4 | 写入带 `injected_by='tool'` 的记忆 → 排序得分低于同等内容 `injected_by='user'` |
| T5 | 删除 1000 条 → `memory_change_log` 产生 1 条 bulk 审计；删除耗时较逐条下降一个数量级 |
| T6 | 记忆量 10k 时，`ProceduralSink` 单次触发扫描行数 ≤ 增量窗口行数 |
| T7 | 四类指标可输出，且在 eval 集上可复现 |
| T8 | `UserSemanticStore` 有非 mock 实现且落 `memories` 表（或已加禁止自实现注释）；写入一次用户事实，`agent-core` 与 `agent-runtime` 两侧读到同一条 |

---

## 6. 风险与依赖

1. **T1/T2 是破坏性迁移**：存量 `episodic_memories` 无 tenant，统一归入 `default`。需确认线上是否存在真实多租户数据；若有，需先做归属判定再迁移（**不要**让真实租户共享 `default` 桶）。
2. **向量维度需与宿主 embedder 对齐**（当前 `memories` 表已用 pgvector，沿用同一 embedder 与 dims）。
3. **T2 依赖宿主层 embedder 注入**，需遵守 ADR-0004（内核不下沉 embedder）。
4. 本计划基于 2026-09-27 代码状态；实施前请复核 `migrations/` 最新版本号与 `CHANGELOG`。

---

## 7. 与外部研究成果的映射

| 外部结论 | 本计划对应项 |
|---------|-------------|
| 记忆层上线即成治理对象，需 provenance + 审计 + 真删 | T4 / T5 |
| 去重应零 LLM 成本（Mem0 md5 hash 模式） | T3 |
| 冲突消解可选「读时排序」（ADD-only） | 本仓库 `memories` 已是覆盖式写入，暂不动；T5 审计补齐回滚后可演进 |
| 公开基准不可信，必须自建生产指标 | T7 |
| 多租户隔离是硬边界，须服务端强制 | T1（当前已部分具备，需补齐 episodic/procedural） |
