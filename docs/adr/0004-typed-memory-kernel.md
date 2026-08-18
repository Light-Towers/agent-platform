# ADR-0004: 类型化记忆下沉内核（方向 2 正确形态）

- 状态：提议（Proposed，待评审）
- 日期：2026-08-18
- 关联：ADR-0003（双数据库驱动并存）、TB-10（语义记忆接线）、优化 H（app 类型感知记忆）
- 前置评估结论：`docs/architecture-improvement-plan.md` 方向 2 影响分析（不推荐直接搬 app 代码）

## 背景

当前语义记忆能力分布呈现「内核薄 / app 厚」的割裂：

| 能力 | 位置 | 状态 |
|------|------|------|
| 原始向量记忆（`recall_memories` / `remember_memory`） | `agent_core.memory.semantic`（内核，零依赖） | 已是单一真相源，deepagents 已接线（TB-10, PR #4） |
| 类型化读写（`recall_typed` / `remember_fact`） | `app/memory/memory_backend.py`（app 专有层） | 仅 app 可用 |
| 分层加权融合 + 时间衰减 | `app/memory/memory_backend.py::recall_typed` | 仅 app 可用 |
| 事实抽取（`extract_memory_facts`，LLM 结构化） | `app/memory/longterm.py` | 仅 app 可用 |
| 巩固 / 遗忘（`consolidate_memories` / `forget_memory`） | `app/memory/memory_backend.py` | 仅 app 可用，部分未完全落地 |

deepagents 的 `agent/memory/semantic_memory.py` 只是内核原始版的薄封装，且**只接了无类型路径**（PR #4 接的 `recall_memories`/`remember_memory`）。这意味着 deepagents 长期记忆**无类型增强**——若将来想要，只能复制 app 的 `memory_backend.py` 代码（违反单一真相源）。

历史结论（方向 2 影响分析）已明确：**直接把 app `memory_backend.py` 搬到内核不推荐**——会触发 §3 护栏（内核契约变更 + 双份 `memories` schema 风险）、抽取粒度错配（DeepAgent 长程多步 vs app 单轮 Q-A）、且搬的是半成品（consolidation/融合权重未全实现）。

本 ADR 提出**方向 2 的正确形态**：把类型增强作为内核的**可选模块**，由 `SEMANTIC_MEMORY_TYPED` 开关控制，让 app + deepagents 共用内核实现，而非各造一份。

## 决策

### 内核契约变更范围（最小化、可选）

在 `agent_core/memory/` 下新增**可选**模块 `typed.py`，仅扩展契约，不改动现有 `semantic.py` 的原始接口：

1. **新增内核数据模型**（框架无关，stdlib + pydantic v2）：
   - `MemoryType` 枚举：`episodic` / `semantic` / `procedural`（与 app 现有 `_MEMORY_TYPES` 对齐）。
   - `TypedMemory` dataclass：`content` / `memory_type` / `importance`(0~1) / `created_at` / `id?`。

2. **新增内核可选 API**（不替换现有 `recall_memories`/`remember_memory`）：
   - `recall_typed(user_id, question, k, weights=None) -> list[TypedMemory]`：语义召回后按 `type_weight × importance × time_decay` 融合排序（移植 `app` 的 `recall_typed` 加权逻辑，公式为内核事实）。
   - `remember_typed(user_id, fact, memory_type, importance) -> None`：fire-and-forget 沉淀带类型记忆。
   - `consolidate(user_id, forget_threshold) -> int` / `forget(user_id, memory_id) -> bool`：巩固+遗忘（补全 app 半成品）。

3. **存储后端扩展**（遵循 ADR-0003 双驱动）：
   - 类型化列（`memory_type` / `importance`）下沉到内核向量后端 schema；
   - **单一 `memories` 表契约**由内核定义（app 当前表直接复用，deepagents 新建也用同契约），消除双份 schema 风险；
   - 内核 `PgVectorMemoryBackend` 增加可选 `with_types=True` 参数，写列缺省回退（兼容旧无类型行）。

4. **开关隔离**：
   - `SEMANTIC_MEMORY_TYPED`（默认 `false`）：仅当 `true` 且 `SEMANTIC_MEMORY_ENABLED=true` 时启用类型路径；
   - app / deepagents 调用方经 `typed_memory_enabled()` 判定，关闭时自动回退到 `recall_memories`/`remember_memory`（零行为变更）。

