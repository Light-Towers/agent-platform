# ADR-0005: 执行记忆协议下沉内核（记忆层统一契约）

- 状态：**采纳（Accepted，2026-09-27）**
- 日期：2026-09-27
- 关联：ADR-0003（双数据库驱动并存）、ADR-0004（类型化记忆下沉内核）、`ARCHITECTURE.md` §2.1 / §4 / §5、优化 E「双轨编排收敛」、`docs/plans/plan-memory-hardening-2026-09-27.md`
- 触发：审计「记忆层是否为双层设计 / 是否需维护两份代码」时的实测发现

---

## 1. 背景：一个被误诊的问题

审计起于一个提问：**记忆层两套实现，是不是同一能力维护了两份？**

实测结论是：**不是重复实现，而是内核契约缺位导致的必然自建。** 定性不同，处置方式完全不同——前者该删一份，后者该补契约。

### 1.1 现状关键技术事实（全部经 2026-09-27 实测）

| # | 事实 | 证据 |
|---|------|------|
| F1 | `memory` 的**法定归属是 `agent-core`**，其职责列表明列「memory（含 MemoryStore 统一门面）」 | `ARCHITECTURE.md:38` |
| F2 | `agent-runtime` 的职责列表为 Planner/Plan/Skill/SkillRegistry/Workflow/ExecutionContext/ExecutionRuntime/Sandbox，**不含 memory** | `ARCHITECTURE.md:39` |
| F3 | 内核已声明记忆实现收口纪律：「**所有后端实现现已收口到内核，各子包不得再各自为政重复实现——统一从此处 import**」 | `agent_core/memory/__init__.py:20-21` |
| F4 | 内核已有统一门面 `MemoryStore`，五动词「召回 / 沉淀 / 巩固 / 遗忘 / 能力探测」，`PgMemoryStore` 为权威后端，另有 `CapabilityReport` 供 `/health` 暴露 | `agent_core/memory/store.py:5-16` |
| F5 | **`MemoryStore` 五动词与 `CapabilityReport` 的能力位全部面向语义记忆**：`supports_consolidate` / `supports_forget` / `supports_tenant_isolation`，**无任何 episodic / procedural / working 支持位** | `agent_core/memory/store.py:37-60` |
| F6 | `agent-runtime` 的 8 个 `memory_*.py` 对 `agent_core` 的 import 数为 **0** | `grep -rn "from agent_core" packages/agent-runtime/agent_runtime/memory*.py` → 空 |
| F7 | `agent_server` **同一进程内并行两套记忆**：语义记忆走 `longterm.py` → `memory_backend` → `agent_core.memory.typed`（`memories` 表）；执行记忆走 `main.py` 的 `_build_memory_hooks` / `_build_context_governor` → `agent_runtime.memory_*`（`episodic_memories` / `procedural_memories` 表） | `main.py:84-100`、`:118-135`；`longterm.py:22,90` |
| F8 | 语义记忆这条线**已成功收口到内核**：`agent_federation` 与 `agent_server` 双侧均走 `agent_core.memory.typed` | `agent_federation/agent/memory/semantic_memory.py:36-50`；`agent_server/memory/longterm.py:22` |
| F9 | `UserSemanticStore` / `SharedSemanticStore` 全仓**仅抽象定义 + 2 个测试 mock，无生产实现** | `agent_runtime/semantic_memory.py:54,66`；grep 实现者仅 `tests/test_memory_types.py:145,150` |
| F10 | 各 application 对 `agent_core` 的 import 数：federation 67 / server 23 / knowledge 31 / exhibition 19 / nl2sql 15 / kefu 10 —— **内核复用已是常态，非个别现象** | `grep -rn "from agent_core" applications/*/` |

### 1.2 由此得到的诊断

把 F1–F5 与 F6 放在一起看，矛盾就清楚了：

