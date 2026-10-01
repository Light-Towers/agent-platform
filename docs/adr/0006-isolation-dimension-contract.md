# ADR-0006: 隔离维度契约（tenant 为边界 / workspace 为归属）

- 状态：**采纳（Accepted，2026-09-27 用户拍板三项决策，见 §8 修订记录）**
- 日期：2026-09-27
- 关联：ADR-0003、ADR-0004、ADR-0005、`ARCHITECTURE.md` §5、`docs/tech-debt/tech-debt-hardcoded-logic.md` TD-13、`docs/architecture/architecture-improvement-plan.md` 优化 G
- 触发问题：**「所有数据都由 租户+用户+workspace 隔离，但 workspace 是最细粒度，是否直接依据 workspace 就行？」**
- 执行计划：`docs/plans/plan-isolation-hardening-2026-09-27.md`

---

## 1. 结论先行

**不能。** `workspace_id` 应作为**归属（ownership）维度**保留并继续使用，但**不可作为唯一隔离维度**。

原因不是"预留扩展性"这类模糊理由，而是三条可验证的事实：

1. `workspace_id` 由**客户端传入**，`tenant_id` 由**服务端断言**——二者可信性不同，不能互换；
2. **存在不属于任何 workspace 的数据**（租户级治理数据、平台级技能资产）；
3. 已有表**仅用 workspace 隔离**（`chunks` / `sql_ddl` / `sql_docs` / `sql_examples`），它们**恰恰是当前租户隔离最薄弱处**——即"只用 workspace"不是假设，是现状，且已暴露风险。

---

## 2. 现状技术事实（2026-09-27 实测）

### 2.1 隔离维度在库表中是**混用**的，从未统一

| 表 | 隔离列 | 证据 |
|---|---|---|
| `chunks`（RAG 文档切片） | **仅 `workspace_id`**（v2 追加，默认 `'default'`） | `001_baseline.up.sql:7-16`；`002_workspace.up.sql:4-5` |
| `sql_ddl` / `sql_docs` / `sql_examples` | **仅 `workspace_id`**（默认 `''`） | `001_baseline.up.sql:41-68` |
| `memories` | `tenant_id` + `user_id` | `001_baseline.up.sql:18-20`；`004` / `005` 迁移 |
| `semantic_cache` | 仅 `tenant_id` | `001_baseline.up.sql:36-39` |
| `execution_queue` / `rate_limit_buckets` / `cost_records` | 仅 `tenant_id` | `001_baseline.up.sql:223-272` |
| `admission_queue` | 仅 `user_id` | `001_baseline.up.sql:72-83` |
| `episodic_memories` / `procedural_memories` | **无隔离列** | `001_baseline.up.sql`（见 ADR-0005 / plan G1） |

### 2.2 两个维度的**可信性不同**（决定性事实）

| 维度 | 来源 | 证据 |
|---|---|---|
| `tenant_id` | **服务端**：请求链路 ContextVar | `agent_federation/agent/memory/main_agent_memory.py:7`「`tenant_id` 取自请求链路 ContextVar」 |
| `workspace_id` | **客户端**：请求字段，默认 `"default"` | `agent_server/api/import_router.py:20`；`agent_server/agent/state.py:35` |

且优化 G 的决策明确：workspace_id「由**客户端显式传**……**仅 app 内部隔离**，不写 `shared_schemas`（联邦网关无感）」——`architecture-improvement-plan.md:118`。

### 2.3 `workspace_id` 无归属校验

全仓 grep 无 `CREATE TABLE workspaces`（亦无等价归属映射表）。→ `workspace_id` 是一个**扁平字符串**，没有任何机制能证明「该 workspace 属于哪个租户」。

### 2.4 `user_id` 位已被 `workspace_id` 占用（TD-13）

`tech-debt-hardcoded-logic.md:126-133`：内核 `recall_typed` / `remember_fact` 形参与列名均为 `user_id`，而 federation 调用处传的是 `workspace_id`，「隔离主键正确传递（`workspace_id` 即落于内核 `user_id` 形参位）」。

**实质后果**：`memories` 表事实上是 **workspace 级**而非用户级——「跨 workspace 的同一用户画像」这一层**不存在**。

另注：`004_memory_tenant_id.up.sql:2` 记载 v4 补列时「当前隔离靠 `user_id` 全局唯一」——即租户维度本就是后补的 defense-in-depth。

### 2.5 存在不属于任何 workspace 的数据

