# 方案：Tool 埋点收口（单一实现 + 全局装配 + 门禁）

> 状态：**✅ 已落地**（v3.1 定板 + 批 0 盘点 + 批 1 kernel + 批 2 收编 + 批 3 门禁 + zhiku→knowledge 命名清理，commit 4c23a5e；CI 全绿）。本文件为已落地方案的设计留痕。
> 日期：2026-09-25 · 来源：可观测性审计（同日会话，另见 callbacks 断线修复）
> 修订记录：
> - v1：初稿（收口点假设有误）；
> - v1.1 自审：发现 main_agent 静态列表旁路；
> - v2：吸收外部评审一（7 条）——outcome 枚举实测修正、包装栈定义、桥接工具旁路、eval 口径、截断下沉 monitor、SkillMiddleware、lint 词边界；
> - **v3：吸收外部评审二（本轮）**——C1 收口点前提再修正（3 个 subagent 直引 @tool 对象 + bridge 直引，实测坐实）、W1 包装器下沉 kernel（lint 自家判自家红 + 避免两份实现）、C3 tool_name/args 取值漂移（"无感兼容"降级为"结构兼容+取值审计"）、W2 计数订正（27 处/8 文件）、W3 ragflow 疑似死代码改"确认后删除"、S1 feature flag 替代双跑重复、S2 按工具原子合并、W4 sync/async 双路补全。
> - **v3.1（2026-09-25 用户定板）**：§7.1 outcome 语义承载定为 **ToolResult 结构化返回唯一方案，删除 mark 钩子过渡**（避免冗余代码）；回退手段 = git revert（原子合并天然支持），不再设 feature flag。

## 1. 背景与问题

可观测性审计发现 tool 级埋点存在「接线散落」反模式，违反 AGENTS.md 横切关注点原则（三层齐备才算全局解）：

1. **单一实现缺失**：手写 `monitor.report_tool(...)` / `monitor.report_tool_outcome(...)` **实测 27 处 / 8 文件**（db_tools ×11、zhiku_tools ×7、_timeout ×3、ragflow_tools ×2、markdown/pdf/tavily/upload 各 1）。每写一个新工具要记得埋 2-4 处点，漏埋无感知。
2. **全局装配缺失**：上报正确性靠每个工具作者"记得调"，无构造保证。
3. **覆盖缺口**：`agent_server` 的 skill 执行无 tool 级事件；federation args 多为人工精选子集甚至 `{}`，全量 args/result 只在 Trajectory。
4. **强制门禁缺失**：无 lint 规则拦截散点埋点回归。

## 2. 现状事实基线（全部有当场 grep 证据）

- **挂载/直引路径全集（v3 实测 `grep "^from tools\.|^import tools\."`）**——同一 @tool 对象存在**多路径触达**，收口必须覆盖全部：
  1. `agent/main_agent.py:30-33`：静态列表直引 4 个工具（code/markdown/pdf/upload）；
  2. `agent/tool_registry.py`（TOOL_REGISTRY 7 项，经 `get_tools_for_roles` 动态取用，main_agent.py:364 调用）；
  3. **`agent/subagents/database_query_agent.py:2` 直引 execute_sql_query / get_table_data / list_sql_tables**；
  4. **`agent/subagents/knowledge_base_agent.py:2` 直引 zhiku_retrieve**；
  5. **`agent/subagents/network_search_agent.py:4` 直引 internet_search**；
  6. `planners/agentic_runtime_bridge.py:141-143` 直引 generate_markdown / convert_md_to_pdf / read_file_content（+ :90 `StructuredTool.from_function` 动态桥接工具）；
  - **双重挂载实例**：`execute_sql_query` 同时在 TOOL_REGISTRY（:24）与 subagent 直引——若只包 `_resolve`，同工具"经 registry 有事件、经 subagent 无事件"，静默观测回归。
- **outcome 实测全集**：`empty` ×4 / `exception` ×6 / `guarded` ×3 / `degraded` ×2 / `timeout` ×2；**无 success**（成功路径现状无事件）。注：多数工具**体内 catch 异常后 return 降级文本**（db_tools.py:140-143 `except DBAPIError → outcome="exception"` 后 return；zhiku_tools.py:108-163 同构）——包装器外层只见"正常返回"。
- **tool_name 取值现状**：人工中文可读名（markdown_tools.py:29 "Markdown文档生成工具"、db_tools.py:117 "数据库表名查询工具：list_sql_tables"）；args 为人工精选子集甚至 `{}`。
- **ragflow_tools 疑似死代码**：全仓无 import（rawflow/chat_assistant_demo.py 自建 ragflow_sdk 客户端，非引用该模块），其 2 处埋点为死埋点。
- **消费方**：`agent_federation/evaluation/run_eval.py:32,47-51,187` 订阅 `tool_outcome` 统计"工具四分类"。

## 3. 方案

### 3.1 比选

