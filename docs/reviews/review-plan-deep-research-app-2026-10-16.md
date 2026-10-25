# 方案评审报告：deep_research 应用方案（第 7 应用）

> 评审对象：`docs/plans/plan-deep-research-app-2026-10-16.md`（481 行，2026-10-16 版）
> 评审日期：2026-10-16
> 评审人：Nox
> 评审方式：**对抗式审计** —— 逐条回源核验方案中的事实断言（读代码 / 跑 grep / 读迁移 SQL），不采信方案自身表述
> 状态：<span style="color:red">**不建议按当前版本进入 P0 实施**</span> —— 有 1 处阻断级设计缺陷（F1）必须先修，否则 P0 骨架的图定义从根上写不出来
>
> **📝 变更记录**
>
> **本文档（评审报告）**
> - **v1.0**（2026-10-16）首版：19 条事实核验 + F1–F7 共 7 项发现。
> - **v1.1**（2026-10-16）① F6 追加并行工作口径——另一会话正在实施「身份门卫 6/6」（工作区可见未提交产物 `packages/agent-runtime/agent_runtime/identity_assembly.py` 与 `docs/plans/plan-identity-gate-6of6-2026-10-16.md`，其方案第 1 节明写将新增存在性门禁 P13）；② 新增 **F8**（跨会话并发改动风险，实施 P0 前须重读 HEAD）；③ §1 总表与 §5 处置顺序同步更新。
>
> **被评方案（本评审对象）在本会话内的变更（供对照）**
> - **v1（380 行）**：初版——10 个「机制型」Skill、`research.qc` 单点质检、无 5 阶段拆分。
> - **v2（481 行）**：按「深度研究团队」专家团升级——新增 §0.3 参考取舍表；§3.3 改为 **6 角色 Skill** 并对齐 prompt 契约；§3.4 改为 **5 阶段执行图**（含「大纲确认」「交付终审」2 个人工闸门）；§3.5 改为 **6 维审查 + 4 条硬性退回条件**；新增 §3.10 研究参数卡 / §3.11 成员超时降级 / §3.12 路由与执行模式；§4 表名与 `round` 维度对齐；§7 复用映射 15→18 行；§8 分期重写。
> - ⚠️ **本评审结论针对 v2（481 行）**；v1 未评审，不得引用。
>
> **待办**：F1–F6 待修（只改方案文档，不动代码）；F8 为流程性要求（实施 P0 前重读当时 HEAD）。

---

## 1. 总体结论

方案的方向、边界、能力复用结论**成立且经得起核验**（§3 事实核验矩阵 17/19 通过）。问题集中在**「平台机制能力边界」的假设**上：3 处断言与代码实况不符，其中 1 处会导致核心流程（评审回路）无法按方案实现。

| 级别 | 编号 | 问题 | 必须修 |
|---|---|---|---|
| 🔴 阻断 | F1 | `ExecutionGraph` 是**无环 DAG 且无条件边** → §3.4「评审回路由条件边实现」不成立 | ✅ 进 P0 前 |
| 🟠 高 | F2 | §9 门禁清单漏 3 处；其中「Makefile session 计数」的判断**方向性错误** | ✅ 进 P0 前 |
| 🟠 高 | F3 | §4「复用既有表」清单 2 个表名错（1 个表根本不存在） | ✅ 进 P0 前 |
| 🟡 中 | F4 | §3.12 把 `ModeSelector` 与「单动作直调」混为一谈 | ✅ 建议修 |
| 🟡 中 | F5 | `enable_loop_fingerprint` **默认关**，方案未点明需显式开启 | ✅ 建议修 |
| 🟡 中 | F6 | §3.9 把「设计约定」写成「门禁要求」（身份装配）——且该处置已被并行工作（身份门卫 6/6 / P13）推进 | ✅ 建议修 |
| 🟠 高 | F8 | **跨会话并发改动**：工作区有另一会话在途改门禁/身份装配 ⇒ §9 与 §3.9 的「当时 HEAD」口径有时效性 | ✅ 实施前重读 |
| 🟢 低 | F7 | 3 项未决（新表命名前缀、`make eval` 纳入否、迁移编号规则） | 记录即可 |

---

## 2. 事实核验矩阵（逐条回源）

