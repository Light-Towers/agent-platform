# 隔离域加固实施计划

| 项 | 内容 |
|----|------|
| 日期 | 2026-09-27 |
| 状态 | **已实施（2026-09-27 落地，见 §7 实施记录）**：T9/T10/T11/T12/T13 代码 + 测试已接线；双 scope 写入经 `MEMORY_DUAL_SCOPE` 渐进开关（默认关，行为零变更） |
| 范围 | `agent_server` RAG/SQL 语料表、knowledge-service、`memories` 表、workspace 归属 |
| 上位决策 | `docs/adr/0006-isolation-dimension-contract.md`（**已采纳**：tenant 为边界 / workspace 为归属；多租户已确认） |
| 与记忆计划的关系 | 本计划管**隔离域**（谁可见）；`plan-memory-hardening-2026-09-27.md` 管**记忆质量域**（好不好用）。T1（episodic/procedural 补 tenant）归后者，本计划不重复 |
| 结论 | **多租户已确认（2026-09-27）**，W1–W4 全部按活跃问题定级，P0 三项先行 |

---

## 1. 结论摘要

ADR-0006 已采纳并拍板三项：

1. **workspaces 与知识库都需要 tenant 映射**（方案 A：归属表 + 校验）；
2. **跨 workspace 用户画像必须存在**（记忆设计的价值前提）；
3. **系统为多租户设计** → 四表缺 tenant_id 不再是"潜在风险"，是**现实风险**。

随之而来的一个重要修正：`procedural_memories` 从初版"平台级跨租户复用"**改判为「租户内共享、跨租户隔离」**——技能由执行轨迹挖掘而来，携带租户业务信息，多租户下跨租户共享即数据泄漏，且记忆投毒攻击面会放大到全平台。

---

## 2. 实施任务

### T9（P0）`chunks` / `sql_*` 四表补 `tenant_id`（W1）

```sql
-- 006_tenant_on_corpus.up.sql
ALTER TABLE chunks        ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default';
ALTER TABLE sql_ddl       ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default';
ALTER TABLE sql_docs      ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default';
ALTER TABLE sql_examples  ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default';
CREATE INDEX IF NOT EXISTS idx_chunks_tenant       ON chunks        (tenant_id, workspace_id);
CREATE INDEX IF NOT EXISTS idx_sql_ddl_tenant      ON sql_ddl       (tenant_id, workspace_id);
CREATE INDEX IF NOT EXISTS idx_sql_docs_tenant     ON sql_docs      (tenant_id, workspace_id);
CREATE INDEX IF NOT EXISTS idx_sql_examples_tenant ON sql_examples  (tenant_id, workspace_id);
```

- **代码**：`import_router.py` / `sql_router.py` 的写入与查询全部增加 `tenant_id` 谓词；值取服务端上下文（同 `_tenant_gate.resolve_tenant` 语义），**不收客户端表单值**（`import_router.py:20` 的 `workspace_id: str = "default"` 参数保留为归属维）。
- **存量回填**：确认存量数据归属（当前唯一租户则归 `'default'`）；若有真实多租户存量，先做归属判定，**不要**让真实租户混入 `'default'` 桶。

### T10（P0）`workspaces` 归属表 + 校验（W2，D4 方案 A）

```sql
-- 007_workspaces.up.sql
CREATE TABLE IF NOT EXISTS workspaces (
    id          TEXT PRIMARY KEY,
    tenant_id   TEXT NOT NULL,
    name        TEXT NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, name)
);
```

- **写入前校验**：创建/引用 workspace 时断言 `workspace.tenant_id == ctx.tenant_id`，不存在则按调用方租户创建（首次引用自动注册），**跨租户同名不共享**。
- **查询侧**：凡按 `workspace_id` 过滤的 SQL，一律与 `tenant_id` 成对出现（契约测试锁定，见 §4）。
- knowledge-service 的知识条目归属：`knowledge_id` 的租户归属沿用其现有 `tenant_id` 元数据（`import_router.py:148` 已有字段），无需新表，只需 T12 强制化。

### T11（P0/P1）knowledge-service `tenant_id` 强制化（W4）

- `import_router.py:148` 的 `tenant_id: str = Form("")` 与 `query_router.py` 各端点：**空值拒绝**（422）或**由服务端上下文注入**（二选一，倾向后者，与 ADR-0006 D1 一致）。
- `mongo_history_utils.py:65` 的 `if tenant_id else None` 回退逻辑删除——非多租户场景也应显式传租户（开发态可用 `default`）。
- 关联：其 ACL 设计（INV-8 前置）与本项对齐，不重复建设。

