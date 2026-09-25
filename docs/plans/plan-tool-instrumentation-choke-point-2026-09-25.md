# 方案：Tool 埋点收口（单一实现 + 全局装配 + 门禁）

> 状态：**待评审**（未动代码）。按 AGENTS.md「所有代码优化/重构必须先制定方案」红线立项。
> 日期：2026-09-25 · 来源：可观测性审计（同日会话，另见 callbacks 断线修复）

## 1. 背景与问题

可观测性审计发现 tool 级埋点存在「接线散落」反模式，违反 AGENTS.md 横切关注点原则（三层齐备才算全局解）：

1. **单一实现缺失**：`agent_federation/tools/` 约 **30 处**手写 `monitor.report_tool(...)` / `monitor.report_tool_outcome(...)`（db_tools / zhiku_tools / ragflow_tools / tavily_tool / pdf_tools / markdown_tools / upload_file_read_tool / _timeout.py 等 ~12 个文件）。每写一个新工具要记得埋 2-4 处点，漏埋无感知。
2. **全局装配缺失**：事件虽经 `EventBus → OTelSpanSink → OTLP → Langfuse` 可达后端，但上报的正确性靠每个工具作者"记得调"，无构造保证。
3. **覆盖缺口**：`agent_server` 的 tool/skill 执行完全无 tool 级事件；federation 的 args 多为摘要（部分传 `{}`），全量 args/result 只在 Trajectory。
4. **强制门禁缺失**：无 lint 规则拦截未来新工具继续手写散点埋点。

## 2. 目标

- 新增/改造 tool **零埋点**：tool 级 `tool_start` / `tool_outcome` 事件由统一包装器自动产生；
- 事件 schema 兼容：`monitor_event` 载荷（type/event/message/data）不变，下游 WS / OTel sink / 测试回调无感；
- 摘除 federation tools/ 全部手写埋点（grep 零命中 + 白名单）；
- lint 门禁拦截回归（裸调 `monitor.report_tool` 即 CI 失败）。

## 3. 方案比选

| 方案 | 做法 | 优点 | 缺点 | 结论 |
|---|---|---|---|---|
| A. 装饰器 `@tool_observed(name=)` | 每个 tool 函数加一行装饰器 | 显式、可读 | 仍需逐个记得加（退化为约定） | 否 |
| **B. 注册器/执行器收口** | 在 tool 注册处（`tool_registry` / `SkillRegistry.register`）统一 wrap | 构造保证不可漏接，新工具零改动 | 包装层需透传函数元数据（name/doc） | **采用** |
| C. OTel 官方 instrumentation | langchain/community instrumentation 自动捕 tool run | 零代码 | 语义是 OTel span 而非业务事件（WS 前端拿不到）；覆盖面受第三方包限制 | 作为 LLM/框架层补充，不替代 B |

**推荐 B'（2026-09-25 自审修正）**：原假设"tool_registry 是唯一收口点"**不成立**——实测存在两条挂载路径：
1. `main_agent.py:271` **静态列表**直接 import 工具对象（`[generate_markdown, convert_md_to_pdf, read_file_content]`，默认主 Agent 工具集走这条路），不经 tool_registry；
2. `tool_registry.get_tools_for_roles()`（动态角色模式，main_agent.py:364 调用）；
3. `ragflow_tools`（get_assistant_list / create_ask_delete）**未见于 TOOL_REGISTRY**，挂载路径未盘点——批 1 动工前必须先完成全量挂载面盘点。

因此收口分两步：**先把 main_agent 静态列表改为经 tool_registry 取用**（工具定位单一真相源），再在 `_resolve()` 解析处统一 wrap（`observed(fn)` 包装器：进入 report_tool、正常返回 report_tool_outcome(success)、异常 report_tool_outcome(error, error_class=classify_exception(exc).value)，复用 `agent_core.resilience.ErrorClass`，配合现有 `_timeout.py` 超时语义）。包装 langchain `@tool` 对象时必须保留 name/description/args_schema 元数据（否则 LLM 看到的工具签名变化）。

## 4. 影响面

- `applications/agent_federation/agent/tool_registry.py`：改造为**唯一工具出口**（`_resolve` 统一 wrap，~40 行）；
- `applications/agent_federation/agent/main_agent.py`：静态工具列表（:271）改为经 tool_registry 取用（消除旁路）；
- `applications/agent_federation/tools/*.py`：摘除 ~30 处手写埋点（12 文件）；
- `applications/agent_federation/tools/_timeout.py`：outcome 上报迁入包装器（超时/成功/异常三态）；
- **挂载面盘点（批 1 前置）**：确认 ragflow_tools 等未注册工具的实际挂载路径并收编入 registry；
- `packages/agent-core/agent_core/monitor.py`：不动（事件 API 保持稳定）；`report_tool_outcome` 增加 `error_class` 透传已支持；
- `applications/agent_server`：P2 阶段评估接入（其 skill 经 `agent_runtime` SkillRegistry 执行，天然有第二个收口点）；
- 测试：`tests/unit/test_agentic_planner.py` 中 2 处测试内直调 `monitor.report_tool` 属测试自证，移入白名单。

## 5. 迁移策略（3 批，每批独立 commit，可独立回滚）

0. **批 0（前置盘点）**：全量挂载面盘点——枚举 tools/ 全部导出工具 × 实际挂载点（main_agent 静态 / get_tools_for_roles / 其他未知路径如 ragflow_tools），产出挂载矩阵，杜绝批 1 漏包。
1. **批 1（落地不摘除）**：main_agent 静态列表改经 registry 取用；`_resolve` 处实现 `observed()` 包装器 + 单测（EventBus 采集断言：一次调用产生 tool_start + tool_outcome 且 data 字段齐全；langchain 工具元数据 name/description/args_schema 不变）；手写埋点暂留，双跑验证事件不重复（注册元数据标记 `instrumented=True`，或接受短期重复、批 2 立即摘除）。
2. **批 2（摘除）**：删除 tools/ 全部手写埋点；核对 `tool_outcome` 的 outcome 取值集合（success/empty/degraded/error/timeout）与既有监控消费方兼容。
3. **批 3（门禁）**：`scripts/lint_architecture.py` 增规则——`applications/*/tools/**` 与 `applications/*/agent/**` 中裸调 `monitor.report_tool` 即失败（白名单：agent_core/monitor.py 自身、tests/）；计入 `make ci`。

## 6. 验收标准

- [ ] `grep -rn "monitor.report_tool" applications/ --include="*.py"` 仅命中白名单（0 个生产代码命中）；
- [ ] 行为级：单测注册两个 tool（成功/抛错），EventBus 采集到 `tool_start` ×1 + `tool_outcome` ×1，data 含 tool_name/outcome/error_class；
- [ ] 事件 schema 不变：`monitor_event` 载荷字段与现状一致（WS 前端无感）；
- [ ] args 记录遵守脱敏约束（大对象截断/摘要，复用 `user_query_hash` 约定），杜绝把全文塞进事件；
- [ ] lint 门禁规则生效（自证：故意加一处裸调 → CI 红）；
- [ ] `make ci` 全绿（10 个 pytest session + lint + eval）。

## 7. 未决问题（评审时定）

1. agent_server 的 skill 执行是否同步接入（`agent_runtime` SkillRegistry 收口）——建议同批 1 一起做，避免两套收口语义；
2. args 全量记录边界：事件里只放摘要 + 长度/hash（全文在 Trajectory/Langfuse），需明确截断阈值（建议 512 字符）；
3. `tool_outcome` 的 `outcome` 枚举是否收敛为 `Literal` 类型（防字符串漂移）。
