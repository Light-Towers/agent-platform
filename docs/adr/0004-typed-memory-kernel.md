# ADR-0004: 类型化记忆下沉内核（方向 2 正确形态）

- 状态：修订中（Revised，待复评）
- 日期：2026-08-18（首版）；2026-08-18（v2 按评审返工）
- 关联：ADR-0003（双数据库驱动并存）、TB-10（语义记忆接线）、优化 H（app 类型感知记忆）
- 前置评估结论：`docs/architecture-improvement-plan.md` 方向 2 影响分析（不推荐直接搬 app 代码）

## 背景

当前语义记忆能力分布呈现「内核薄 / app 厚」的割裂：

| 能力 | 位置 | 状态 |
|------|------|------|
| 原始向量记忆（`recall_memories` / `remember_memory`） | `agent_core.memory.semantic`（内核，零依赖） | 已是单一真相源，agent_federation 已接线（TB-10, PR #4） |
| 类型化读写（`recall_typed` / `remember_fact`） | `app/memory/memory_backend.py`（app 专有层） | 已落地（优化 H），但仅 app 可用，agent_federation 无类型路径 |
| 分层加权融合 + 时间衰减 | `app/memory/memory_backend.py::recall_typed` | 已落地（优化 H），仅 app 可用 |
| 事实抽取（`extract_memory_facts`，LLM 结构化） | `app/memory/longterm.py` | 已落地，仅 app 可用 |
| 巩固 / 遗忘（`consolidate_memories` / `forget_memory`） | `app/memory/memory_backend.py` | 已落地完整 SQL（优化 H），仅 app 可用 |

> 修订注（SP-3）：首版称 consolidate/forget「部分未完全落地」已过时——核实 `memory_backend.py:158` / `:181` 已实现完整 SQL，且与优化 H 已接线。修正为「已落地但仅 app 可用，agent_federation 无类型路径」。

### 现状关键技术事实（修订 v2 补充，回应 SP-1 / G2）

下沉前必须正视**两套驱动 + 两张表**的现状，否则「单一真相源」只是主张：

1. **内核 `agent_core.memory.vector_backend`**：
   - 默认后端为 **Milvus**（`vector_backend.py:5,370`）；pg 模式后端为 `PgVectorMemoryBackend`（asyncpg）。
   - `PgVectorMemoryBackend._init_schema`（`vector_backend.py:262-280`）建的 `memories` 表**仅 `(id, user_id, content, embedding)` 四列**（tenant 模式多 `tenant_id`），**无 `memory_type`/`importance`/`created_at`**。
   - `PgVectorMemoryBackend.recall(pool, ...)` 形参 `pool` 为 **asyncpg** 风格（`cp.acquire()`，`vector_backend.py:301`）。
   - 内核 `semantic.py` 的 `__all__` 含 **5 个**公开符号：`semantic_memory_enabled` / `get_default_backend` / `get_semantic_memory`（兼容别名）/ `recall_memories` / `remember_memory`（首版漏列 `get_semantic_memory`，ST-1 笔误修正）。

2. **app `memories` 表（`app/infra/db.py:32-41`）**：
   - 含 `memory_type TEXT` / `import_at`（实为 `created_at`）/ `importance FLOAT`，共 7 列，是内核四列表的**超集**。
   - app 类型路径（`memory_backend.py:88-189`）**直接用 app psycopg 池 + `app.infra.db.vector_search`**，**完全没走**内核 `PgVectorMemoryBackend`。

→ 结论：内核表比 app 表少 3 列、驱动不同（asyncpg/Milvus vs psycopg）。"app 表直接复用内核契约"在首版不成立，须在决策中明确对齐方案（见下）。

## 决策

### 内核契约变更范围（最小化、可选，v2 完整披露）

在 `agent_core/memory/` 下新增**可选**模块 `typed.py`，并扩展现有后端契约：

1. **新增内核数据模型**（零依赖，明确选型）：
   - `TypedMemory = @dataclass`（**不用 pydantic**）：`content: str` / `memory_type: str` / `importance: float` / `created_at: datetime` / `id: int | None`。
   - `MemoryType` 枚举：`episodic` / `semantic` / `procedural`（与 app 现有 `_MEMORY_TYPES` 对齐）。
   - 选型理由（G1）：`agent-core/pyproject.toml:14` 的 `dependencies = []`，pydantic 不在内核硬依赖；引入需加 extra，违反 §3 零依赖铁律。故用 stdlib `@dataclass`，零新增依赖。

