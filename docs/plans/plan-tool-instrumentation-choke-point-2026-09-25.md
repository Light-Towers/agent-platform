# 方案：Tool 埋点收口（单一实现 + 全局装配 + 门禁）

> 状态：**v2 修订稿，待评审**（未动代码）。按 AGENTS.md「所有代码优化/重构必须先制定方案」红线立项。
> 日期：2026-09-25 · 来源：可观测性审计（同日会话，另见 callbacks 断线修复）
> 修订记录：v1 自审修正收口点假设（B'）；**v2 吸收外部评审 7 条建议**——修正 outcome 枚举事实错误、补包装栈定义、收口点扩为全集、新增 outcome 覆写钩子、eval 基线同步、截断下沉 monitor 层。v1 的三处事实错误（收口点假设 / outcome 枚举 / 异常路径可达性）已全部实测修正。

## 1. 背景与问题

可观测性审计发现 tool 级埋点存在「接线散落」反模式，违反 AGENTS.md 横切关注点原则（三层齐备才算全局解）：

1. **单一实现缺失**：`agent_federation/tools/` 约 **30 处**手写 `monitor.report_tool(...)` / `monitor.report_tool_outcome(...)`（db_tools / zhiku_tools / ragflow_tools / tavily_tool / pdf_tools / markdown_tools / upload_file_read_tool / _timeout.py 等 ~12 个文件）。每写一个新工具要记得埋 2-4 处点，漏埋无感知。
2. **全局装配缺失**：事件虽经 `EventBus → OTelSpanSink → OTLP → Langfuse` 可达后端，但上报的正确性靠每个工具作者"记得调"，无构造保证。
3. **覆盖缺口**：`agent_server` 的 tool/skill 执行完全无 tool 级事件；federation 的 args 多为摘要（部分传 `{}`），全量 args/result 只在 Trajectory。
4. **强制门禁缺失**：无 lint 规则拦截未来新工具继续手写散点埋点。

## 2. 现状事实基线（v2 实测，方案全部决策以此为据）

- **outcome 实测全集**（生产代码）：`empty` ×4 / `exception` ×6 / `guarded` ×3 / `degraded` ×2 / `timeout` ×2。**无 success、无 error**（v1 所写 "error" 实为 exception、漏 guarded）。
- **成功路径现状无 outcome 事件**：`_timeout.py` docstring 自述"正常不发事件，success 由调用方或 runner 补"——该补报机制未见实现。引入 success 是**从无到有**的新增语义，非口径漂移。
- **异常被吞（阻塞级事实）**：`_timeout.py:36-53` 把 TimeoutError / ValueError / Exception 全部转为错误字符串返回、不外抛。**包装器若只能看到"正常返回"，任何基于异常的 error 上报路径都走不通**——分支语义必须显式承载（见 §3.2）。
- **挂载路径全集（批 0 盘点前已知 3 条 + 1 条未知）**：
  1. `main_agent.py:271` 静态列表直接 import 工具对象（默认主 Agent 工具集）；
  2. `tool_registry.get_tools_for_roles()`（动态角色，main_agent.py:364）；
  3. `planners/agentic_runtime_bridge.py:90 build_bridged_langchain_tools()`：StructuredTool.from_function 动态构建桥接工具，**完全绕开 registry**（经 RuntimeToolCaller → runtime.delegate 治理）；
  4. `ragflow_tools` 2 工具不在 TOOL_REGISTRY（埋点却在 ragflow_tools.py:31,69）——挂载路径未知，批 0 盘点。
- **消费方**：`agent_federation/evaluation/run_eval.py:32,47-51,187` 直接订阅 `tool_outcome` 统计"工具四分类"（注意：是 federation 的 evaluation/，非根 eval/）。

## 3. 方案

### 3.1 比选

