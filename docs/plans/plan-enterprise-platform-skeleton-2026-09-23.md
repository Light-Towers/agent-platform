# 企业级智能平台骨架方案（已被取代）

> 创建日期：2026-09-23
> 状态：**已被取代** — 见 `docs/architecture/agent-execution-platform.md`
> 取代原因：本方案提议 Application 互相 import，违反 ARCHITECTURE.md 红线 2；且"torch 已替代"判断不准确（knowledge-service 仍依赖 torch/transformers/flagembedding）；"有状态=Agent"边界定义不够准确（应为"谁决定下一步"）
> 定位：企业级智能平台 — 单进程 + 插件式能力模块 + 外部基础设施

---

## 1. 问题诊断

### 1.1 当前架构的问题

当前是**多服务微服务式**：agent_server + knowledge-service + nl2sql-service + kefu-service + exhibition-agent 各自独立进程，HTTP 通信。

**核心问题：把"业务逻辑"和"基础设施"都当成了"独立服务"。**

- knowledge-service 的代码是「检索 → rerank → 生成」的业务流程，不是基础设施
- 把业务逻辑独立部署，多了一层 HTTP 跳转、多了一套部署运维
- 真正重的依赖（Milvus/Neo4j/torch）中：
  - **pymilvus**：轻量客户端，连远程 Milvus server，不是重依赖
  - **neo4j driver**：同理，轻量客户端
  - **torch**：只有 local embedding 需要，已用 SiliconFlow API 替代
- "重依赖隔离"的理由**不成立**

### 1.2 能力层命名混淆

当前 SkillRegistry 混合注册了 4 种 SkillKind（FUNCTION/WORKFLOW/AGENT/REMOTE），但它们语义不同：

| 类型 | 实际语义 | 有状态 | 有内部流程 | 类比 |
|------|---------|--------|-----------|------|
| FUNCTION | 原子工具 | 否 | 否 | Codex 的 read_file / bash |
| REMOTE（重量服务） | 子 Agent | 是（Milvus/Neo4j/对话历史） | 是（检索→rerank→生成） | Codex 的 code-reviewer |
| WORKFLOW | 子 Agent（固定流程） | 是 | 是（多步但路径确定） | — |
| AGENT | 子 Agent（agentic loop） | 是 | 是（LLM 驱动多步） | — |

混在一个 registry 里靠 SkillKind 区分，概念模糊。

### 1.3 双重状态管理

编排层（agent_server）维护对话历史，子 Agent（knowledge-service）内部也维护——双重状态管理。如果承认是子 Agent，这是 multi-agent 的标准模式（各管各的状态空间）；如果不承认，就是 bug。

---

## 2. 目标架构

### 2.1 分层

```
┌─────────────────────────────────────────────────┐
│  入口层  FastAPI :8000                           │
│  agent_server（平台单进程）                       │
├─────────────────────────────────────────────────┤
│  编排层  Planner（可插拔）                        │
│  AgenticPlanner / DeterministicPlanner           │
│  → 决定调子 Agent 还是 Tool，怎么组合             │
├─────────────────────────────────────────────────┤
│  运行时中间件层  agent-runtime                    │
│  admission / coordinator / cache / circuit_breaker│
│  tracing / sandbox / mcp_client                  │
├─────────────────────────────────────────────────┤
│  子 Agent 层（有状态 · 有内部流程 · 委托任务）     │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐         │
│  │knowledge │ │ nl2sql   │ │ kefu     │         │
│  │ Milvus   │ │ pgvector │ │ LangGraph│         │
│  │ Neo4j    │ │          │ │          │         │
│  └──────────┘ └──────────┘ └──────────┘         │
│  ┌──────────┐ ┌──────────┐                      │
│  │exhibition│ │general_qa│                      │
│  └──────────┘ └──────────┘                      │
│  → 插件式 import，进程内调用，非 HTTP             │
│  → 各自管理状态空间（multi-agent 标准模式）        │
├─────────────────────────────────────────────────┤
│  Tool 层（无状态 · 原子调用 · 传参拿结果）         │
│  search / rag / sql / mcp                        │
│  → FunctionExecutor，轻量内联                     │
├─────────────────────────────────────────────────┤
│  内核层  agent-core（零依赖）                     │
│  tracing / llm / memory / resilience / events    │
├─────────────────────────────────────────────────┤
│  契约层  shared-schemas                          │
│  QueryRequest / QueryResponse / ThreadState       │
└─────────────────────────────────────────────────┘

外部基础设施（独立部署，像数据库一样）：
  Milvus（向量库）  Neo4j（图谱）  MySQL（关系数据）  pgvector
```