2. **内核后端 schema 扩展（SP-1 / SP-2 修正）**：
   - `PgVectorMemoryBackend._init_schema` 增加 `memory_type TEXT DEFAULT 'semantic'` / `importance FLOAT DEFAULT 0.5` / `created_at TIMESTAMPTZ DEFAULT now()` 三列（仅 pg 模式）。
   - Milvus 集合 schema（`vector_backend.py:59-66`）增加对应标量字段（`memory_type` / `importance` / `created_at`），或 typed 路径在 Milvus 模式下降级为无类型（见开关）。
   - **app 表经幂等 `ALTER TABLE` 对齐内核契约**（已是超集，补默认值即可，不破坏现有数据）。
   - 此改动落在 `vector_backend.py`——首版未在"契约变更范围"列出，v2 补入。

3. **新增内核可选 API**（不替换现有 `recall_memories`/`remember_memory`）：
   - `recall_typed(pool, user_id, question, k=3, weights=None) -> list[TypedMemory]`：**显式接收 `pool`**（G2/ST-3 修正）。`pool` 类型 = 宿主传入的 psycopg `AsyncConnectionPool`（pg 模式，与 app 同池）或内核自建 asyncpg 池（见驱动策略）。语义召回后按 `type_weight × importance × time_decay` 融合排序（移植 app `recall_typed` 加权逻辑，公式为内核事实；`time_decay = 1/(1+0.01*age_days)`，双曲衰减，非线性）。
   - `remember_typed(pool, user_id, fact, memory_type, importance) -> None`：fire-and-forget 沉淀。同样接收 `pool`。
   - `consolidate(user_id, pool, forget_threshold) -> int` / `forget(user_id, pool, memory_id) -> bool`：巩固+遗忘（移植 app 已落地 SQL）。
   - `semantic.py` 新增可选导出 `recall_typed` / `remember_typed`（复用 `typed.py`），现有 5 个公开符号签名不变。

4. **驱动策略（G2 核心，v2 拍板）**：
   - **pg 模式**：内核 typed 路径**接收宿主 psycopg 池**（与 app 共用同一池，避免双池违反 ADR-0003 连接数警示）。内核 `typed.py` 内部用 psycopg async API（`pool.connection()`），**不自建 asyncpg 池**。
   - **Milvus 模式**：typed 路径降级——`recall_typed` 退化为无类型语义召回（仅按 importance 排序，无 memory_type 维度），或经 `SEMANTIC_MEMORY_TYPED` 关闭回退原始路径。
   - 非 pg/Milvus 模式（内存降级）：typed 路径不可达，`typed_memory_enabled()` 返回 false。

5. **开关隔离**：
   - `SEMANTIC_MEMORY_TYPED`（默认 `false`）：仅当 `true` 且 `SEMANTIC_MEMORY_ENABLED=true` 时启用类型路径。
   - 调用方经 `typed_memory_enabled()` 判定。关闭时：
     - app re-export 层**继续走自身 psycopg 池的 `recall_typed`/原始逻辑**（G3 修正：不切内核 asyncpg/Milvus 自建池，连接来源不变，事务边界不变）；
     - agent_federation 回退到 `recall_memories`/`remember_memory`（已接线的 PR #4 路径，零行为变更）。

6. **抽取阶段不下沉**：`extract_memory_facts`（LLM 抽取）**留在宿主层**（app / agent_federation 各自调用自己的 LLM 客户端），内核只接收已抽取的结构化 `TypedMemory`。原因：抽取粒度因宿主而异（app 单轮 Q-A vs DeepAgent 长程多步），且依赖 LLM 客户端（违反内核零依赖）。

### 护栏合规（§3，v2 明确）