### T12（P1）契约测试：隔离维度白名单（W5）

- 新增 `tests/governance/test_isolation_dimension_contract.py`：扫描 migrations 全部 `CREATE TABLE`，断言业务表含 `tenant_id`（平台级/系统表走显式白名单，如 `admission_queue` 等待另行判定）。
- 断言凡 SQL 含 `workspace_id = ` 谓词处，同一查询必含 `tenant_id = ` 谓词（静态扫描近似即可，标注已知误报源）。

### T13（P0）`memories` 双 scope 用户画像（W3，用户拍板"画像层必须存在"）

**设计**：同一张表承载两种 scope，`user_id` 恢复真实用户语义。

```sql
-- 008_memories_dual_scope.up.sql
ALTER TABLE memories ADD COLUMN IF NOT EXISTS workspace_id TEXT;
ALTER TABLE memories ADD COLUMN IF NOT EXISTS scope TEXT NOT NULL DEFAULT 'workspace';
-- 数据迁移前置断言：存量 user_id 列位实装的是 workspace_id（TD-13；两侧调用均证实：
-- agent_federation/agent/memory/main_agent_memory.py 与 agent_server/agent/graph.py:121）
UPDATE memories SET workspace_id = user_id WHERE workspace_id IS NULL;
UPDATE memories SET user_id = 'default' WHERE scope = 'workspace';
CREATE INDEX IF NOT EXISTS idx_memories_scope ON memories (tenant_id, scope, workspace_id);
CREATE INDEX IF NOT EXISTS idx_memories_user  ON memories (tenant_id, scope, user_id);
```

- **召回语义**：
  - workspace 记忆：`WHERE tenant_id=%s AND scope='workspace' AND workspace_id=%s`
  - user 画像：`WHERE tenant_id=%s AND scope='user' AND user_id=%s`（跨该用户所有 workspace）
  - 合并召回：两路各取 top-k 后按现有 `type_weight × importance × 衰减` 融合排序（不改评分公式）。
- **写入路由**：首期默认 `scope='workspace'`（行为零变更）；user 画像条目由 LLM 抽取阶段标记（个人偏好/身份类事实 → `scope='user'`），落点在 `longterm.extract_memory_facts` 的提示词加一个判定位，属增量改动。
- **TD-13 收口**：内核形参与列名**不重命名**（沿用 TD-13 结论），但 `typed.py` docstring 增补：该位即"归属键"，双 scope 后 `user_id` 位恢复用户语义、`workspace_id` 位承载空间归属，二者由 `scope` 列区分。
- **与记忆计划的衔接**：T4（provenance）的 `injected_by` / `confidence` 列对本表同样生效，互不冲突。

---

## 3. 明确不做

- ❌ 不做 workspace 令牌/服务端签发（D4 方案 C）——方案 A 已足够。
- ❌ 不把 `procedural_memories` 做成跨租户共享——多租户下即数据泄漏（ADR-0006 D3 修订）。
- ❌ 不重命名内核 `user_id` 形参/列——TD-13 结论不变，用 `scope` 列消歧。
- ❌ 不在本计划内动 `episodic_memories`/`procedural_memories`——归 `plan-memory-hardening` T1。

---

## 4. 验收清单

| 任务 | 验收用例 |
|------|---------|
| T9 | tenantA 导入文档后，tenantB `query` 召回不到该文档任何 chunk；sql_examples 同理 |
| T10 | tenantB 携带与 tenantA 同名 `workspace_id` 读写 → 各自隔离，`workspaces` 表中两条记录分属两租户 |
| T11 | 不带 `tenant_id` 调 knowledge-service 导入/查询 → 显式 422（或服务端注入 default 并审计），不再静默全量 |
| T12 | 人为建一张无 `tenant_id` 的业务表 → 契约测试失败 |
| T13 | 同一用户在 workspaceA 写"偏好上海"，在 workspaceB 提问 → user 画像条目被召回；workspaceA 的项目 Q/A 不串入 workspaceB |
| 回归 | `tests/ha/test_tenant_isolation_real_pg.py`、`tests/governance/` 全绿 |

---

## 5. 风险与依赖