- 架构契约说：**记忆归内核**（F1/F2），且**子包不得各自为政**（F3）；
- 但内核提供的契约**只覆盖语义记忆**（F4/F5），**对执行记忆（episodic 轨迹 / procedural 技能 / working）零覆盖**；
- 而 `agent-runtime` 恰恰需要执行记忆来支撑 `ContextSelector` 与写路径自动沉淀——**内核没有，只能在 runtime 自建**（F6/F7）。

**结论：`agent-runtime` 的 `memory_*` 不是对内核的重复实现，而是内核能力缺位下的必然自建。** 语义记忆那条线（F8）证明了：只要内核提供契约，两侧就会自然收敛到同一实现。

这与 ADR-0004 的情形完全同构——当时是「agent_federation 无类型路径」导致能力割裂，解法是把类型化记忆下沉内核；现在是「agent-runtime 无执行记忆契约」导致能力割裂，解法同构。

### 1.3 附带的语义冲突（易被忽略，须一并处理）

| 来源 | `episodic` 指什么 | 落库 |
|------|------------------|------|
| `agent_core.memory.typed.MemoryType` | `memories` 表内一条**情节型语义事实**（如「用户上周问过 X」） | `memories` |
| `agent_runtime.memory_types.MemoryCategory` | **一次执行的完整轨迹**（task_summary + key_steps + outcome） | `episodic_memories` |

**同名不同义。** 当前靠物理隔离（不同表、不同包）尚可区分；一旦做契约对齐或跨层合并，极易静默串味。须在决策中显式定名。

---

## 2. 决策

**沿用本仓库已验证成功的范式：协议下沉内核（零依赖签名）+ 实现留宿主（薄适配器）+ 开关灰度。**

该范式在优化 E / P4.3 已成功落地一次（当时在 `agent_core/memory/backend.py` 仅放 `MemoryBackend` Protocol 签名，实现留在 `app/memory/memory_backend.py`，内核由此成为唯一真相源）。本 ADR 不做新发明，只把同一范式应用到执行记忆。

### 2.1 内核新增「执行记忆协议」（零依赖，仅签名）

在 `agent_core/memory/` 下新增 `execution.py`：

- **数据模型**（`stdlib @dataclass`，不引 pydantic，遵守 `agent-core` 零依赖铁律——与 ADR-0004 决策 1 同一理由）：
  - `Episode`：execution_id / task_summary / key_steps / outcome / importance / created_at
  - `ProceduralEntry`：name / version / description / steps / status(draft|stable|deprecated) / usage_count
- **协议**（`typing.Protocol`，`runtime_checkable`）：
  - `EpisodicStoreProtocol`：`save` / `recall` / `get` / `list_by_execution` / `delete`
  - `ProceduralStoreProtocol`：`save` / `get` / `list_versions` / `promote` / `deprecate`
- **方法签名一律显式带 `tenant_id`**（默认 `_TENANT_UNSET`，沿用 `_tenant_gate.resolve_tenant` 语义：归属不明的记忆宁可暂不可见，也不跨租户可见）。

> 边界（遵守 ADR-0004 决策 6「抽取阶段不下沉」）：**内核只放协议与数据模型，不放 SQL 实现、不放 LLM 抽取、不放评分实现。** PG 实现与 sink 编排留在 `agent-runtime`。

### 2.2 内核门面扩展

- `MemoryStore` 增加可选的执行记忆动词（或并列第二个门面 `ExecutionMemoryStore`），使「语义记忆」与「执行记忆」在同一门面下可被发现。
- `CapabilityReport` 增加 `supports_episodic` / `supports_procedural` / `supports_working` 三个能力位，消除「开关配错 → 静默无记忆且无从排查」。

### 2.3 runtime 侧改为薄适配器

