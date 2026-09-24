# 05 — exhibition-agent 定位评估（F-S1-05 决策输入）

> 2026-09-21；为 F-S1-05（exhibition-agent 独立实现 Skill+ExecutionContext，红线 4）提供定位决策输入。
> 对应假设 H-S1-02（exhibition 不依赖 agent-runtime 是否有意豁免红线 4）。

## 1. exhibition-agent 定位（README + 代码）

**会展行业 AI Agent 平台侧骨架**，按《跨项目接口契约 v1.1》接入 `mingyang-warehouse`：

- 最小骨架验证 **C1（ExecutionContext）+ C2（统一信封 + 错误码）+ C4（trace）** 三条契约；
- 重点把 **INV-10（指标口径不可绕过）** 变成可回归自动化测试；
- 平台侧可不等 warehouse 就绪就跑通契约链路（全走 mock server）；
- 99 测试，独立 uv workspace 成员。

→ 定位是**跨项目契约验证骨架**，不是通用 Agent 运行时宿主。

## 2. Skill / ExecutionContext 对比（exhibition vs agent-runtime）

### 2.1 ExecutionContext

| 维度 | exhibition `contract/execution_context.py` | agent-runtime `planner/protocol.py:170` |
|------|--------------------------------------------|------------------------------------------|
| 类型 | pydantic BaseModel（字段冻结，契约 v1.1 §C1） | dataclass（可变，运行时聚合器） |
| 字段 | user_id / tenant_id / tenant_type / roles / scopes / auth_source / request_id | execution_id / identity / step_count / call_stack / max_steps / max_depth / deadline / tokens_used / cost_used / steps / fingerprints |
| 语义 | **信任上下文**（谁在调、权限、审计键，INV-8 载体） | **执行预算/调用栈**（步数、深度、token/cost 聚合、循环指纹） |
| 用途 | 沿调用链传递，warehouse 只信此上下文 | 绑定一次 execution，嵌套 Skill 共享预算 |

**结论**：语义正交。exhibition 的是"谁、有何权限"，agent-runtime 的是"执行了多少、预算剩多少"。**不可直接复用**。

### 2.2 Skill

| 维度 | exhibition `skills/base_skill.py` | agent-runtime `skills/registry.py:40` |
|------|------------------------------------|----------------------------------------|
| 形态 | `BaseSkill(ABC)` + 子类实现 `run(params, ctx) → SkillResult` | `Skill(frozen dataclass)` + `executor: Executor`（函数式注册） |
| 结果 | `SkillResult`：answer / readiness / classification / sources / citations / egress_decision / error_code（业务契约字段） | 由 executor 返回，`to_tool_schema()` 生成工具描述 |
| 上下文 | `SkillContext`：execution_context + warehouse_client（业务注入） | `ExecutionContext`（运行时预算） |
| 治理 | 只读（INV-6），MetricPendingError → 答"待接入"（INV-10） | permissions / sub_skills / CompositionValidator（组合治理） |

**结论**：exhibition 的是**业务 skill 基类**（结果含契约字段），agent-runtime 的是**能力注册条目**（含执行器+schema+权限）。可适配但非直接复用。

## 3. 收敛选项

### 选项 A：保持独立（推荐）

exhibition 作为契约骨架，独立实现 Skill/ExecutionContext（契约载体），不接入 agent-runtime。

- **理由**：
  1. 契约验证需字段冻结的严格模型（ExecutionContext 字段冻结于 v1.1 §C1），agent-runtime 的运行时 dataclass 语义不同；
  2. 接入会模糊契约边界——exhibition 的"信任上下文"与 agent-runtime 的"执行预算"是正交关注点；
  3. exhibition 定位是"骨架"，接入 agent-runtime 会将其变为"运行时宿主"，改变定位；
  4. 红线 4（内核能力不得重复实现）针对的是**运行时内核能力**（CircuitBreaker/Cache/Tracer 等），exhibition 的 Skill/ExecutionContext 是**业务契约载体**，性质不同。
- **代价**：维持两套 Skill/ExecutionContext（但语义不同，非纯重复）。
- **F-S1-05 处置**：标记为"有意豁免（契约载体非运行时内核能力）"，关闭红线 4 违规判定，但记录豁免理由。

### 选项 B：接入 agent-runtime

exhibition 作为 agent-runtime 应用宿主，复用 Skill/SkillRegistry/ExecutionContext。

- **代价**：
  1. ExecutionContext 语义对齐需大改其一（exhibition 加预算字段 / agent-runtime 加信任字段）；
  2. BaseSkill ABC → Skill dataclass 适配层；
  3. SkillResult 业务字段（readiness/classification/egress）需在 agent-runtime 找位置或保留 exhibition 侧包装。
- **风险**：契约边界模糊，INV-8/INV-10 的字段冻结保证被运行时 dataclass 削弱。
- **不推荐**（除非 exhibition 演进为生产应用）。

### 选项 C：部分接入

ExecutionContext 保持独立（契约载体），Skill 经适配层接入 agent-runtime SkillRegistry（只读 skill 注册为 FUNCTION kind）。

- **代价**：适配层 + 双上下文（exhibition ExecutionContext 注入 agent-runtime ExecutionContext.metadata）。
- **收益**：Skill 发现/组合治理复用 agent-runtime。
- **适用条件**：exhibition 需要多 Skill 组合治理（当前骨架只有 venue.schedule.query 单 skill，无此需求）。

## 4. 决策输入（H-S1-02）

| 问题 | 选项 | 推荐 |
|------|------|------|
| exhibition 不依赖 agent-runtime 是否有意豁免红线 4？ | A 保持独立 / B 接入 / C 部分接入 | **A**（契约载体非运行时内核能力，语义正交） |

**推荐决策**：**选项 A**，F-S1-05 标记为"有意豁免（契约载体）"，关闭红线 4 违规判定。理由：
- exhibition 的 Skill/ExecutionContext 是跨项目契约载体（INV-8/INV-10），语义与 agent-runtime 运行时协议正交；
- 红线 4 针对运行时内核能力重复实现（如 F-S1-04 的 CB/Cache、F-S1-06 的 NoOpTracer），不针对业务契约模型；
- 强行收敛会模糊契约边界，削弱字段冻结保证。

**待维护者拍板**：若认可选项 A，F-S1-05 从"仍成立债务"移入"有意豁免（已决策）"；若未来 exhibition 演进为生产应用，重开选项 B/C 评估。

## 5. 后续

- 本评估为 F-S1-05 提供决策输入，**不改动代码**；
- 待维护者拍板后，更新 02-debt-diagnosis.md F-S1-05 状态（豁免 / 立收敛方案）；
- 若选 A，无需进一步动作；若选 B/C，立 `plan-fix-f-s1-05-exhibition-runtime-converge.md`。