1. **T13 迁移前置断言**：`UPDATE ... SET workspace_id = user_id` 基于"存量 user_id 位实装 workspace_id"的实测结论（TD-13 + 两侧调用点）。执行前须在目标库复核：`SELECT DISTINCT memory_type, COUNT(*) FROM memories GROUP BY 1` 与抽样比对调用方日志，确认无真实 user_id 混入；若有，先做归属判定再迁移。
2. **T9 存量回填**：与 T13 同理，先确认存量归属，禁止把真实多租户数据混入 `'default'`。
3. **T11 可能破坏现有调用方**：knowledge-service 的现有客户端（agent_federation 的 `zhiku_tools` 等）若未传 tenant_id，强制化后会 422——上线前排查全部调用点并补传（服务端注入优先，可规避）。
4. **迁移顺序**：T9/T10/T13 各自独立可并行；T12 依赖 T9/T10 落地后才有意义。
5. 本计划基于 2026-09-27 代码状态；实施前复核 `migrations/` 最新版本号（当前 005）。

---

## 6. 与外部研究成果的映射

| 外部结论（AI Agent Memory 研究报告 2026-09-26） | 本计划对应项 |
|---------|-------------|
| Mem0 OSS 无租户维度（`app_id` 属 Platform 专有）→ 自研必须自带租户 | T9–T13 全部以 `tenant_id` 为强制边界 |
| 记忆投毒（MINJA / OWASP ASI06）攻击面随共享范围放大 | procedural 改判租户内共享（§1 修正） |
| GDPR 可证明删除按主体（user）执行 | T13 恢复 user 维度是 GDPR 删除的前置条件（无 user 维度则无法按主体删除） |

---

## 7. 实施记录（2026-09-27，分支 `feat/isolation-hardening`）

> 编号按 `migrations/` 当前最新（005）顺延为 006/007/008，与并行任务无冲突（已 `git pull` 核对）。迁移 up/down 成对、`IF [NOT] EXISTS` 幂等、SQL 注释英文、代码 LF 行尾。agent-core 零宿主依赖不变（`typed.py` 仅 stdlib；workspace 归属模块落 `agent-runtime`）。

| 任务 | 文件 : 关键位置 | 说明 |
|------|----------------|------|
| T9 迁移 | `packages/agent-runtime/agent_runtime/migrations/006_tenant_corpus.{up,down}.sql` | chunks/sql_ddl/sql_docs/sql_examples 补 `tenant_id`（DEFAULT 'default'）+ `(tenant_id, workspace_id)` 复合索引 |
| T9 读写 | `applications/agent_server/rag/store.py:58`(`add_document`)/`:153`(`retrieve_chunks`) | 全 SQL 成对带 tenant 谓词；tenant 漏传经 `resolve_tenant` fail-fast |
| T9 读写 | `applications/agent_server/sql/schema_store.py:54`(`fetch_context`) | 消除「空 workspace = 全库召回」旁路，tenant 谓词必经 |
| T9 接线 | `api/import_router.py` `api/sql_router.py` `subagents/{rag,sql_agent}.py` `sql/pipeline.py` `agent/graph.py` | 写入口收服务端租户（不收表单）；graph 节点透传 `tenant_id` |
| T10 | `packages/agent-runtime/agent_runtime/workspace_registry.py`（新）+ `007_workspaces.{up,down}.sql` + `009_workspaces_backfill.{up,down}.sql` | `workspaces(tenant_id, id)` 复合 PK 命名空间化；`resolve_workspace(pool, tenant_id, workspace_id) -> bool`（首次引用自动注册，幂等，入参非法 fail-fast，表未应用降级 True）·`register_workspace`·`assert_workspace_access`（可选严格越权门，未接线默认读路径）·`server_tenant_id`。接线：`import_router`/`sql_router`/`query_router` 使用 workspace_id 前均调 `resolve_workspace`（读路径 best-effort，失败不阻断）。`009` 为现网 (tenant='default', 已用 workspace_id) 幂等补注册 |
| T11 | `applications/knowledge-service/knowledge_service/utils/tenant_utils.py:22`（新）+ `api/{import,query}_router.py` `clients/mongo_history_utils.py` `core/config.py` | 空 tenant → 服务端注入 `KNOWLEDGE_DEFAULT_TENANT_ID` + 审计；删除 Mongo「空→不过滤」回退 |
| T12 契约 | `tests/governance/test_isolation_dimension_contract.py`（新） | 迁移回放最终 schema 每张业务表含 `tenant_id`（系统/待判定表白名单登记理由）；AST 断言 `workspace_id =` 谓词必配 `tenant_id` |
| T13 | `packages/agent-core/agent_core/memory/typed.py:138`(`memory_dual_scope_enabled`)/`:197`(`remember_typed`)/`:259`(`recall_typed`)/`:360`(`consolidate`)/`:398`(`forget`)/`:442`(`_vector_search_user_profile`) + `008_memories_dual_scope.{up,down}.sql` | `MEMORY_DUAL_SCOPE` 渐进开关（默认关=零变更）；开关开时 workspace 行落 `workspace_id`+`scope` 新布局、user 画像落真实 `user_id`；召回双路按同一 `type_weight×importance×decay` 融合（不改评分公式）；读写双列兼容滚动升级窗口；`typed.py` docstring 收口 TD-13「归属键」语义（不重命名形参/列） |
| T13 接线 | `applications/agent_server/memory/{memory_backend,longterm}.py` `agent/graph.py` | `remember_fact`/`recall_typed` 增 `scope`/`user_id`/`profile_user_id`；`longterm` 抽取提示加 scope 判定位并路由 |
| 越权测试 | `tests/governance/test_corpus_tenant_isolation.py` `tests/governance/test_memories_dual_scope.py`（新）+ `tests/ha/test_tenant_isolation_real_pg.py`（追加 4 例）| fake 池行为级 + 真实 PG 行为级（dual-scope 向量召回 / workspaces 越权 / chunks + sql_* 语料租户谓词） |