| 方案 | 做法 | 优点 | 缺点 | 结论 |
|---|---|---|---|---|
| A. 装饰器 `@tool_observed(name=)` | 每个 tool 函数加一行装饰器 | 显式、可读 | 仍需逐个记得加（退化为约定） | 否 |
| **B'. 工具构造出口全集收口** | 所有挂载路径统一经一个 `build_tool()` 工厂取用并 wrap | 构造保证不可漏接 | 需先完成挂载面盘点 | **采用** |
| C. OTel 官方 instrumentation | 自动捕 tool run | 零代码 | OTel span 而非业务事件（WS 前端拿不到）；覆盖受第三方包限制 | LLM/框架层补充，不替代 B' |

### 3.2 核心设计

**包装栈（自外向内，v2 明确定义）**：

```
@tool → build_tool() 包装器 → [原装饰链：with_timeout 等] → 裸函数
```

- 包装器在**最外层**产生 `tool_start`（含 args 摘要），调用结束后产生 `tool_outcome`；
- **outcome 判定优先级**：分支覆写 > 异常分类 > 默认 success：
  1. **分支覆写钩子**（R1 核心）：提供 contextvar `tool_ctx.mark("degraded" | "empty" | "guarded")`——工具函数体内遇到业务分支时标记，包装器结束时优先采用覆写值。这给 empty/degraded/guarded 这类"正常返回但非成功"的分支语义一条**正式表达通道**；
  2. `_timeout.py` 改造为覆写钩子的第一个使用方：其 timeout/guarded/exception 分支从"直接调 monitor"改为"标记 tool_ctx"（上报动作统一收归包装器）；
  3. 未覆写且调用外抛 → `report_tool_outcome(exception, error_class=classify_exception(exc).value)`（复用 `agent_core.resilience.ErrorClass`）；
  4. 默认 → success。
- **langchain 工具元数据保留**：`_resolve` 返回的是 `@tool` 产物（StructuredTool，pydantic 实例）。包装不得替换 StructuredTool 外壳——对 `_run` / `coroutine` 内侧包装（`StructuredTool` → wrapper → 原装饰链 → fn），或以 `create_model` 重建时透传 args_schema/name/description；单测断言包装前后 `name/description/args_schema` 逐字段相等。

### 3.3 收口点全集（v2 修正：四处，非一处）

| # | 收口点 | 处置 |
|---|---|---|
| 1 | `tool_registry._resolve()` | 统一经 build_tool() 包装 |
| 2 | `main_agent.py:271` 静态列表 | **改为经 tool_registry 取用**（消除旁路；工具定位单一真相源） |
| 3 | `agentic_runtime_bridge.build_bridged_langchain_tools()` | 桥接工具同样经 build_tool() 包装（或在其 RuntimeToolCaller.delegate 层承接——批 0 定） |
| 4 | ragflow_tools 等未在册工具 | 批 0 盘出挂载路径后收编入 registry |

## 4. 影响面

- `applications/agent_federation/agent/tool_registry.py`：新增 `build_tool()` 工厂 + `_resolve` 接入；
- `applications/agent_federation/agent/main_agent.py`：静态工具列表（:271）改经 registry 取用；
- `applications/agent_federation/planners/agentic_runtime_bridge.py`：桥接工具接入包装（归属细节批 0 定）；
- `applications/agent_federation/tools/*.py`：摘除 ~30 处手写埋点（12 文件）；
- `applications/agent_federation/tools/_timeout.py`：三分支改为 tool_ctx 覆写（上报动作收归包装器）；
- `packages/agent-core/agent_core/monitor.py`：**新增** args 截断/脱敏（横切下沉到单一实现，见 §6）+ 事件新增 `duration_ms` 字段（包装器天然可测，向后兼容追加）；
- `applications/agent_federation/evaluation/run_eval.py`：批 2 同步更新工具统计口径（新增 success 类目 + 四分类→新枚举映射）；
- `applications/agent_server`：接入方式改为 **SkillRegistry middleware**（`skills/registry.py:224` 已有洋葱链扩展点，实现为 `ToolObservedMiddleware`，不改 registry 本体）；
- 前端（P2 评估）：agent_server 桥接链 monitor 事件经 evidence StreamEvent 流向前端（deterministic.py:191 出口已核实），success 事件是否透出/如何展示批 0 一并确认；
- 测试白名单：`tests/unit/test_agentic_planner.py`（fake_core 自证）、`api/monitor.py`（re-export 层）、evaluation 订阅处。

