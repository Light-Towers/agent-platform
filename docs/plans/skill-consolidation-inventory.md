# P0 现状盘点：能力清单 + 缺口 + Executor 映射

> **创建时间**：2026-09-23
> **目标**：将 7 个烟囱应用收敛为 Codex/Cursor 式 agentic 能力组合平台

## 一、SkillRegistry 现有注册（agent_server）

| # | name | SkillKind | 来源 | 注册条件 |
|---|------|-----------|------|----------|
| 1 | `search` | FUNCTION | `capabilities.py:155` | 始终 |
| 2 | `rag` | FUNCTION | `capabilities.py:163` | 始终 |
| 3 | `sql` | FUNCTION | `capabilities.py:171` | 始终 |
| 4 | `mcp` | FUNCTION | `capabilities.py:179` | 始终 |
| 5 | `general_qa` | WORKFLOW(DAG) | `capabilities.py:186` | graph 注入时 |
| 6 | `code_execution` | SANDBOX | `main.py:296` | 始终 |
| 7 | `agentic` | AGENT | `main.py:304` | entry_points 可用时 |
| 8+ | MCP 工具们 | REMOTE | `main.py:289` | mcp_manager 非 None |
| 9+ | Workflow YAML | WORKFLOW | `main.py:276` | discover_workflows |

**Planner 选择**：`PLANNER` env → `deterministic` / `graph` / `agentic` / `auto`(UnifiedPlanner)

## 二、7 应用能力清单 + Executor 映射

### 1. agent_server（统一入口 — 已有 skill）

| 能力 | 现状 | 拟 Executor | 备注 |
|------|------|-------------|------|
| search | ✅ 已注册 FUNCTION | — | `search_web(query)` |
| rag | ✅ 已注册 FUNCTION | — | `rag_query(query, workspace_id)` |
| sql | ✅ 已注册 FUNCTION | — | `sql_query(query)` — 本地 pgvector text-to-SQL |
| mcp | ✅ 已注册 FUNCTION | — | `mcp_query(state, manager)` |
| general_qa | ✅ 已注册 WORKFLOW | — | LangGraph DAG |
| code_execution | ✅ 已注册 SANDBOX | — | Docker/subprocess |
| agentic | ✅ 已注册 AGENT | — | AgenticPlanner.to_skill() |

### 2. agent_federation（编排层 — 降级为 agentic executor 提供方）

| 能力 | 现状 | 拟 Executor | 备注 |
|------|------|-------------|------|
| _execute_agent_core | ✅ 经 entry_points 注入 AgenticPlanner | — | deepagents 深度 agent |
| 文件工具(3个) | bridge 注册（默认关） | FUNCTION | generate_markdown/convert_md_to_pdf/read_file_content |
| 3 子 agent | bridge 注册（默认关） | FUNCTION | database_query/network_search/knowledge_base |
| 沙箱 | bridge 注册（默认关） | SANDBOX | as_sandbox_skill() |

**收敛方向**：agent_federation 降为 agentic executor 提供方（entry_points），编排统一到 agent_server。

### 3. knowledge-service（重服务 → RemoteExecutor）

| 能力 | HTTP 端点 | 拟 Skill name | 拟 Executor | invoke 签名 |
|------|-----------|---------------|------------|-------------|
| 知识库问答 | POST `/query` | `knowledge_query` | REMOTE | `httpx.post(url+"/query", json=kwargs)` |
| 纯检索 | POST `/api/v1/retrieve` | `knowledge_retrieve` | REMOTE | `httpx.post(url+"/api/v1/retrieve", json=kwargs)` |
| 文档导入 | POST `/upload` | `knowledge_upload` | REMOTE | multipart upload |
| 会话历史 | GET `/history/{id}` | — | — | 辅助，不注册为 skill |

**缺口**：❌ 未注册到 agent_server SkillRegistry

### 4. nl2sql-service（重服务 → RemoteExecutor）

| 能力 | HTTP 端点 | 拟 Skill name | 拟 Executor | invoke 签名 |
|------|-----------|---------------|------------|-------------|
| Text-to-SQL | POST `/api/query` | `nl2sql_query` | REMOTE | `httpx.post(url+"/api/query", json=kwargs)` |