- `agent_core.memory.typed` 核心逻辑仅依赖 stdlib（`@dataclass` + `datetime`），**不引入 pydantic**。
- **驱动依赖归属（二次评审 #1 修正）**：`vector_backend.py` 只用 **asyncpg**（`pool.acquire()` + `$N` 占位符，`vector_backend.py:301-313`），**不碰 psycopg**；psycopg 仅经 `get_checkpointer`（`memory/__init__.py:48`）使用，与 vector/typed 下沉无关。故内核 typed 的 pg 路径：**asyncpg 经内核现有 `vector_backend` 间接使用（可选 extra + 懒加载）**；若采用「接收宿主 psycopg 池」策略（驱动策略 4），则 psycopg 由宿主提供，内核不新增 psycopg 硬依赖。两种策略下内核均**不新增硬依赖**。
- LLM 抽取不进内核，内核不感知任何 LLM 客户端。
- 向后兼容：`semantic.py` 现有 5 个公开符号（`semantic_memory_enabled` / `get_default_backend` / `get_semantic_memory` / `recall_memories` / `remember_memory`）签名不变，调用方（含 PR #4 已接线的 agent_federation）零改动。

### 返回类型与 re-export 投影（SP-4 澄清）

- 内核 `recall_typed -> list[TypedMemory]`；app `memory_backend.py` 改为 re-export 内核，并在适配层做 `.content` 投影，保持 app 现有 `recall_typed -> list[str]` 契约（`longterm.recall` / `graph.py` 下游无需改）。即 re-export 层负责类型投影，app 既有测试不变。

### 迁移路径（两阶段，独立 PR）

- **阶段 1（本 ADR 落地）**：内核新增 `typed.py`（含 `vector_backend.py` schema 扩展）+ app `memory_backend.py` 改为**薄适配层** re-export 内核（同优化 F 的 re-export 手法），适配层做 `.content` 投影；app 既有测试不变；agent_federation 可选接入 `recall_typed`（不强制）。
- **阶段 2（后续）**：agent_federation 在 `run_deep_agent` 接入 `recall_typed`/`remember_typed`，实现与 app 共用类型记忆；统一 `memories` 表契约到内核定义并下发迁移脚本。

## 替代方案

1. **直接搬 app `memory_backend.py` 到内核**（已否决）：违反 §3 护栏（内核契约变更 + 双份 schema 风险）、抽取粒度错配、搬的是半成品（首版误述，实为已落地但仅 app 可用）。
2. **agent_federation 复制 app 代码**（已否决）：双份真相源，合并冲突风险，违背单一真相源原则。
3. **维持现状（app 专有，agent_federation 无类型）**：可接受为临时态，但 agent_federation 永远无法获得类型增强，且 app 类型逻辑无法被内核测试门禁覆盖。

## 后果

- **正向**：
  - 类型化记忆成为跨子包单一真相源，app + agent_federation 共用内核实现，消除复制；
  - 内核可加框架无关单测（加权融合 / 衰减 / 遗忘），CI 门禁可覆盖（当前 app 类型逻辑无独立单测）；
  - agent_federation 长期记忆获得类型增强路径，且与 app 同契约。
- **负向 / 风险**：
  - 内核契约变更：`vector_backend.py` 的 `memories` 表新增 `memory_type`/`importance`/`created_at` 列（pg 模式）+ Milvus 集合标量字段；各子包需迁移（app 幂等 ALTER，agent_federation/kefu/wenda 若启用需建表）。
  - 与现有双驱动（ADR-0003）叠加，pg 模式 typed 路径复用宿主 psycopg 池（不新增池），Milvus 模式降级无类型。
  - **驱动切换移植成本（二次评审 #2）**：app 类型路径用 psycopg 池（`%s` 占位符 + `pool.connection()`，`memory_backend.py:142-155`），内核 `vector_backend` 用 asyncpg 池（`$N` 占位符 + `pool.acquire()`，`vector_backend.py:301-313`）。若采用「接收宿主 psycopg 池」策略，内核 `typed.py` 需**同时改写**：① 占位符风格 `$N`→`%s`；② 池 API `acquire()`→`connection()`；③ 解除对 `app.infra.db.vector_search` 的依赖（改为内核内联 SQL）。若采用「内核 asyncpg 自建池」策略，则 app 适配层需反向改写。移植工作量需在阶段 1 估算。
  - 加权融合公式（type_weight / decay 系数）固化内核事实，宿主可经 `weights` 入参覆盖（见待决策项 2）。
- **运维约束**：`SEMANTIC_MEMORY_TYPED` 默认关闭；CI 零密钥环境走内存降级，typed 路径不可达（符合现有 CI 门禁分层）。