- **租户级治理数据**：`execution_queue`、`rate_limit_buckets`（主键含 `tenant_id, dimension`）、`cost_records`。配额 / 限流 / 成本只认租户，workspace 装不下。
- **平台级资产**：`procedural_memories` 是**持久化的 Skill 定义**（`procedural_memory.py:1-22`：「已经掌握的做事方法」「从 Episodic Memory 挖掘高频成功模式」）。技能天然跨 workspace 复用；按 workspace 隔离 = 每个空间重学一遍，**摧毁程序性记忆的价值**。
- **共享知识库**：`SharedSemanticStore` 按 `knowledge_id / tenant_id` 隔离（`semantic_memory.py` 模块 docstring），不是 workspace。

---

## 3. 决策

### D1（硬规则）`tenant_id` 是唯一**安全边界**

- 每一行业务数据**必须有** `tenant_id`；
- 每一个查询**必须带** `tenant_id` 谓词；
- 值由**服务端**从请求上下文（ContextVar / token）解析，**客户端不可指定**；
- 沿用 `_tenant_gate.resolve_tenant` 已确立的严格语义：归属不明的行**宁可暂不可见，也不跨租户可见**（禁止 legacy `default` 桶过渡读）。

### D2（硬规则）`workspace_id` / `user_id` / `knowledge_id` 是**归属维度**

- 三者**彼此正交**，按数据语义选择其一或其组合，**不是层级包含关系**；
- 归属维度由客户端传入，**可空**；
- **不可单独承担隔离职责**（违反即视为缺陷）。

### D3 数据分类 → 维度模板

| 类别 | 判定 | 维度模板 | 例 |
|------|------|---------|-----|
| **租户级**（治理/计量） | 与具体工作空间无关 | `tenant_id` 必填，无归属维 | `execution_queue`、`rate_limit_buckets`、`cost_records` |
| **归属级**（业务数据） | 属于某空间/某人/某库 | `tenant_id` 必填 + 归属维 | `memories`、`chunks`、`sql_*`、`episodic_memories` |
| **租户内共享**（资产） | 租户内跨 workspace 复用 | `tenant_id` 必填，**无 workspace 谓词**（但**禁止跨租户**） | `procedural_memories`、`SharedSemanticStore` 知识库 |
| **平台级**（真全局） | 跨租户复用 | 默认**不存在**；确需引入时须经评审 + 内容脱敏审查 | （当前无此类数据） |

> **修订（2026-09-27，多租户确认后）**：初版曾将 `procedural_memories` 列为"平台级跨租户复用"，**已推翻**。技能由 `ProceduralExtractor` 从租户的执行轨迹（episodic）中挖掘而来，**内容携带租户业务信息**——多租户下跨租户共享即数据泄漏；且记忆投毒（MINJA / OWASP ASI06）的攻击面会从单租户放大到全平台。故技能与共享知识一律**租户内共享、跨租户隔离**；确需跨租户的公共知识只能走显式发布机制（knowledge-service 的 `scope_type` 元数据已有此雏形），且须内容脱敏审查。

### D4 `workspace_id` 必须做归属校验（补当前最大缺口）

二选一，评审拍板：

- **方案 A（推荐）**：建 `workspaces(id, tenant_id, ...)` 归属表，写入/读取前校验 `workspace.tenant_id == ctx.tenant_id`；
- **方案 B（轻量）**：服务端将 `workspace_id` 规范化为 `f"{tenant_id}:{raw}"` 后落库，使跨租户撞名在物理上不可能。

> 未做此项前，"客户端传任意 workspace_id" 在缺少租户谓词的表上即为越权通道。

### D5 处置 TD-13 的语义重载

- **不重命名**内核形参与列（TD-13 已论证：破坏 schema 与多包兼容）；
- 改为在内核 `typed.py` / `store.py` docstring 明确：**该形参位是「归属键（scope key）」，调用方须自行决定承载 `workspace_id` 还是 `user_id`，且同一部署内必须一致**；
- 若未来需要真正的「跨 workspace 用户画像」，应**新增显式维度**，而非复用该位。

---

## 4. 由此发现并需登记的问题

| # | 级别 | 问题 | 位置 |
|---|------|------|------|
| **W1** | **P0（活跃）** | `chunks` / `sql_ddl` / `sql_docs` / `sql_examples` 四表**无 `tenant_id`**，仅靠客户端传入的 `workspace_id` 隔离 → **多租户部署已确认（2026-09-27），跨租户文档与 SQL 语料可见即为现实风险** | `001_baseline.up.sql:7-16,41-68`；`002_workspace.up.sql` |
| **W2** | **P0（活跃）** | `workspace_id` 无归属校验（无 `workspaces` 表），无法证明其归属 → 跨租户撞名即可越权 | 全仓无归属表 |
| W3 | **P0（用户拍板必须存在）** | 跨 workspace 用户画像缺失：`memories.user_id` 位被 `workspace_id` 占用（TD-13，且 `agent_server/agent/graph.py:121` 与 federation 两侧均传 workspace_id），用户维度事实上不存在 | `tech-debt-hardcoded-logic.md:126-133` |
| W4 | P1 | knowledge-service 有 `tenant_id` 字段但**默认空、可选**（`import_router.py:148` 默认 `""`；`mongo_history_utils.py:65` 仅在非空时追加过滤）→ 不传即不过滤，须升级为服务端强制断言 | `knowledge_service/api/import_router.py:148` |
| W5 | P2 | 隔离维度无统一约定，七类表四种组合，新增表时无章可循 | 本 ADR §2.1 |