**缺口**：❌ 未注册到 agent_server SkillRegistry（agent_server 有本地 `sql` skill，但 nl2sql-service 是独立重服务，能力更强）

### 5. kefu-service（客服 → RemoteExecutor）

| 能力 | HTTP 端点 | 拟 Skill name | 拟 Executor | invoke 签名 |
|------|-----------|---------------|------------|-------------|
| 客服问答 | POST `/invoke` | `kefu_query` | REMOTE | `httpx.post(url+"/invoke", json=kwargs)` |
| legacy 消息 | POST `/api/messages` | — | — | 兼容入口，不注册 |

**缺口**：❌ 未注册到 agent_server SkillRegistry

### 6. dialogue-framework（孤儿框架）

| 能力 | HTTP 端点 | 拟 Skill name | 拟 Executor |
|------|-----------|---------------|------------|
| 对话系统 | POST `/query` | `dialogue` | REMOTE（若保留）|

**现状**：不被任何应用消费，不消费任何应用。独立框架。
**决策**：**P3 评估去留**——kefu-service 已独立实现客服，dialogue-framework 未被复用。
**P3 决策（2026-09-23）**：**暂保留，记为后续评估**。理由：(1) dialogue-framework 是完整对话系统框架（9 命令 + Policy + Tracker + NLG），kefu-service 虽独立实现但功能子集；(2) 删除前需确认无外部消费方（当前仓库内无引用，但可能有外部部署）；(3) 不阻塞收敛——agent_server 不依赖 dialogue-framework。

### 7. exhibition-agent（会展 Agent → skill 提供者）

| 能力 | 现状 | 拟 Skill name | 拟 Executor |
|------|------|---------------|------------|
| 场馆排期查询 | BaseSkill | `venue_schedule_query` | FUNCTION（调 warehouse REST）|
| 数据分析 | BaseSkill（调 nl2sql-service） | `data_analysis_query` | FUNCTION（HTTP 调 nl2sql）|
| skill_loader 48 端点 | LLM tool calling | — | exhibition-agent 自有机制，不强行收编 |

**缺口**：❌ 2 个 Skill 未注册到 agent_server SkillRegistry

## 三、缺口清单

| # | 缺口 | 优先级 | Executor | P 阶段 |
|---|------|--------|----------|--------|
| G1 | knowledge-service 未注册为 RemoteExecutor skill | P1 | REMOTE | P1 |
| G2 | nl2sql-service 未注册为 RemoteExecutor skill | P1 | REMOTE | P1 |
| G3 | kefu-service 未注册为 RemoteExecutor skill | P3 | REMOTE | P3 |
| G4 | exhibition-agent 2 skill 未注册 | P2 | FUNCTION | P2 |
| G5 | dialogue-framework 孤儿，去留未决 | P3 | — | P3 |
| G6 | agent_federation 编排层与 agent_server 重叠 | P5 | — | P5 |

## 四、Executor 类型映射表

| 能力 | Executor | 理由 |
|------|----------|------|
| knowledge_query / knowledge_retrieve | REMOTE | 重依赖(torch/Milvus/Neo4j)，HTTP 隔离 |
| knowledge_upload | REMOTE | 同上 |
| nl2sql_query | REMOTE | 重依赖(pgvector/元知识)，HTTP 隔离 |
| kefu_query | REMOTE | 独立服务，HTTP 调用 |
| venue_schedule_query | FUNCTION | 轻量，调 warehouse REST（已有 httpx） |
| data_analysis_query | FUNCTION | 轻量，HTTP 调 nl2sql-service |
| dialogue | REMOTE（若保留） | 独立服务 |
| search / rag / sql / mcp | FUNCTION（已注册） | 进程内 |
| code_execution | SANDBOX（已注册） | Docker/subprocess |
| agentic | AGENT（已注册） | AgenticPlanner |

## 五、跨应用消费关系

```
agent_federation ──> kefu-service(:8003 /invoke)
                 ──> nl2sql-service(:8000 /api/query)
                 ──> knowledge-service(:8900 /query + /api/v1/retrieve)

exhibition-agent ──> nl2sql-service(:8000 /api/query)
                 ──> warehouse REST (external)

knowledge-service ──import──> exhibition-agent.foundation.knowledge_lifecycle [反向依赖]

dialogue-framework: 孤岛，无消费关系
```
