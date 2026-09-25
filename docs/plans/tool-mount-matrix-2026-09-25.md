# 批 0 产出：Tool 挂载矩阵 + 前置盘点结论

> 归属：[plan-tool-instrumentation-choke-point-2026-09-25.md](plan-tool-instrumentation-choke-point-2026-09-25.md) v3 §5 批 0。
> 日期：2026-09-25 · 方法：只读 grep/read，未动任何生产代码。
> 作用域：`applications/agent_federation`（agent_server 侧 SkillRegistry 接入另立批 1 任务）。

## 1. 工具 × 挂载路径矩阵（11 个 @tool 全量）

路径代号：**MA**=main_agent.py:30-33 静态列表 · **REG**=tool_registry TOOL_REGISTRY（get_tools_for_roles 动态）· **SUB**=agent/subagents/* 直引 · **BR**=planners/agentic_runtime_bridge.py:141-143 直引 · **DEAD**=无生产挂载。执行形态：**A**=async（原生或经 @with_timeout 异步包装）/ **S**=sync。

| 工具 | 源文件 | MA | REG | SUB | BR | 形态 | 挂载数 |
|---|---|---|---|---|---|---|---|
| generate_markdown | markdown_tools | ✅ | ✅(files) | — | ✅ | S | **3 重** |
| convert_md_to_pdf | pdf_tools | ✅ | ✅(files) | — | ✅ | A(超时) | **3 重** |
| read_file_content | upload_file_read_tool | ✅ | ✅(files/data/search/knowledge) | — | ✅ | S | **3 重** |
| execute_sql_query | db_tools | — | ✅(data) | ✅ db_query | — | A(超时) | **2 重** |
| get_table_data | db_tools | — | — | ✅ db_query | — | A(超时) | 1 |
| list_sql_tables | db_tools | — | — | ✅ db_query | — | A(超时) | 1 |
| zhiku_retrieve | zhiku_tools | — | ✅(knowledge) | ✅ kb_agent | — | A(超时) | **2 重** |
| internet_search | tavily_tool | — | ✅(search) | ✅ search_agent | — | A(超时) | **2 重** |
| execute_python_code | code_execution_tool | ✅(沙箱开关) | ✅(code，LLM 不可自选) | — | — | A | 2 |
| get_assistant_list | ragflow_tools | — | — | — | — | S | **0（死代码）** |
| create_ask_delete | ragflow_tools | — | — | — | — | S | **0（死代码）** |

**关键结论**：
1. **三重挂载 3 个、双重挂载 4 个**——"只包 `_resolve`"将使 7/11 工具至少一条路径无事件；C1 的严重性高于评审估计（评审只点了双重 1 例）。
2. **SUB 路径是生产主路径**：三个 subagent 经 `main_agent.py:24-26` import + `config.py:93-95` 模块路径注册（remote/local 子 Agent 定位）双通道生效，非边缘路径。
3. **形态分布**：A×7（原生 async 1 + @with_timeout 异步包装 6）、S×4——包装必须双路覆盖，且 6 个"同步内核 + 异步外壳"工具的包装层级要落在 with_timeout **内侧**（见 §3）。

## 2. ragflow_tools 死代码确认

- 全仓 `grep -rn "ragflow"`：仅 `rawflow/chat_assistant_demo.py`（自建 `ragflow_sdk.RAGFlow` 客户端 + 本文件内自定义函数），**无任何位置 import `tools/ragflow_tools`**；
- 结论：`get_assistant_list` / `create_ask_delete` 为死埋点。**处置：批 2 直接删除该文件**（其 @tool 无消费者，删除无行为影响；Git 历史可回溯）。

## 3. eval 基线现状

- `evaluation/` 目录仅含 golden.jsonl（输入集）与脚本，**无已存 baseline 快照文件**（`save_baseline()` 由 run-all/run_eval 运行时生成）；
- 处置：批 2 改口径前，先跑一次当前代码录制 baseline 快照留底（否则"口径变更前基线"无从对比）。

## 4. 下游 tool_name / 事件消费方审计

| 消费方 | 消费内容 | 影响 | 处置 |
|---|---|---|---|
| `evaluation/run_eval.py:32,47-51,187` | `tool_outcome` 的 tool_name/outcome/error_class，"工具四分类"统计 | success 新增 + 名称映射 → 统计口径变 | 批 2 同步更新 + 首录基线 |
| WS 前端（仓库外） | WebSocketSink 直推 `monitor_event`（含中文 tool_name） | 名称变英文 / args 变摘要 → 前端展示与聚合 | **需人工确认前端消费逻辑**（前端仓库不在本仓） |
| Langfuse 看板 | OTLP span 属性 / 事件流按名聚合 | 同上 | 看板侧改名或依赖 display_name 映射 |
| agent_server evidence 流 | `deterministic.py:191` StreamEvent(type="evidence") | **仅 agent_server 桥接链存在**，federation 无此链（grep 无 monitor.on/evidence 消费） | §7.5 影响面收窄为 agent_server |

## 5. §7.4 定板建议：桥接工具包装层级

`agentic_runtime_bridge` 动态工具（StructuredTool.from_function）本质是 **Skill 的 langchain 化外壳**：其调用经 `RuntimeToolCaller → runtime.delegate → SkillRegistry`（架构验收 #4"不绕过 Skill Runtime"）。**建议：不在 bridge 层包装**——事件由 SkillRegistry 侧 middleware（agent_server 接入点）统一产生；bridge 层包装会造成 Skill 执行 + 外壳调用**双重事件**。federation 本地工具（tools/*）不受此影响（不经 delegate）。

## 6. 遗留确认项（人工）

1. WS 前端仓库对 tool_name 的展示/聚合逻辑（仓外，需人工看一眼）；
2. `check_zhiku_health`（api/server.py:72 引用）非 @tool，不入矩阵——确认无需事件化；
3. `execute_python_code` 挂载于 `SANDBOX_TOOL_ENABLED` 开关之后——包装后需验证开关关闭时零事件（应自然成立，工具未挂载即无调用）。