## 5. 迁移策略（4 批，每批独立 commit，可独立回滚）

0. **批 0（前置盘点）**：全量挂载面矩阵（tools/ 全部导出 × 全部挂载点，含 ragflow 归属、桥接工具、subagent 工具集归属）+ evidence 前端桥接链确认 + eval 基线快照留底（批 2 对比用）。
1. **批 1（落地不摘除）**：`build_tool()` + tool_ctx 覆写钩子落地；main_agent 静态列表改经 registry；单测（EventBus 断言 start+outcome、覆写优先级、元数据逐字段相等、_timeout 三分支经钩子上报）；手写埋点暂留双跑，事件去重（`instrumented=True` 注册标记）。
2. **批 2（摘除）**：删除 tools/ 全部手写埋点；**eval 口径同步**（run_eval 工具统计纳入 success，基线重录并注明"新增 success 维度"而非漂移修正）。
3. **批 3（门禁）**：`scripts/lint_architecture.py` 增规则——`applications/*/tools/**`、`applications/*/agent/**`、`applications/*/planners/**` 裸调 `monitor.report_tool*` 即失败（**正则词边界**，`report_tool` 是 `report_tool_outcome` 前缀）；放行 `tool_ctx.mark`；白名单：`agent_core/monitor.py`、`api/monitor.py`（re-export）、`tests/`、evaluation 订阅处；计入 `make ci`，自证（故意裸调 → CI 红）。

## 6. 验收标准

- [ ] `grep -rnE "monitor\.report_tool(_outcome)?\(" applications/ --include="*.py"` 仅命中白名单（0 个生产代码命中）；
- [ ] 行为级：单测覆盖四类路径——成功→success、函数内 mark("degraded")→degraded、外抛→exception、_timeout 超时→timeout；EventBus 各采集到 `tool_start` ×1 + `tool_outcome` ×1，data 含 tool_name/outcome/error_class/**duration_ms**；
- [ ] 包装前后 StructuredTool 元数据逐字段相等（name/description/args_schema）；
- [ ] 事件 schema 向后兼容：`monitor_event` 既有字段不变，`duration_ms` 为追加字段；
- [ ] args 截断/脱敏实现在 **monitor 层单一实现**（`_emit` 统一截断 512 字符 + 摘要），不在各包装器重复；
- [ ] eval 基线重录完成，run_eval 工具统计含 success 类目且文档注明口径变化；
- [ ] lint 门禁自证通过（词边界正确：`report_tool_outcome` 调用不被 `report_tool` 规则误伤漏网）；
- [ ] `make ci` 全绿（10 个 pytest session + lint + eval）。

## 7. 未决问题 → 评审定板

| # | 事项 | 建议定板值 |
|---|---|---|
| 1 | agent_server skill 侧接入方式 | **SkillMiddleware**（复用现成洋葱链，非改 SkillRegistry 本体） |
| 2 | args 截断阈值与实现位置 | **512 字符，monitor `_emit` 层单一实现** |
| 3 | outcome 枚举 | **Literal["success","empty","exception","guarded","degraded","timeout"]** + `error_class` 保留业务字符串扩展位 |
| 4 | 桥接工具（agentic_runtime_bridge）包装层级 | 批 0 定（build_tool 包装 vs delegate 层承接） |
| 5 | success 事件前端透出策略 | 批 0 随 evidence 桥接链一并确认 |