**测试结果**（Windows 本机，HA 用例需 Linux CI 真实 PG）：
- `ruff check .` 全通过；`scripts/lint_architecture.py` + `scripts/check_doc_sync.py` 通过（agent-runtime 未反向 import 应用层，红线 1 保持）。
- 根套件 `pytest tests -m "not requires_pg"`：433 passed（唯一失败 `test_circuit_breaker_middleware_degrades` 经 `git stash` 复核为 v3 分支既有失败，与本任务无关）。
- `packages/agent-core` typed 18/18、`packages/agent-runtime` 574、`applications/agent_server/tests` 44、`applications/agent_federation/tests` 142、`applications/knowledge-service/tests` 230 passed（含集成 skip）——全绿。
- 治理新增：`test_isolation_dimension_contract.py`（4）、`test_corpus_tenant_isolation.py`（10）、`test_memories_dual_scope.py`（7）全绿。

**未做 / 边界**：`/query` 的 tenant 源仍走 `req.tenant_id`（改服务端断言属 shared-schemas 契约变更，按框架规则「需评估 JWT」另行决策，本任务不动）；`episodic/procedural` 隔离列归 `plan-memory-hardening` T1（本任务白名单登记）；corpus 存量回填真实多租户归属判定需运维在目标库执行前复核（§5.2）。

**渐进开启**：migration 006/007/008 全量应用后，翻 `MEMORY_DUAL_SCOPE=true` 启用 user 画像双 scope（读路径始终双列兼容，无需停机）；多租户部署须为 agent_server 配 `DEFAULT_TENANT_ID`、knowledge-service 配 `KNOWLEDGE_DEFAULT_TENANT_ID`。

---

## 8. T9 存量回填 pre-flight（部署门禁，2026-09-27 补充）

### 8.1 索引取舍：复合索引与旧单列索引**并存**（不替换）

`006_tenant_corpus` 新建 `(tenant_id, workspace_id)` 复合索引，**保留** baseline 已有的 `idx_*_workspace`（workspace_id 单列）。取舍：
- **不替换**：复合索引前导列是 `tenant_id`，无法服务任何「裸 `workspace_id =` （不带 tenant）」的查询；虽本任务已将**全部**读写改为 tenant+workspace 成对谓词（旧单列索引理论上变冷），但保留它对「未来偶发只按 workspace 的运维/回填 SQL」零风险，且与回滚（down 仅删复合列）对称；
- 代价：4 表各多一个索引的写入开销与存储——当前 corpus 量级可忽略；待 lint/契约测试（T12）长期锁定「无裸 workspace 谓词」后，可另开一个 cleanup 迁移删除旧单列索引（非本任务范围）。