- `agent_runtime/memory_pg.py` 的 `PgEpisodicStore` / `PgProceduralStore` **声明实现内核协议**（`class PgEpisodicStore(EpisodicStoreProtocol)`），SQL 实现保留在原处。
- 保留不动：`ContextSelector`（防 context pollution）、`memory_sink.py` 写路径编排与 LLM 抽取、`SkillUsageTracker` 生命周期、`ContextGovernor` 管道——这些属于执行编排，不属内核。

### 2.4 评分与治理语义统一（消除不对称）

| 项 | 现状 | 处置 |
|----|------|------|
| 评分 | 三轨：`typed.py` 加权融合 / `PgEpisodicStore` `ORDER BY importance` / `three_factor_score` 仅内存路径用 | 把 `three_factor_score`（bigram Jaccard，中文友好）**下沉内核**作为共享评分函数，两轨统一调用 |
| 租户 | `typed.py` 严格（拒绝 default 过渡读）；episodic/procedural **无 tenant_id**，ILIKE 全表跨租户可见 | 协议层强制 `tenant_id` 形参 + 迁移补列（见 plan T1） |
| 去重 / provenance / 审计 | 语义侧部分具备，执行侧全无 | 协议层统一字段约定（见 plan T3/T4/T5） |
| 命名冲突 | `episodic` 在两层同名不同义（§1.3） | 内核协议中 `Episode` 一律指**执行轨迹**；`typed.MemoryType.episodic` 标注为「情节型事实」，并在协议 docstring 显式互斥说明 |

### 2.5 开关与灰度

- 新增 `EXECUTION_MEMORY_KERNEL_CONTRACT`（默认 `false`）：仅控制「是否按内核协议校验 runtime 实现」（`isinstance` 断言），**不改变运行时行为**。
- 灰度期内部实现仍在 runtime，纯契约校验，零数据迁移、零行为变更。

---

## 3. 替代方案

1. **把 runtime 的执行记忆整体搬进 `agent-core`**（否决）：违反 F3（内核只收协议与零依赖实现）与 ADR-0004 决策 6（LLM 抽取不下沉）；会把 sink 编排与 `ContextSelector` 拖进内核，破坏内核框架无关性。
2. **把执行记忆合并进语义记忆的 `memories` 表**（否决）：二者语义不同（用户画像 vs 执行经验）、生命周期不同（跨会话长期 vs 随执行滚动）、召回策略不同；合并会毁掉程序性记忆沉淀管道，且违反 `semantic_memory.py` 已确立的「RAG / Memory 两层分离」正确设计。
3. **维持现状，只在文档里说明「两套是合理的」**（否决）：租户、评分、审计、provenance 四处不对称会各自漂移，最终必然长出真·双份真相源；且 `UserSemanticStore` 空实现（F9）已是一个正在成形的重复入口。
4. **什么都不做，等两侧自然收敛**（否决）：F8 证明收敛依赖内核提供契约；没有契约就不会有收敛。

---

## 4. 后果

**正向**

- 记忆层的租户 / 评分 / 审计 / provenance 语义**一处定义、两处遵守**，从根本上消除「双份真相源」的生长土壤；
- `agent_federation` 未来可获得执行记忆路径（对称补齐），与 `agent_server` 同契约；
- `CapabilityReport` 扩展后，记忆能力状态可被 `/health` 观测；
- `agent-runtime` 的执行记忆从「架构越位」变为「契约内的宿主实现」，与 `ARCHITECTURE.md` §2.1 对齐。

**负向 / 风险**

- 内核新增模块，需 CI 证明其零第三方依赖（建议加一条 import 白名单测试）；
- 协议一旦下沉，runtime 后续调整需先动协议（演进成本上升，但正是收口的目的）；
- 灰度开关若长期不打开，协议会与实现漂移 —— 建议协议落地后一期内打开断言；
- §1.3 的命名冲突需在协议 docstring 中显式声明，否则后续维护者仍会踩。

**不做的事**（明确边界，防止过度扩张）

- 不做数据迁移（`episodic_memories` 表结构不变）；
- 不改运行时行为（灰度期纯契约校验）；
- 不动 `ContextSelector` / `ContextGovernor` / `memory_sink` 编排逻辑。