> 判定口径：✅ 通过（与代码一致）／❌ 不成立（与代码矛盾）／⚠️ 部分成立（需限定）

| # | 方案断言 | 核验证据 | 判定 |
|---|---|---|---|
| 1 | `human_task` 已 WIRED（2026-10-15），三段链齐 | `human_task.py` docstring「STATUS: WIRED（2026-10-15）」；`protocol.py` `__awaitable__` 分支含 `kind="human"` 分派 | ✅ |
| 2 | `ExecutionStatus` 有 `WAITING_HUMAN` | `execution_status.py:34` `WAITING_HUMAN = "waiting_human"` | ✅ |
| 3 | `Skill` 有 `timeout_ms` / `effect_contract` / `input_schema` / `output_schema` | `skills/registry.py` `Skill` dataclass 全字段在位 | ✅ |
| 4 | `SkillKind` 四型 + `ExecutionBoundary` 三值 | `registry.py:31-53` | ✅ |
| 5 | 生产 FastAPI 必须经 `build_api_app`（P2 门禁） | `agent_core/guardrails/app_factory.py`；`lint_architecture.py` `_FASTAPI_PATTERN` 扫 `applications/**` | ✅ |
| 6 | `sse_pack` 在 shared-schemas | `shared_schemas/sse.py` | ✅ |
| 7 | `StreamEvent` 类型含 `suspended` | `protocol.py:44` | ✅ |
| 8 | `serialize_stream_event` 可复用 | `protocol.py:788` | ✅ |
| 9 | `PlannerRuntime` 可注入 `human_task_store` / `awaitable_task_store` | `protocol.py:376-440` | ✅ |
| 10 | 平台支持把 LangGraph 静态图包成 Workflow Skill | `skills/dag.py:as_dag_skill()` docstring：「内部执行静态 DAG（如 LangGraph 静态图 graph.astream 全链路）」 | ✅（**此条是 F1 的解药**） |
| 11 | **`ExecutionGraph` 支持条件边 / 回路** | `execution_graph.py`：`GraphCycleError`、`detect_cycle()`、`topological_layers()`；`GraphNode` 字段仅 `node_id/skill_name/kwargs/input_refs`（**无条件/谓词字段**）；`add_edge` 自环即抛错；`graph_compose.py:109` LLM 产环即 `GraphComposeError` | ❌ **不成立** |
| 12 | §4「复用既有表」清单 | 见 F3 详述 | ❌ 部分名错 |
| 13 | 单动作直调「经 `ModeSelector` 走 deterministic 单路由」 | `ModeSelector` 是**决策期选范式**；实际消费点仅 `applications/agent_server/planners/unified.py`（`planner == "auto"` 时启用，否则作 force override） | ❌ 定位不准 |
| 14 | 循环/语义指纹护栏可用 | `docs/architecture/complete-agent-runtime-architecture.md:702`：✅ 已实现（**默认关闭**） | ⚠️ 需显式开启 |
| 15 | 身份中间件「必须挂载」 | `ARCHITECTURE.md §5`：**目前仅覆盖 2/6 应用，是已登记技术债，无门禁** | ⚠️ 是设计约定，非门禁 |
| 16 | 仓库 `origin` 为 PUBLIC | `gh repo view` → `visibility: PUBLIC` | ✅ |
| 17 | P4-2 门禁白名单硬编码各应用 `tests/` 目录 | `lint_architecture.py` `_WHITELIST`（含 6 个 `applications/*/tests/`） | ✅（**方案漏登记**） |
| 18 | 根 `pyproject.toml` 需加 members + sources | `[tool.uv.workspace].members` 8 项 / `[tool.uv.sources]` 含 `agent-federation-app` | ✅ |
| 19 | k8s 需改 | `deploy/k8s/20-agent-platform.yaml` **只部署单个 `agent-platform`:8000**，不枚举应用 | ✅ **无需改动**（方案未声明，建议显式写出以免后人误改） |

---

## 3. 问题详述

### F1 🔴 阻断级｜`ExecutionGraph` 无环、无条件边 —— 评审回路无法按方案实现

**方案原文（§3.4）**：「章节评审回路：`draft → review → revise → review` 由条件边实现」「两个人工闸门…条件边」。