### 8.2 回填前必验：行数统计 + 多租户归属判定（禁止混桶）

migration 006 的 `DEFAULT 'default'` 会把**存量行全量归入 `default` 桶**。若目标库已存真实多租户语料，直接归 default = 混桶（跨租户可见）。因此**应用 006 前必须在目标库跑以下 pre-flight**（本机 dev/CI 无真实 corpus 目标库，无法代跑，属部署时人工门禁）：

```sql
-- (a) 四表行数（记录到本表下方）
SELECT 'chunks' t, count(*) FROM chunks
UNION ALL SELECT 'sql_ddl', count(*) FROM sql_ddl
UNION ALL SELECT 'sql_docs', count(*) FROM sql_docs
UNION ALL SELECT 'sql_examples', count(*) FROM sql_examples;

-- (b) 枚举 workspace 分桶（四表各跑一遇，示例 chunks）；多租户下需逐个 workspace 确认归属租户
SELECT workspace_id, count(*) FROM chunks GROUP BY workspace_id ORDER BY 2 DESC;
```

判定规则：
- 若本部署**单租户**（或存量 workspace_id 均属同一租户）→ 归 `default` 安全，直接应用 006。
- 若**已混多个租户的存量数据**→ **停工上报**：先建立 workspace→tenant 归属映射（T10 `workspaces` 表），把非默认租户的行 UPDATE 到真实 `tenant_id` **后**再放开 DEFAULT；绝不允许真实租户数据混入 `default`。

**执行状态（2026-09-27）**：⚠️ 未执行——Windows 开发机无可达的目标 PG（`localhost:5433` 拒连，HA 用例按设计 skip）。本表待运维在有真实 corpus 的目标库执行后回填行数与归属结论；未确认前不得在带存量数据的生产库上应用 006。

### 8.3 workspace_id 唯一性模型（设计裁定，与用户对齐）

用户观点：`workspace_id`/`user_id` 应为全局唯一 ID（如雪花）。但**当前代码事实**：`workspace_id` 为客户端传入的扁平字符串，默认 `'default'`（`import_router`、`AgentState`、`QueryRequest`、`_RAG_SCHEMA` 均如此），多租户共享 `'default'`。因此：
- **现在**：workspaces 必须用复合 PK `(tenant_id, id)` 命名空间化，否则 `'default'` 跨租户撞 PK（不能取用户 DDL 的字面 `id TEXT PRIMARY KEY`）；这也才能满足 plan §4 T10 验收“同名 workspace_id → 两行分属两租户”；`UNIQUE(tenant_id, name)` 同理不适用（自动注册时 name 均为空，同租户第二个即违反）。
- **未来若真要全局唯一 id（雪花）**：属跨服务契约变更（ID 生成 + 退役共享 `'default'` 键 + 存量迁移，涉 agent_server/federation/shared-schemas），需另立 ADR/plan；届时在命名空间 PK 基础上加 `UNIQUE(id)` 即可，现有实现不回退不冲突。

### 8.4 T13 迁移前置断言：确认 `memories.user_id` 列位实装的是 workspace_id（TD-13）

`008_memories_dual_scope` 的 `UPDATE memories SET workspace_id = user_id ... ; UPDATE memories SET user_id = 'default' ...` **基于一个事实断言**：存量 `user_id` 列位实装的是 **workspace_id**（而非真实用户）。两侧调用点已核实：`agent_federation/agent/memory/main_agent_memory.py`（传 `thread_id` 作 workspace）与 `agent_server/agent/graph.py`（`state.workspace_id`）。

**应用 008 前必须在目标库抽样验证，确认无真实 user_id 混入**（否则会把真实用户误当 workspace 回填、并抹入 'default' 占位，造成错位）：

```sql
-- (a) user_id 列位取值基数：若 distinct(user_id) ≈ workspace 数量且含 'default'/thread_id 形态，
--     则为 workspace 语义（符合断言）；若出现大量自然用户标识且与 workspace 无关，则可能混入真实 user。
SELECT count(*) AS rows, count(DISTINCT user_id) AS distinct_user_id, count(DISTINCT tenant_id) AS tenants FROM memories;
-- (b) 抽样比对调用方日志：取若干 user_id 值核对其是否为已知 workspace/thread_id。
SELECT user_id, count(*) FROM memories GROUP BY user_id ORDER BY 2 DESC LIMIT 20;
```