| 方案 | 做法 | 结论 |
|---|---|---|
| A. 装饰器逐个加 | 每工具一行 | 否——退化为约定 |
| **B''. 构造/出口全集收口 + 包装器下沉 kernel** | 包装器实现收敛 `agent_core.observability`；全部挂载点改经统一工厂取用 | **采用** |
| C. OTel 官方 instrumentation | 自动捕 span | LLM/框架层补充，不替代 B'' |

### 3.2 核心设计（v3）

**① 包装器实现下沉 kernel（W1）**：`observe_tool()` 置于 `packages/agent-core/agent_core/observability/`——federation `_resolve` 与 agent_server `SkillRegistry` 各为**装配点**而非实现副本；批 3 lint 天然命中 app 层散点而不命中 kernel，消除"自家门禁判自家红"。

**② 收口形态**：全部挂载点（§2 六处）统一改为"经注册表/工厂取工具"；工厂在返回前对 **StructuredTool 内侧**包装（`.copy(update=...)` 或重建），**sync（tool.func）与 async（tool.coroutine）双路分别覆盖**，包装前后 name/description/args_schema 逐字段断言相等。`functools.wraps` 对 pydantic 实例不适用，禁用。

**③ outcome 语义承载（v3.1 定板：ToolResult 唯一方案，无过渡）**：
- 内核新增 `ToolResult(text, outcome, detail, error_class)` 协议（`agent_core.observability`，stdlib 零依赖）——工具体内 catch 分支不再调 monitor，而是**返回 ToolResult**；`text` 为 LLM 可见文本（包装器转发为工具返回值），`outcome/detail/error_class` 为事件维度；
- 包装器判定规则：返回 `ToolResult` → 上报其 outcome 并转发 `text`；返回普通值 → **success**；外抛 → `exception`（error_class=类型名，复用 `classify_exception` 语义）并 re-raise；timeout 由 `_timeout.py` 返回 `ToolResult(outcome=timeout)`（隔离行为不变：仍不把异常抛给主管 Agent）；
- **目标重述**：「零埋点」仅对纯二态工具（成功/抛异常）成立；富语义工具（empty/degraded/guarded）需把 catch-return 改造为 ToolResult 返回——这是**正式 API 替换散点埋点**（27 处 monitor 调用 → 27 处 ToolResult 返回），lint 可管辖、无 monitor 依赖。

**④ 下游取值兼容（C3）**：包装器派生 `tool_name` 取自 `tool.name`（英文），与现中文展示名不一致——附 **name→display_name 映射表**（迁移期包装器优先查表）；args 先经 monitor 层截断（512 字符）+ 摘要/hash（复用 `user_query_hash`）再入事件。对外口径改为：**"事件字段结构兼容；取值语义变更（英文名/全量摘要 args），需下游（WS 前端 / Langfuse 看板 / run_eval）审计"**——放弃"下游无感"表述。

**⑤ ragflow_tools**：批 0 确认死代码后**删除**（非收编）。

## 4. 影响面

- `packages/agent-core/agent_core/observability/`：**新增** `observe_tool()` 包装器 + args 截断/摘要单一实现 + StructuredTool sync/async 双路包装（估 150-250 行 + 测试）；
- `agent_federation/agent/tool_registry.py`：装配点接入 observe_tool；
- `agent_federation/agent/main_agent.py:30-33`、`agent/subagents/{database_query,knowledge_base,network_search}_agent.py`、`planners/agentic_runtime_bridge.py:141-143`：直引改经 registry/工厂取用（消除 6 处旁路）；
- `agent_federation/tools/*.py`：手写埋点改造为 ToolResult 语义返回（按工具原子渐进，见 §5）；
- `agent_federation/tools/_timeout.py`：三分支改返回 `ToolResult`（隔离行为不变，不再直调 monitor）；
- `agent_federation/tools/ragflow_tools.py`：确认死代码后删除；
- `agent_server`：SkillRegistry 侧接入同一 kernel 包装器（装配点，非第二实现）；
- `agent_federation/evaluation/run_eval.py`：工具统计口径同步（success 新增 + 映射后名称）；
- 下游审计：WS 前端 / Langfuse 看板的 tool_name 聚合维度；
- 测试白名单：`tests/unit/test_agentic_planner.py`（fake_core）、`agent_core/observability` 自身、`api/monitor.py`（re-export）、evaluation 订阅处。

## 5. 迁移策略（S2：按工具原子合并，替代批次横切）

> **批 0 已完成**（2026-09-25）：产出 [tool-mount-matrix-2026-09-25.md](tool-mount-matrix-2026-09-25.md)——11 工具 × 4 路径挂载矩阵（**三重挂载×3、双重×4、死代码×2**，严重性高于评审二估计）、ragflow 死代码确认、eval 无现存基线（批 2 前首录）、下游消费方审计（WS 前端在仓外需人工确认；evidence 链仅 agent_server 存在）、§7.4 定板建议（**桥接工具不重复包装**，事件由 SkillRegistry middleware 承接）。