**代码实况**（三处独立证据）：

| 证据 | 位置 | 内容 |
|---|---|---|
| 图会拒绝环 | `planner/execution_graph.py:123,182` | `class GraphCycleError(ValueError)`；`detect_cycle()`；`add_edge` 遇自环即抛 |
| 节点无分支语义 | `planner/execution_graph.py:92-121` | `GraphNode` 只有 `node_id / skill_name / kwargs / input_refs` —— **没有条件谓词、没有 when/if 字段** |
| 组合期也拒环 | `planner/graph_compose.py:109` | `raise GraphComposeError("LLM 产出的 Graph 存在循环依赖")` |

图模型是 **分层 DAG**（`topological_layers()`，同层 `asyncio.gather` 并行），因此：
- **不能**表达「按 review 结果决定回退到 revise」这种数据依赖分支；
- **不能**表达 `review ⇄ revise` 的循环。

**影响**：P0/P1 的执行图定义**从根上写不出来**；且这不是措辞问题——是「平台没有这个能力」被当成了有。

**修复建议（推荐 A）**：

> **A. 把「逐章 + 评审回路」整体封装为一个 LangGraph 静态图，经 `as_dag_skill()` 注册为 WORKFLOW Skill**

- Phase 3 内部（`draft → review → 条件回退 revise → 复审`）用 LangGraph **静态图**表达（LangGraph 本身支持条件边与有界循环）；
- 经 `skills/dag.py:as_dag_skill("research.section_loop", ...)` 暴露为 `SkillKind.WORKFLOW`，对调用方是黑盒（只见 Skill 契约）；
- 外层 `ExecutionGraph` 只表达 5 阶段，**天然无环**：`scout → outline → outline_gate → section_loop → framework → publish → publish_gate`；
- **此形态平台已明确支持**：`as_dag_skill` docstring 即写明「内部执行静态 DAG（如 LangGraph 静态图 `graph.astream` 全链路）」；`kefu-service` 的 3 个 Flow 子图（order/logistics/postsale）用的就是同一手法。

**备选 B（不推荐）**：在 `ExecutionGraph` 里**静态展开** 3 轮（`review1 → revise1 → review2 → revise2 → review3`）。可行但节点冗余、可读性差、且「第 3 轮强制 PASS」的语义只能靠节点入参 hack 表达。

**备选 C（不推荐）**：整段走 `mode="agentic"`（AgenticPlanner 自主循环 + `skill_guard`）。丢失静态可读性与确定性，与 §3.2「稳定业务流程不该让 LLM 每次重规划」的既定判断自相矛盾。

---

### F2 🟠 高级｜§9 门禁清单漏 3 处，且「Makefile session 计数」判断方向错误

**（a）漏登记：`scripts/lint_architecture.py` 的 `_WHITELIST`（P4-2 门禁）**

`_WHITELIST` 硬编码了 6 个 `applications/*/tests/` 目录。规则是「除白名单外，任何 `registry.execute(` / `get_registry().execute(` 调用即 CI 失败」。新应用的测试若直接执行 Skill（正常写法），会命中 P4-2 → **CI 红**。→ §9 须增加一条：`_WHITELIST` 登记 `applications/deep_research/tests/`。

**（b）漏登记：根 `pyproject.toml` 的 `[tool.ruff.lint.per-file-ignores]` 按应用路径硬编码**（现 104–110 行）。新代码不应有盲捕获（棘轮），但若确有 legacy，需逐文件登记——§9 应点明这个落点。

**（c）判断方向错误：Makefile session 计数**

方案 §9 第 2/3 条写「新增 session（9 标准 → 10）→ AGENTS.md 计数必须同步，否则 CI 红」。**实核后不成立**：

```
check_doc_sync.check_session_count()  ← scripts/check_doc_sync.py:302-335
  mk_sessions = Makefile 的 test: 目标下、以 "\tuv run pytest " 开头的行数
```

- 现 Makefile `test:` 目标共 10 条 pytest，但第 10 条是 `uv run --extra otel pytest …`，**不匹配前缀** ⇒ `mk_sessions = 9`；
- AGENTS.md 同时声明两处：`9 session pytest（根 / …）` 与 `10 个 pytest session` ⇒ `declared = {9, 10}`；
- 判据是 `mk_sessions not in declared` ⇒ `9 ∈ {9,10}` 通过。