> **部署形态已确认（2026-09-27 用户拍板）：本系统为多租户设计。** 原"多租户化阻断项"的边界条件不再适用，W1–W4 全部按活跃问题定级。

---

## 5. 替代方案

1. **统一只用 `workspace_id`**（即本次提问的方案，否决）：客户端可传、无归属校验、且租户级与平台级数据无法表达；`chunks` 的现状正是其后果样本。
2. **统一只用 `tenant_id`**（否决）：无法区分同一租户内的不同工作空间与用户，RAG 文档与会话记忆会串味（优化 G 正是为此引入 workspace）。
3. **维持现状不做约定**（否决）：新增表继续随意选维度，W4 会持续放大；且 W1/W2 无修复依据。
4. **把 `workspace_id` 提升为服务端派发的可信维度**（可选，作为 D4 方案 C）：由服务端签发并签名 workspace 令牌。成本高于 A/B，本 ADR 不推荐，仅登记。

---

## 6. 后果

**正向**

- 七类表的隔离语义有统一判据，新增表按 §D3 模板选维即可；
- `tenant_id` 成为可审计的强制谓词，跨租户泄漏从"靠人记得写 WHERE"变为"契约强制"；
- 程序性记忆与共享知识的平台级定位得到显式承认，不再被误要求按 workspace 隔离；
- TD-13 从"命名噪音"升格为"已记录的设计约束"，避免后续维护者误判。

**负向 / 风险**

- W1 涉及四张**存量表**加列 + 回填，是数据迁移，成本高于普通加固；
- D4 引入归属校验会增加一次查询/一次规范化的开销（可缓存，影响可忽略）；
- 单租户部署下这些改动短期收益不显性，需按"多租户化前置项"立项而非按"修 bug"立项。

---

## 7. 验证

- **契约测试**：新增 `tests/governance/test_isolation_dimension_contract.py`——扫描 migrations 中所有 `CREATE TABLE`，断言每张业务表含 `tenant_id`（平台级表须在白名单中显式登记）；
- **越权测试**：tenantA 携带 workspace="X" 写入，tenantB 携带同名 workspace="X" 读取 → 返回空（D4 落地后）；
- **回归**：`tests/ha/test_tenant_isolation_real_pg.py` 全绿。

---

## 8. 修订记录（2026-09-27 用户拍板，待决策项收口）

用户三项拍板（原文）：
> 1. workspaces、知识库 是不是得有个 tenant 映射？
> 2. 「跨 workspace 用户画像」这一层需要存在，要不 agent 记忆设计就没用了。
> 3. 这个系统使用多租户设计

| 原待决策项 | 拍板结果 |
|-----------|---------|
| 1. D4 归属校验方案 | **方案 A 采纳**：新建 `workspaces(id, tenant_id, ...)` 归属表；知识库同理（knowledge-service 已有 `tenant_id` 字段但须强制化，见 W4） |
| 2. W1 立项 | **多租户已确认 → 活跃 P0 立即修**（原"先确认部署形态"前置条件已解除） |
| 3. procedural / 知识库定级 | **修正为「租户内共享、跨租户隔离」**（原倾向"平台级"在多租户下不成立：技能源于租户执行轨迹，跨租户共享即泄漏 + 投毒面放大；见 D3 修订） |
| 4. workspace 令牌（方案 C） | 不需要，方案 A 已足够 |
| **新增（用户拍板 2）** | **跨 workspace 用户画像必须存在** → `memories` 双 scope 设计（workspace 级 + user 级），`user_id` 恢复真实用户语义，执行见 plan T13 |

执行任务分解见 `docs/plans/plan-isolation-hardening-2026-09-27.md`（T9–T13）。

---

## 9. 与既有文档的关系

- 本 ADR **不推翻**优化 G 引入 `workspace_id` 的决策——它解决了真实问题（RAG 与长期记忆的统一归属）；本 ADR 只限定**它不能单独承担隔离**。
- 本 ADR 是 `ARCHITECTURE.md` §5「记忆层契约缺位」之外的**第二条**隔离相关技术债，二者独立。
- 执行细节（迁移 SQL、验收用例）待评审通过后单独立项，本 ADR 不重复。