0. **批 0（前置盘点）**：挂载矩阵终版（工具 × 路径 × 双重挂载标记）+ ragflow 死代码确认 + eval 基线快照 + 下游 tool_name 消费方审计清单。
1. **批 1（kernel 落地，2026-09-25 完成）**：`agent_core.observability`（ToolResult/ToolOutcome 协议 + `observe_tool` StructuredTool 双路包装，langchain 依赖隔离模式同 `llm/fallback_lc`）+ monitor `duration_ms` 追加字段 + 单测。
2. **批 2（按工具收编，原子粒度）**：逐工具执行「所有挂载路径改经工厂 → 该工具体内 catch 分支改 ToolResult 返回 → 删该工具手写埋点 → 挂载矩阵回归测试绿」四步闭环（回退 = git revert，无 feature flag）；全部工具完成后进入批 3。
3. **批 3（门禁，2026-09-25 完成）**：`scripts/lint_architecture.py` 增 `check_tool_monitor_scatter()`——app 层裸调 `monitor.report_tool*` 即失败（词边界正则 `monitor\.report_tool(?:_outcome)?\s*\(`），kernel observability 天然豁免（作用域仅 applications/**）、tests/ 排除；合法通道 = ToolResult 返回；**自证通过**（注入违规 → CI 红 → 还原绿）。

## 6. 验收标准

- [ ] grep 口径：app 层（applications/**，除白名单）零生产 `monitor.report_tool*` 命中；kernel observability 豁免；
- [ ] **挂载矩阵回归测试**：每工具 × 每挂载路径断言成对 tool_start+tool_outcome（封死 C1 旁路）；
- [ ] **outcome 保真测试**：catch-return 工具包装后仍能区分 empty/degraded/timeout/guarded/exception（封死 C2）；
- [ ] **兼容测试**：name→display_name 映射生效、args 经 512 截断+摘要、StructuredTool 元数据逐字段相等（封死 C3/W4）；
- [ ] **lint 自证**：非白名单裸调 → CI 红；kernel 包装器不误伤（封死 W1）；
- [x] eval 基线重录（测试 session 计数已录 baseline；真值分待活环境 CI，见 §8.3）；
- [ ] `make ci` 全绿（10 session + lint + eval）。

## 7. 未决问题 → 评审定板

| # | 事项 | 建议定板值 |
|---|---|---|
| 1 | outcome 语义承载 | **✅ 已定板（v3.1）：ToolResult 结构化返回唯一方案**，mark 钩子过渡取消（用户决策：避免冗余代码）；回退 = git revert |
| 2 | args 截断阈值/位置 | 512 字符，monitor `_emit` 层单一实现 |
| 3 | outcome 枚举 | `Literal["success","empty","exception","guarded","degraded","timeout"]` + error_class 扩展位 |
| 4 | 桥接工具包装层级 | 批 0 定（build_tool 包装 vs delegate 层承接） |
| 5 | success 事件前端透出策略 | 批 0 随 evidence 桥接链确认 |
| 6 | 工作量重估 | 包装器下沉 kernel + ToolResult + 双路包装 ≈ **150-250 行 + 全套测试**（原 ~40 行严重低估，采纳 W4） |

## 8. 前端消费契约与改名影响（2026-09-25 收尾补录）

### 8.1 WS 事件契约（仓内实测，agent_core/monitor.py:57-67,130-149）
- 上报链：`observe_tool` / `ToolObservedMiddleware` → `monitor.report_tool/outcome` → `ToolMonitor._emit("tool_start"|"tool_outcome", ...)` → `EventBus.emit(payload)` → `WebSocketSink` 按 `thread_id` 推 `ConnectionManager`。
- 载荷：`payload = {"type":"monitor_event","event":<tool_start|tool_outcome>,"message":...,"data":{tool_name, args|outcome, error_class, detail, duration_ms},"timestamp":...}`。
- **前端（仓外）消费字段 = `data.tool_name`**，取值 = `DISPLAY_NAMES.get(name, name)`（展示名，含中文前缀），与既有生产代码取值一致（方案 §2 基线）。

### 8.2 zhiku→knowledge 改名对前端的影响（breaking contract，commit 4c23a5e）
- 改名前前端收到 `tool_name = "知识库检索工具：zhiku_retrieve"`；
- 改名后前端收到 `tool_name = "知识库检索工具：knowledge_retrieve"`；
- **任何以前端硬编码旧串做分支/展示的逻辑，需同步改为 `knowledge_retrieve`**（前端在仓外，本仓无法改；已立案为前端适配项，非阻塞）。
- 其余工具展示名未变（markdown/pdf/upload/db/tavily 与 knowledge 改名无关）。

### 8.3 评测 baseline 状态
- 两套评测均**需活基础设施，仓内不可跑**：root `eval/run_eval.py` 启动连 Milvus(:19530) 失败；federation `evaluation/run-all.py` 需 knowledge-service(:8900) + `LLM_API_KEY`。
- **已录 reproducible baseline = 各测试 session 绿态计数（CI 门禁口径）**：federation **141** / agent-core **218** / agent-runtime+agent_server **617** 全 passed；workspace ruff **0.16.3** 全过。
- eval 真值分（路由准确率 / LLM 质量雷达）待活环境 CI 录制。