---

## 5. 验证

- **内核零依赖**：`agent_core/memory/execution.py` 仅 import stdlib，加 CI 断言；
- **协议一致性**：`assert isinstance(PgEpisodicStore(pool), EpisodicStoreProtocol)` 在 `EXECUTION_MEMORY_KERNEL_CONTRACT=true` 下通过；
- **租户对称**：执行记忆与语义记忆在相同租户隔离测试用例下表现一致（扩展 `tests/ha/test_tenant_isolation_real_pg.py`）；
- **能力探测**：`CapabilityReport` 能如实报告 `supports_episodic` / `supports_procedural`；
- **回归**：`agent-runtime` 现有 62 条测试 + `agent_federation` 44 条全绿，行为零变更。

---

## 6. 决策记录（2026-09-27 评审采纳）

> 本轮评审将四项「倾向」锁定为正式决策，并补充实现中确定的数据模型归属决策。

1. **执行记忆门面 → 并列 `ExecutionMemoryStore`（延后实现）**：T0 先下沉内核 Protocol + `CapabilityReport` 能力位；并列门面作为后续增量，不阻塞协议收口（避免引入未实现门面）。
2. **`three_factor_score` 不替换 `typed.py` 加权融合**（锁定）：语义记忆评分已通过生产审计，执行记忆用三因子，按 `MemoryCategory` 分派，不混用。
3. **`UserSemanticStore`（F9）单独立项**（归 plan-memory-hardening T8）：本次未实现，作为后续收口项（薄适配器）。
4. **`typed.MemoryType.episodic` 不重命名**（锁定）：协议 docstring 显式互斥声明 + 测试锁定语义（见 `test_execution_memory_kernel_protocol.py`）。
5. **（实现新增决策）数据模型归属**：`Episode` / `ProceduralEntry` dataclass 由 runtime 拥有（已是事实真相源），内核**只下沉 Protocol**、不重复定义 dataclass——在内核再定义一份会重现双份真相源，与 ADR-0005 目标相悖。

### 6.1 实施状态（2026-09-27，T0 已落地）

- **内核协议层**：`packages/agent-core/agent_core/memory/execution.py`（`EpisodicStoreProtocol` / `ProceduralStoreProtocol`，`@runtime_checkable`，纯 stdlib + `_tenant_gate`，零反向依赖）；`store.CapabilityReport` 扩展 `supports_episodic` / `supports_procedural` / `supports_working`；`__init__.py` 导出两协议。
- **验证**：`packages/agent-core/tests/test_execution_contract.py`（零第三方依赖断言 + Protocol 可满足性）+ `packages/agent-runtime/tests/test_execution_memory_kernel_protocol.py`（`PgEpisodicStore`/`PgProceduralStore` isinstance 满足协议，零基类改动）。`uv run pytest` 5 passed。
- **runtime 适配零冲突**：因 `runtime_checkable` 仅校验方法存在性（structural typing），现有 `Pg*` 实现无需改基类即满足内核协议——与执行 agent 在 `feat/isolation-hardening` 的并行 A3-A4 开发互不干扰。
- **未完项**：T8（UserSemanticStore 薄适配器）、并列 `ExecutionMemoryStore` 门面、评分函数下沉（决策 2 锁定为「不替换」，故评分下沉本身不再必要）。

---

## 7. 与既有文档的关系

- 本 ADR 是 `ARCHITECTURE.md` §2.1「memory 归 agent-core」的**落地路径**，不是对其的修改；
- 执行细节（迁移 SQL、字段、验收用例）在 `docs/plans/plan-memory-hardening-2026-09-27.md`，本 ADR 不重复；
- 与 ADR-0004 同构：ADR-0004 下沉**类型化语义记忆**，本 ADR 下沉**执行记忆协议**，二者共同构成内核记忆契约的两半。