5. **抽取阶段不下沉**：`extract_memory_facts`（LLM 抽取）**留在宿主层**（app / deepagents 各自调用自己的 LLM 客户端），内核只接收已抽取的结构化 `TypedMemory`。原因：抽取粒度因宿主而异（app 单轮 Q-A vs DeepAgent 长程多步），且依赖 LLM 客户端（违反内核零依赖）。

### 护栏合规（§3）

- `agent_core/memory.typed` 核心逻辑仅依赖 stdlib + pydantic；psycopg/asyncpg 经内核现有 `vector_backend` 间接使用（可选 extra + 懒加载），**不新增内核硬依赖**。
- LLM 抽取不进内核，内核不感知任何 LLM 客户端。
- 向后兼容：现有 4 个公开符号（`semantic_memory_enabled` / `recall_memories` / `remember_memory` / `get_default_backend`）**签名不变**，调用方（包括 PR #4 已接线的 deepagents）零改动。

### 迁移路径（两阶段，独立 PR）

- **阶段 1（本 ADR 落地）**：内核新增 `typed.py` + 后端 schema 扩展 + 开关；app 的 `memory_backend.py` 改为**薄适配层** re-export 内核（同优化 F 的 re-export 手法），app 既有测试不变；deepagents 可选接入 `recall_typed`（不强制）。
- **阶段 2（后续）**：deepagents 在 `run_deep_agent` 接入 `recall_typed`/`remember_typed`，实现与 app 共用类型记忆；统一 `memories` 表契约到内核定义。

## 替代方案

1. **直接搬 app `memory_backend.py` 到内核**（已否决）：违反 §3 护栏（内核契约变更 + 双份 schema）、抽取粒度错配、搬半成品。
2. **deepagents 复制 app 代码**（已否决）：双份真相源，合并冲突风险，违背单一真相源原则。
3. **维持现状（app 专有，deepagents 无类型）**：可接受为临时态，但 deepagents 永远无法获得类型增强，且 app 类型逻辑无法被内核测试门禁覆盖。

## 后果

- **正向**：
  - 类型化记忆成为跨子包单一真相源，app + deepagents 共用内核实现，消除复制；
  - 内核可加框架无关单测（加权融合 / 衰减 / 遗忘），CI 门禁可覆盖（当前 app 类型逻辑无独立单测）；
  - deepagents 长期记忆获得类型增强路径，且与 app 同契约。
- **负向 / 风险**：
  - 内核契约变更：新增 `memories` 表的 `memory_type` / `importance` 列契约，需各子包 DB 迁移（app 已有该列可直接复用，deepagents/kefu/wenda 若启用需 `ALTER TABLE`）；
  - 与现有双驱动（ADR-0003）叠加，连接/表结构协调成本略增；
  - 加权融合公式（type_weight / decay 系数）需固定为内核事实，app 现 1.2/1.1/1.0 + `0.01*age` 作为默认，宿主可覆盖 `weights`。
- **运维约束**：`SEMANTIC_MEMORY_TYPED` 默认关闭，开启前需确认目标子包 `memories` 表含类型列；CI 零密钥环境走内存降级，类型路径不可达（符合现有 CI 门禁分层）。

## 验证（落地后）

- 内核单测（无 DB/无 LLM）：`recall_typed` 加权排序正确性、`time_decay` 单调性、`consolidate` 遗忘阈值、`forget` 删除；
- 回归：app 现有 `test_longterm_h.py` / `memory_backend` 调用经 re-export 层不变，agent-core 全量 + app eval（`python -m eval.run_eval`）基线不降；
- 端到端：deepagents 接入后，多轮对话类型记忆召回正确（比对 PR #4 的 `test_semantic_memory.py` 扩展）。

## 待决策项（评审时需拍板）

1. `memories` 表契约是否由内核统一定义并下发迁移脚本（vs 各子包自带 migration）？
2. 加权融合默认系数（type_weight / decay）是否允许宿主经 env 覆盖，还是硬编码内核事实？
3. 阶段 2 deepagents 接入是否随本 ADR 一并 PR，还是单独立项？