⇒ **再加 1 个 session 得 10，仍在 `{9,10}` 内 → 仍绿**；加到 11 才红。
⇒ 正确表述应为：**「加 1 个 session 不破门禁；但 AGENTS.md 的『9 session pytest（根 / shared-schemas / …）』枚举会变成事实性陈述错误，需同步文字」**——这是文档准确性问题，不是门禁问题。原方案把它写成阻断项，会让实施者去做一件非必需的事，同时**忽略真正会红的两处（a）（b）**。

**（d）应显式声明「k8s 不需要动」**：`deploy/k8s/20-agent-platform.yaml` 只部署单应用（`:8000`），不枚举 applications。方案未提，建议写明以免后人误改。

---

### F3 🟠 高级｜§4「复用既有表」清单 2 处名错（1 个表不存在）

方案 §4 末行：「复用平台既有表：`execution_queue` / `rate_limit_buckets` / `cost_records` / `trajectory` / `awaitable_tasks`」。

| 方案写法 | 实况 | 判定 |
|---|---|---|
| `rate_limit_buckets` | **全仓 `.sql` / `.py` 均无此表**（仅 `applications/knowledge-service/tests/unit/test_security_guards.py` 出现过该字样） | ❌ **不存在** |
| `trajectory` | 实为 **`trajectories`**（`trajectory/store_pg.py:43` `table: str = "trajectories"`） | ❌ 名字错 |
| `execution_queue` / `cost_records` / `awaitable_tasks` | 均在 `migrations/001_baseline.up.sql` | ✅ |

**另核为真但方案未列**：`execution_checkpoints`、`execution_status`（durable 状态机）、`memories`、`episodic_memories`、`procedural_memories`、`chunks`、`sql_ddl`。

**附带缺口**：方案未定**迁移编号规则**。实核 `migrations/` 现有最大编号 **012** ⇒ 本应用新建迁移应从 **013** 起（`agent_runtime/migrations/` + `runner.py`）。

---

### F4 🟡 中级｜§3.12 混淆 `ModeSelector` 与「单动作直调」

- `ModeSelector` 的职责是**决策期选执行范式**（`ExecutionMode`: deterministic/workflow/graph/agentic），且**唯一生产消费点是** `applications/agent_server/planners/unified.py`（`settings.planner == "auto"` 时启用；其余值为 force override）。
- 「单动作直调」（如「查查 X」）在平台里的正确载体是 **`Plan(mode="deterministic", route=<skill_name>)`** ——走 `execute_plan` 的单 route 分支，**不经** ModeSelector。

修复：§3.12 拆成两条独立说明——「范式选择：可选装配 `ModeSelector`（auto 模式）」与「单动作直调：`Plan(mode='deterministic', route=...)`」。

---

### F5 🟡 中级｜`enable_loop_fingerprint` 默认关闭，方案未点明

`docs/architecture/complete-agent-runtime-architecture.md:702` 明载「Skill → Skill 运行时循环 / 语义指纹 ✅ 已实现（**默认关闭**）」。方案 §3.4 提到该护栏可用，但未说明必须 `PlannerRuntime(enable_loop_fingerprint=True)` 才生效——**漏写会让循环保护静默失效**，且属于「已实现 ≠ 已接线」的同一类坑。

---

### F6 🟡 中级｜§3.9 把「设计约定」写成「门禁要求」——**且该结论已被并行工作推进**

`ARCHITECTURE.md §5` 明确登记：「身份中间件未覆盖全部应用（§2.3 的『全局装配』层目前只覆盖 **2/6**）…处置：切换前须先把三个应用纳入同一装配，再加一条不变量」。即：**HEAD 上确实没有对应门禁**。

方案 §3.9 写「`IdentityMiddleware` **必须**挂载」，读起来像既有强制门禁。应改为：「**设计约定**：本应用主动挂载，避免成为第 7 个未覆盖应用」。