### 2.2 部署拓扑

```
                    负载均衡器（nginx / traefik）
                   /     |     \
            实例1   实例2   实例3      ← 每个实例都是完整的 agent_server
              |       |       |
           共享外部基础设施
     Milvus / Neo4j / MySQL / pgvector / LLM API
```

- **1 个平台进程**（可水平扩展多实例）替代当前 5 个应用进程
- 扩容从 N×M（N 服务 × M 实例）→ 1×M
- 基础设施独立部署，与平台进程解耦

### 2.3 并发模型

```
agent_server 进程（1 个线程，1 个 asyncio 事件循环）
│
├── 用户 A 请求 → async task A
│   └── Planner 决定调 knowledge 子 Agent
│       └── await knowledge.query(messages)    ← 普通函数调用，不 spawn
│           └── await milvus.search(...)        ← I/O，yield 让出
│           └── await llm.chat(...)             ← I/O，yield 让出
│
├── 用户 B 请求 → async task B
│   └── Planner 决定调 nl2sql 子 Agent
│       └── await nl2sql.query(messages)        ← 普通函数调用，不 spawn
│           └── await pgvector.query(...)       ← I/O，yield 让出
│
└── 事件循环调度：A yield 时 B 执行，B yield 时 A 执行
```

- FastAPI + asyncio 天然支持多用户并发
- 能力模块操作全是 I/O 密集（查 Milvus / 调 LLM / 查 Neo4j），asyncio 在 I/O 等待时 yield
- 连接池管资源竞争（Milvus max_connections）
- 熔断管故障隔离（模块出错不拖垮进程）
- 每个用户是独立 async task，有自己的对话上下文和执行状态
- 共享进程内存空间，但对话历史在 DB 不在内存（不互相污染）

### 2.4 子 Agent 运行时模型

**子 Agent 既不是独立进程也不是线程——它是带状态的 async 函数。**

动态创建子 Agent = 创建一个 async task + 独立执行上下文，不 spawn 进程/线程：

```python
# Planner 动态决定创建子 Agent
agent = SubAgentRegistry.get("knowledge")           # 选/实例化
ctx = ExecutionContext(messages=..., session_id=...) # 独立上下文
result = await agent.run(ctx)                        # async 调用，不 spawn
```

并发调多个子 Agent（如并行查知识库 + 生成 SQL）：

```python
results = await asyncio.gather(
    knowledge_agent.run(ctx1),    # task A
    nl2sql_agent.run(ctx2),       # task B
)
# 同一事件循环里并发，不创建进程/线程
```

**什么时候才真的需要进程/线程？**

| 场景 | 解法 | 原因 |
|------|------|------|
| CPU 密集（local embedding/rerank） | `asyncio.to_thread()` | 阻塞事件循环 |
| 执行用户代码（sandbox） | 子进程 | 安全隔离 |
| 子 Agent 业务流程（检索/LLM/DB） | **都不需要** | 全是 I/O，asyncio 够 |

动态创建的代价是一个 Python 对象 + 一个 async task，不是 fork 一个进程。

---

## 3. 子 Agent vs Tool 的区分

| 维度 | 子 Agent | Tool |
|------|---------|------|
| 状态 | 有（Milvus/Neo4j/对话历史） | 无 |
| 内部流程 | 有（检索→rerank→生成等多步） | 无（原子） |
| 调用语义 | 委托任务，它自己决定怎么做 | 传参数，拿结果 |
| 注册方式 | SubAgentRegistry | ToolRegistry |
| 执行器 | 进程内 import 调用 | FunctionExecutor |
| 类比 | Codex 的 code-reviewer 子 agent | Codex 的 read_file / bash |