## 验证（落地后）

- 内核单测（无 DB/无 LLM）：`recall_typed` 加权排序正确性、`time_decay` 单调性、`consolidate` 遗忘阈值、`forget` 删除；
- 回归：app 现有 `test_longterm_h.py` / `memory_backend` 调用经 re-export 层（含 `.content` 投影）不变，agent-core 全量 + app eval（`python -m eval.run_eval`）基线不降；
- 端到端：agent_federation 接入后，多轮对话类型记忆召回正确（比对 PR #4 的 `test_semantic_memory.py` 扩展）。

## 待决策项（评审时需拍板，v2 收敛）

1. **表契约迁移脚本归属**：内核统一定义并下发迁移脚本（推荐），还是各子包自带 migration？→ 推荐内核 `vector_backend.py` 内 `_init_schema` 幂等加列 + 提供 ALTER 片段。
2. **加权系数覆盖方式**：默认系数（`procedural=1.2 / semantic=1.1 / episodic=1.0` + `time_decay=1/(1+0.01*age_days)` 双曲衰减）写死在 `typed.py`；`weights` 入参覆盖优先于默认（G4 澄清：签名已支持入参覆盖，env 覆盖为**可选增强**，非必需，待决策是否加 env 旋钮）。
3. **阶段 2 是否随本 ADR 一并 PR**：建议单独立项（与首版一致），避免扩大本 ADR 落地面。

## 修订记录（v2，回应评审）

- SP-1：背景补全「两套驱动+两张表」事实，决策明确 schema 扩展 + 驱动策略（psycopg 池复用），删去「app 直接复用」错误主张。
- SP-2：契约变更范围补入 `vector_backend.py`（`_init_schema` 加列 + recall/remember 读类型列）。
- ST-1：公开符号补 `get_semantic_memory`（共 5 个）。
- ST-2：明确 `TypedMemory = @dataclass`（零依赖，不引 pydantic）。
- ST-3/G2：`recall_typed`/`remember_typed` 签名显式接收 `pool`，说明 psycopg 池类型。
- G3：关闭开关时 app 走自身 psycopg 池（不切内核自建池），连接来源/事务边界不变。
- SP-3：consolidate/forget 改为「已落地但仅 app 可用」。
- SP-4：re-export 层做 `.content` 投影保 `list[str]` 契约。
- G4：`weights` 入参覆盖优先于默认，env 覆盖列为可选增强（待决策项 2）。

## 修订记录（v2.1，回应二次评审）

状态由「修订中」收敛为「采纳待拍板」。二次评审 4 条核实：

- **#1 psycopg 归属（采纳）**：护栏合规段改为「asyncpg 经内核 vector_backend 间接使用；psycopg 仅经 get_checkpointer，与 typed 下沉无关」，删除模糊的「psycopg/asyncpg 经宿主池传入」。
- **#2 驱动切换移植成本（采纳）**：负向风险补「占位符 `$N`→`%s` + 池 API `acquire()`→`connection()` + 解除 `app.infra.db.vector_search` 依赖」的移植清单，阶段 1 需估算。
- **#3 衰减公式（采纳）**：`time_decay` 改为精确双曲衰减 `1/(1+0.01*age_days)`（核实 `memory_backend.py:135`），非线性。
- **#4 公开符号（已修正，v2 行 59 已列 5 个）**：评审引首版行号，v2 已补 `get_semantic_memory`；本段显式列全 5 个符号。
- **反驳：二次评审沿用首版「consolidate/forget 部分未完全落地 ✅」**：经核实 `memory_backend.py:158`/`181` 为**完整 SQL 实现**（与首版 SP-3 已被推翻一致），该 ✅ 系评审未重新核实代码、照抄首版过时判断。维持 v2「已落地但仅 app 可用」结论，不予采纳。

**二次评审已核实准确的声明（与 v2 一致）**：`extract_memory_facts` 位于 `longterm.py:42` ✅；agent_federation `semantic_memory.py` 纯 re-export ✅；`_MEMORY_TYPES` 三值与 `MemoryType` 对齐 ✅；加权公式 `type_weight×importance×time_decay` 一致 ✅；`type_weight 1.2/1.1/1.0` 一致 ✅。