判定：断言成立（全部为 workspace 语义）→ 可应用 008；**若发现有真实 user_id 混入 → 停工上报**，先做归属判定（区分哪些行是真实用户 vs workspace）再迁移，禁止盲目回填。

**执行状态（2026-09-27）**：⚠️ 未执行——本机无可达目标 PG。开关 `MEMORY_DUAL_SCOPE` 默认关时 008 的列变更可先行（不影响读写），UPDATE 回填仅在开关开启后才需严格正确；开关翻为 true 前必须在目标库跑上述抽样并记录结论。

---

## 9. T11 / T12 落地记录（2026-09-27，分支 `feat/isolation-hardening`）

### 9.1 T11：knowledge-service 租户强制化——选定“服务端上下文注入”（非 422）

**二选一决策：选“空值→服务端注入默认租户 + 审计”，不选“空值 422”。** 理由：
- knowledge-service 现有多个调用方（联邦 `tools/knowledge_tools.py`、agent_server 的 remote knowledge skill、离线 `scripts/import_exhibition_corpus.py`、`evaluation/run-all.py`）历史上不统一传 tenant_id；直接 422 会**同步打断全部未补传的存量链路**（上线风险高，且单租户/开发态本无租户概念）。
- 注入方案同样关闭了真正的漏洞：旧逻辑“空 tenant → 不加过滤 = 全库召回”（`mongo_history_utils` 的 `if tenant_id else None`、Milvus `build_retrieval_filter` 的 None→无表达式）才是跨租户可见根因；现在调用点总能拿到一个具体租户，下游 Mongo/Milvus 过滤恒非空 → 不再有“空→全量”旁路。
- 可审计：注入时 `logger.warning` 留痕，便于后续把“仍走 default 桶”的调用方逐个收敛。
- 代价（诚实标注）：多租户下未传 tenant 的调用方会被归入 `KNOWLEDGE_DEFAULT_TENANT_ID`（默认 `default`）而非报错——**安全但不等于正确**，故必须配合下面的调用方审计。

**改动**：新增 `knowledge_service/utils/tenant_utils.resolve_server_tenant()`；`/upload`、`/query`、`/api/v1/retrieve`、`/history`(GET/DELETE) 均过一道注入；删除 `mongo_history_utils` 的 `if tenant_id else None` 回退（写入恒带租户）；config 新增 `KNOWLEDGE_DEFAULT_TENANT_ID`。已在 `3dedbca`。

### 9.2 T11 上线前置：调用方审计结果（本轮补齐）

| 调用方 | 是否传 tenant | 处置 |
|--------|-------------|------|
| `agent_federation/tools/knowledge_tools.py::knowledge_retrieve`（`/api/v1/retrieve`） | 曾不传 | **已修**：从 `api.context.get_tenant_context()` 取请求链路租户传入 payload；非 server 环境降级不传（注入 default，不 422）。 |
| `agent_server/capabilities.py` 的 `knowledge_query`/`knowledge_retrieve` remote skill | 不传 | **注入安全**（不 422）；真实多租户 tenant 下传受限于 PlannerRuntime 身份恒 'default'（与 /query tenant 源同一既有边界），属后续跨服务决策，未在本任务动。 |
| `knowledge-service/scripts/import_exhibition_corpus.py` | 传（TENANT_ID 常量） | 无需改。 |
| `agent_federation/evaluation/run-all.py`（离线评测） | 不传 | 离线/dev harness，注入 default 可接受，不改。 |

审计结论：注入方案保证无调用方因强制化而 422；唯一具真实多租户正确性风险的联邦在线工具 `knowledge_retrieve` 已补传；agent_server remote knowledge skill 与 /query 租户源属同一待决边界（需真实服务端租户注入，另议）。

### 9.3 T12：隔离维度契约测试（已在 `3dedbca`）

`tests/governance/test_isolation_dimension_contract.py`：① 迁移回放最终 schema，断言每张业务表含 `tenant_id`（系统/待判定表显式白名单+理由，人为建无 tenant 业务表→红）；② AST 扫描 corpus/memory 模块 SQL 常量，断言 `workspace_id =` 谓词必与 `tenant_id` 成对出现（已知误报源：docstring/日志——通过要求同串含表名 token + SQL 动词过滤）。episodic/procedural 于本分支 commit 755cfc5 已补 tenant_id，白名单条理由保留作防御。