### 当前能力归类

**子 Agent**（有状态、有内部流程）：
- knowledge_query（Milvus + Neo4j + 对话历史 + 检索→rerank→生成）
- nl2sql_query（pgvector + SQL 生成流程）
- kefu_chat（LangGraph 状态机 + 对话历史）
- exhibition_query（仓储 REST + 多轮 tool calling）
- general_qa（固定流程子 Agent）

**Tool**（无状态、原子调用）：
- search（搜索）
- rag（检索增强生成，原子）
- sql（SQL 执行，原子）
- mcp（MCP 协议调用，原子）

---

## 4. 迁移策略

### 4.1 从多服务 → 单进程插件式

| 步骤 | 内容 | 风险 |
|------|------|------|
| S1 | knowledge-service 业务逻辑提取为可 import 的模块包 | 低（代码搬迁） |
| S2 | nl2sql-service 同上 | 低 |
| S3 | kefu-service 同上 | 低 |
| S4 | exhibition-agent 同上 | 低 |
| S5 | agent_server 注册子 Agent（进程内 import）替代 RemoteExecutor HTTP | 中（路由/中间件适配） |
| S6 | 删除独立服务的 Dockerfile / 部署配置 | 低 |
| S7 | 验证：全量测试 + 并发压测 | — |

### 4.2 从混合 SkillRegistry → SubAgentRegistry + ToolRegistry

| 步骤 | 内容 | 风险 |
|------|------|------|
| R1 | SkillRegistry 拆分为 SubAgentRegistry + ToolRegistry | 中 |
| R2 | 子 Agent 注册走 SubAgentRegistry（有状态、有流程） | 低 |
| R3 | Tool 注册走 ToolRegistry（无状态、原子） | 低 |
| R4 | Planner 路由区分：调子 Agent（委托）vs 调 Tool（传参） | 中 |
| R5 | 验证：编排层测试 + eval | — |

### 4.3 保留不变

- agent-core（内核层，零依赖，不动）
- agent-runtime（运行时中间件，不动）
- shared-schemas（契约层，不动）
- 外部基础设施（Milvus/Neo4j/MySQL/pgvector，本来就是独立部署）

---

## 5. 验收标准

1. **部署**：从 5 个应用进程 → 1 个平台进程 + 外部基础设施
2. **并发**：单进程 asyncio 支撑多用户并发，I/O 不阻塞
3. **扩容**：多实例 + 负载均衡，1×M 扩容
4. **分层清晰**：子 Agent（有状态）和 Tool（无状态）分开注册、分开路由
5. **测试全绿**：现有 1691 测试不退化
6. **eval 不退化**：15/15 = 100%

---

## 6. 与现有代码的关系

### 保留
- `packages/agent-core/` — 内核层，不动
- `packages/agent-runtime/` — 运行时中间件，不动（SkillRegistry 拆分在此层）
- `packages/shared-schemas/` — 契约层，不动
- `applications/agent_server/` — 平台进程，增强（注册子 Agent 替代 RemoteExecutor）

### 改造
- `applications/knowledge-service/` → 业务逻辑提取为可 import 模块，不再独立部署
- `applications/nl2sql-service/` → 同上
- `applications/kefu-service/` → 同上
- `applications/exhibition-agent/` → 同上

### 删除
- 各独立服务的 Dockerfile / docker-compose 服务条目 / 独立部署脚本
- RemoteExecutor HTTP 调用路径（改为进程内 import 调用）

---

## 7. 技术债与后续

本骨架方案落地后，原有技术债 D7/D9 仍需推进，但可在新结构内顺带处理：
- **D7**（87 处裸 except）：在新结构内逐文件收窄
- **D9**（exhibition llm_client.py 收敛）：exhibition 改为进程内模块后，LLM 客户端收敛更自然

新增技术债（骨架迁移产生）：
- 子 Agent 进程内调用的异常隔离边界（熔断/超时配置）
- 连接池统一管理（Milvus/Neo4j/pgvector 各自连接池配置）