> ⚠️ **但本条的处置建议需与并行工作对齐（2026-10-16 当时复核）**：本仓有另一会话正在实施「身份门卫 6/6 覆盖」（工作区可见未提交产物：`packages/agent-runtime/agent_runtime/identity_assembly.py`、`docs/plans/plan-identity-gate-6of6-2026-10-16.md`）。其方案第 1 节写明将新增 **存在性门禁（漏装即 CI 失败，与 #12 的 L-5 同族）**，并把「启动守卫 + 中间件 + 档位留痕」收敛为一次调用 `identity_assembly`。
> ⇒ 正确表述应为：**「本应用经共享装配点 `identity_assembly` 装配（而非各自手写挂载），并按届时已落地的 P13 存在性门禁要求接入」**。若按旧写法自称「必须挂载」并手写挂载代码，待 P13 落地后反而可能不合规（共享装配点才是唯一被门禁承认的形态）。
> 该并行工作未提交，**不得在方案中当作既成事实引用**；实施 P0 前应重读一次当时 HEAD。

---

### F8 🟠 高级｜跨会话并发改动的协调风险（本轮实见）

本轮 `git status` 观察到**工作区存在另一会话的在途改动**（`identity_middleware.py` 被改、新增 `identity_assembly.py` 与 `plan-identity-gate-6of6-2026-10-16.md`；更早一轮还出现过 `scripts/ha_real_kill_verify.py` / `tests/test_ha_kill_script_gate.py`）。

**影响**：本方案的 §9「门禁影响清单」与 §3.9「身份装配」两节**依赖当时 HEAD 的门禁形态**；若在并发会话提交 P13 之后再实施 P0，两节口径均已过期。

**建议**：
1. 实施 P0 前**重新实读一次 HEAD**（尤其 `scripts/lint_architecture.py` 的门禁编号与 `identity_assembly` 是否已入库），不沿用本文档快照；
2. 本方案与评审报告**均不得声称「当前门禁为 N 条」**——ARCHITECTURE.md 已自述计数口径易错（15 行表 / 14 条打印 / 16 个实现函数），叠加并发改动后更不可引用固定数字；
3. 提交本方案时，用 pathspec 限定只提交本方案与评审两份文件（本仓为多会话混合工作区，**禁 `git add -A` / `git add .`**）。

---

### F7 🟢 低级｜3 项未决（记录，不阻断）

1. **新表命名前缀未定**：现有平台表（`memories` / `chunks` / `execution_queue`）**无应用前缀**。方案默认跟随（`research_*` 自带域前缀，够用），建议在 §4 明写理由，避免后人反复讨论。
2. **`make eval` 是否纳入**：方案 §8 P3 提了评测 golden，但未定是否挂进 `Makefile` 的 eval 目标（现 eval 目标只覆盖 agent_server 启发式 + knowledge-service 检索消融）。
3. **§6.2 DTO 命名**与 `shared-schemas` 既有风格（`QueryRequest/QueryResponse`）一致 ✅，无异议。

---

## 4. 未核项（诚实边界）

- `payload_externalization` / `execution_recovery` 的**具体接线难度**未评估（方案已声明「未接线」，本轮未深入）；
- `graph_compose.py` 的 LLM 组合路径**是否可用于深研的场景**未评估（本方案定的是静态图，不依赖它）;
- 新应用的**租户隔离行为级回归**（`tests/ha/test_tenant_isolation_real_pg.py` 形态）需 PG，本轮未实跑。

---

## 5. 建议处置顺序

```
① 修 F1（§3.2/§3.3/§3.4 重写：section_loop 改为 as_dag_skill 包 LangGraph 静态图）
② 修 F2（§9 补 3 处落点 + 改写 session 计数表述 + 声明 k8s 不需改）
③ 修 F3（§4 表名修正 + 迁移从 013 起）
④ 修 F4/F5/F6（表述与默认值口径；F6 按并行 P13 口径改写）
⑤ 【实施 P0 前】重读当时 HEAD（F8：并发会话可能已改门禁/身份装配，本文档快照即过期）
⑥ 复核通过 → 才进入 P0 骨架
```

**一句话**：方案的**方向对、边界对、复用结论对**；错的是**对「平台图模型能力」的 3 处假设**——其中最贵的一处（ExecutionGraph 无环无条件边）会导致评审回路写不出来，必须先改成 `as_dag_skill` + LangGraph 静态图。另有 1 类**流程性风险**（并发会话在改门禁），要求实施前重读 HEAD。
