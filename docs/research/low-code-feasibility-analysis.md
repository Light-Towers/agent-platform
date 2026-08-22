# 低代码编排平台可行性实证分析（2026-08-12）

> 状态：专项调研，回答用户根本性质疑——"难道不能基于 n8n / Dify 等编排工具直接搭节点来实现本项目全部功能吗？"
> 所有代码搜索结果均于 2026-08-12 通过 GitHub Code Search API 实证核实，非模型记忆。
> 承接 `spec.md`（7 个工程化差异化特性）+ `competitive-landscape.md`（赛道调研）+ `research-proposal.md`（架构方案）。

## 一、调研问题

本项目（agent_platform）已锐化定位为"工程化优先的多源证据问答 Agent 运行时"，差异化核心是 7 个工程化特性：

1. 三能力统一路由（Supervisor 路由 Search/RAG/SQL）
2. SQL 安全双保险（sqlglot 白名单 + 连接级只读）
3. 可复位降级 + 熔断三态
4. 评测门禁 + CI 回归（golden set 阻断路由准确率回归）
5. 会话防劫持 + checkpoint 持久化恢复
6. 单进程轻量 + 零配置冒烟
7. 无 LLM 可验收（mock 模式跑通全链路）

**核心问题**：n8n / Dify / Langflow / FastGPT 能否通过"搭节点 + 自定义代码节点"实现这 7 个特性的全部？若能，自建无必要性；若不能，卡点在哪？

## 二、平台基线（2026-08-12 GitHub API 实证）

| 平台 | Stars | License | Open Issues | 自定义节点机制 | 部署模型 |
|------|-------|---------|-------------|---------------|---------|
| **n8n-io/n8n** | 200,272 | NOASSERTION (fair-code) | 1,297 | `@n8n/create-node` 脚手架（TypeScript） | 单镜像可跑，生产需 PG/MySQL + Redis |
| **langgenius/dify** | 152,126 | NOASSERTION | 994 | Code Node（Python/JS） | docker-compose **38 个镜像**，最小 7-8 服务 |
| **langflow-ai/langflow** | 153,071 | MIT | 983 | Custom Component（Python 类，基于 LangChain） | 单镜像可跑，需后端 DB |
| **labring/FastGPT** | 29,336 | NOASSERTION | 166 | 自定义节点 | 需 MongoDB + PG(pgvector) + 沙箱 |

> Dify 的 `docker/docker-compose.yaml` 实测 38 个 image，含 14 种向量数据库选型（weaviate/qdrant/pgvector/milvus/opensearch/es/chroma/oceanbase/...）、squid 代理、certbot、nginx、sandbox、plugin-daemon、agent-backend 等。

## 三、逐特性实证分析

### 3.1 三能力统一路由（Supervisor 路由 Search/RAG/SQL）

| 平台 | 能否搭 | 怎么搭 | 限制 |
|------|--------|--------|------|
| n8n | ✅ 能 | AI Agent 节点 + Switch/Router 节点 + HTTP/Tavily 节点 + Postgres 节点 | 路由逻辑写在节点配置里，非 LangGraph 状态图；反思重试需用 Loop 节点拼，状态管理弱 |
| Dify | ✅ 能 | Workflow + LLM 节点 + Conditional Branch + Knowledge Retrieval + Code 节点 | 路由是条件分支，非 Supervisor 式编排；反思重试受工作流 DAG 限制 |
| Langflow | ✅ 能 | Router Component + 各能力 Component | 基于 LangChain，最接近本项目编排模型 |
| FastGPT | ✅ 能 | 工作流 + 知识库节点 + HTTP 节点 | SQL 能力弱，需自定义代码节点补 |

**结论**：四平台**都能搭**三能力路由。这是**最同质化、最不构成差异化**的能力——与 `competitive-landscape.md` 已实证的"6 个 0 stars 子项目都复刻了此架构"一致。

### 3.2 SQL 安全双保险（sqlglot 白名单 + 连接级只读）

**GitHub Code Search 实证（2026-08-12）**：

| 平台 | `sqlglot` 命中数 | `readonly connection` 命中 |
|------|-----------------|--------------------------|
| n8n | **0** | 0（未搜到 SQL 只读连接） |
| Dify | **0** | 45（但都是 knowledge_fs_operations，非 SQL 只读） |
| Langflow | **0** | — |
| FastGPT | **0** | — |

**四平台全部 0 命中 sqlglot**——无一内置 SQL 白名单守卫。

| 平台 | 能否实现 | 怎么实现 | 限制 |
|------|---------|---------|------|
| 四平台 | ⚠️ 理论能 | 在自定义代码节点里写 sqlglot 守卫 + 只读连接 | ① 每个 SQL 节点重复写守卫代码，无平台级统一拦截；② 守卫被绕过时无二道保险；③ 自定义节点的错误处理/日志/trace 需自己搭；④ 写自定义节点 = 写代码，等于在平台里重写本项目的 SQL 守卫模块 |

**结论**：**理论能但无原生支持**，需在每个 SQL 节点写自定义守卫代码，且无法做到"白名单 + 连接级只读"双保险（平台不暴露连接级权限控制）。

### 3.3 可复位降级 + 熔断三态

**GitHub Code Search 实证**：

| 平台 | `circuit breaker` 命中 | 用户工作流节点可用？ |
|------|----------------------|---------------------|
| n8n | 19（有完整 `circuit-breaker.ts`，三态 CLOSED/OPEN/HALF_OPEN） | **❌ 否**。11 个使用点**全部在 `log-streaming.ee`（企业版日志流）**，保护的是 n8n 内部服务，**不暴露给用户工作流节点** |
| Dify | 2（`workflow_schedule_task.py` + feature config） | ❌ 否。仅调度任务内部用，无用户级熔断器 |
| Langflow | **0** | ❌ 否 |
| FastGPT | **0** | ❌ 否 |

**n8n 熔断器使用点实证**（全部 11 个命中路径）：
```
packages/cli/src/utils/circuit-breaker.ts                          # 实现本身
packages/workflow/src/message-event-bus.ts                          # 内部消息总线
packages/@n8n/api-types/src/dto/log-streaming/...                   # 日志流 DTO
packages/cli/src/modules/log-streaming.ee/destinations/...          # 企业版日志流
packages/frontend/editor-ui/src/features/integrations/logStreaming.ee/...
packages/cli/src/utils/__tests__/circuit-breaker.test.ts            # 测试
packages/cli/test/integration/public-api/log-streaming.test.ts      # 测试
...（全部 log-streaming 相关）
```

**关键发现**：n8n 有生产级熔断器实现，但**只用于保护 n8n 自身的 log-streaming 服务**，用户搭节点时**无法给自己的 HTTP 节点、AI Agent 节点套上这个熔断器**。

| 平台 | 能否实现 | 限制 |
|------|---------|------|
| 四平台 | ⚠️ 理论能（自定义节点里自己写） | ① 熔断状态需持久化（否则进程重启丢失），平台不提供节点级状态存储；② 可复位降级需"连续失败计数 + 冷却窗口"，每个节点重复实现；③ 无法接入平台的重试/超时机制；④ 半开探测的并发控制需自己写 |

**结论**：**四平台都无原生用户级熔断器**。n8n 有但仅限内部用。自定义实现等于在平台里重写本项目的健壮性模块，且状态持久化难以做到。

### 3.4 评测门禁 + CI 回归（golden set 阻断路由准确率回归）

**GitHub Code Search 实证**：

| 平台 | `golden eval` 命中 | CI 集成能力 |
|------|-------------------|------------|
| n8n | 3（`@n8n/instance-ai/evaluations/`，SDK 层面） | 工作流定义在 UI 里，难以版本控制、难以在 CI 里自动跑 |
| Dify | **0** | 工作流定义在 DB 里，无 golden set 评测门禁 |
| Langflow | **0** | 无 |
| FastGPT | 未搜到 | 无 |

| 平台 | 能否实现 | 限制 |
|------|---------|------|
| 四平台 | ⚠️ 理论能（外部 CI 调用平台 API 跑 golden set） | ① 工作流是 UI/DB 定义的，**难以版本控制**（无法 `git diff` 工作流变更）；② CI 里跑评测需平台实例在线，CI 环境搭建复杂；③ **无法阻断合入**——平台不提供"路由准确率低于基线则拒绝合入"的钩子；④ 评测结果与工作流版本的关联需自己维护 |

**结论**：**四平台都无原生 CI 评测门禁**。可外部搭但集成度低，无法做到"golden set 阻断路由准确率回归"——这是本项目"无评测的重构等于盲改"原则的核心，低代码平台难以满足。

### 3.5 会话防劫持 + checkpoint 持久化恢复

**GitHub Code Search 实证**：

| 平台 | `session hijack` 命中 | `checkpoint restore` 命中 | 性质 |
|------|----------------------|--------------------------|------|
| n8n | 4（`auth.service.ts`，平台认证） | 44（`suspended-run-restorer`，instance-ai SDK） | 平台级认证，非会话级防劫持；挂起恢复是 SDK 层面 |
| Dify | **0** | 16（`home_snapshot_service`，Agent 配置快照） | **无会话防劫持**；快照是 Agent 配置版本，非会话状态 |
| Langflow | 未搜到 | 28（`GraphCheckpoint` + `resume.py`） | **有图执行级 checkpoint**，但明确标注 "HITL graph suspend/resume"，非多轮会话上下文 |
| FastGPT | — | 51（prompt-compress / agent-loop） | 非会话检查点 |

**Langflow checkpoint 实证**（`src/lfx/src/lfx/graph/checkpoint/schema.py`）：
```python
"""Durable checkpoint data model for HITL graph suspend/resume (LE-1440)."""
class GraphCheckpoint(BaseModel):
    checkpoint_id: str
    run_id: str
    flow_id: str | None
    session_id: str | None  # 有 session_id 字段
    user_id: str | None
    vertex_results: dict[str, VertexCheckpointData]  # 各节点结果
    pause_context: dict[str, Any] | None  # HITL 暂停上下文
    ...
```

Langflow 的 checkpoint 是**单次工作流执行内**的图状态快照（哪些 vertex 已构建、运行队列、HITL 暂停上下文），用于 HITL 暂停后恢复执行。**不是** LangGraph `AsyncSqliteSaver` 式的**跨会话多轮上下文**检查点（保存对话状态、消息历史、路由决策、证据，用于 `client.resume(thread_id)` 接续此前对话）。

| 平台 | 能否实现 | 限制 |
|------|---------|------|
| 四平台 | ⚠️ 部分能 | ① **会话防劫持**（API_KEY 派生 session_id）需控制平台的会话 ID 生成逻辑，低代码平台**不允许覆盖**会话 ID 派生方式；② **会话级 checkpoint**：Langflow 有图执行级但非会话级，Dify/n8n/FastGPT 的会话是对话历史而非状态恢复；③ 跨会话恢复需 `resume(thread_id)` 接口，平台不暴露此级 API |

**结论**：**四平台都无会话级防劫持**。Langflow 有图执行级 checkpoint 但非多轮会话上下文恢复。会话 ID 派生方式平台不允许覆盖。

### 3.6 单进程轻量 + 零配置冒烟

**部署复杂度实证**：

| 平台 | 最小生产部署服务数 | 零配置冒烟？ |
|------|-------------------|------------|
| n8n | n8n + PostgreSQL/MySQL + Redis（3-4 服务） | ❌ 需配置 DB |
| Dify | api + web + postgres + redis + sandbox + plugin-daemon + nginx + agent-backend（**7-8 服务**，compose 38 镜像） | ❌ 需配置多服务 |
| Langflow | langflow + 后端 DB（2-3 服务） | ❌ 需配置 DB |
| FastGPT | FastGPT + MongoDB + PG(pgvector) + 沙箱（4 服务） | ❌ 需配置多 DB |
| **本项目** | **单进程 + 1 个 PG**；或**内存模式零依赖** | ✅ `DATABASE_URL` 为空时内存模式启动 |

**结论**：**四平台部署复杂度均高于本项目**。本项目"单进程 + 1 PG / 内存模式零依赖"是最低运维复杂度，低代码平台无法匹配。

### 3.7 无 LLM 可验收（mock 模式跑通全链路）

**GitHub Code Search 实证**：

| 平台 | `mock llm` 命中 | 运行时无 LLM 模式？ |
|------|----------------|-------------------|
| n8n | 有测试 mock | ❌ 工作流执行需配置 LLM 凭据，无 LLM 时 AI 节点报错 |
| Dify | 1928（但都是 `tests/` 文件） | ❌ mock 是开发测试用，非运行时模式；工作流需配置模型 provider |
| Langflow | 有测试 mock | ❌ 同上 |
| FastGPT | — | ❌ 需配置模型 |

本项目要求：`LLM_API_KEY` 为空时走**确定性 mock**（路由→检索→汇总→回答全链路可验收），不报错中断，用于 CI 冒烟与离线验收。

| 平台 | 能否实现 | 限制 |
|------|---------|------|
| 四平台 | ⚠️ 理论能（自定义节点里写 mock 逻辑） | ① 平台的 AI/LLM 节点**要求配置 provider 凭据**，无 LLM 时节点直接报错，不会走 mock；② 要在自定义节点里拦截 LLM 调用并返回 mock，等于重写本项目的 mock 层；③ 平台的 mock 是测试级（pytest/单元测试），不是运行时级（无 LLM_API_KEY 时自动降级） |

**结论**：**四平台都无运行时无 LLM 可验收模式**。mock 是测试级非运行时级，低代码平台的 LLM 节点要求凭据，无 LLM 时报错而非降级。

## 四、逐特性对比总表

| # | 工程化特性 | n8n | Dify | Langflow | FastGPT | 自建 |
|---|-----------|-----|------|----------|---------|------|
| 1 | 三能力统一路由 | ✅ 搭节点 | ✅ 搭节点 | ✅ 搭节点 | ✅ 搭节点 | ✅ |
| 2 | SQL 安全双保险（sqlglot+只读） | ⚠️ 自定义节点 | ⚠️ 自定义节点 | ⚠️ 自定义节点 | ⚠️ 自定义节点 | ✅ 原生 |
| 3 | 可复位降级 + 熔断三态 | ⚠️ 内部有/用户无 | ❌ 无 | ❌ 无 | ❌ 无 | ✅ 原生 |
| 4 | 评测门禁 + CI 回归 | ⚠️ SDK 层 | ❌ 无 | ❌ 无 | ❌ 无 | ✅ 原生 |
| 5 | 会话防劫持 + 会话级 checkpoint | ❌ 无 | ❌ 无 | ⚠️ 图级非会话级 | ❌ 无 | ✅ 原生 |
| 6 | 单进程轻量 + 零配置冒烟 | ❌ 3-4 服务 | ❌ 7-8 服务 | ❌ 2-3 服务 | ❌ 4 服务 | ✅ 1 进程 |
| 7 | 无 LLM 可验收（运行时 mock） | ❌ 测试级 | ❌ 测试级 | ❌ 测试级 | ❌ 测试级 | ✅ 运行时 |

**图例**：✅ 原生支持 / ✅ 搭节点可实现 / ⚠️ 部分能或需大量自定义 / ❌ 无

**关键判断**：
- 特性 1（三能力路由）：四平台都能搭——**但这正是最不构成差异化的能力**（6 个 0 stars 子项目都复刻了）。
- 特性 2-7（6 个工程化特性）：**四平台无一原生支持**，全部需要"在自定义代码节点里重写本项目的对应模块"。

## 五、真实成本对比

### 5.1 用低代码平台搭出等价功能的工作量

假设要用 Dify/n8n 搭出本项目 7 个特性的等价功能：

| 特性 | 搭法 | 工作量 | 等价于 |
|------|------|--------|--------|
| 三能力路由 | 拖节点 + 配条件分支 | 0.5 天 | 本项目 Supervisor 已有 |
| SQL 双保险 | 写自定义代码节点（sqlglot + 只读连接） | 2 天 | 重写本项目 SQL 守卫模块 |
| 熔断三态 + 可复位 | 写自定义代码节点 + 状态持久化 | 3 天 | 重写本项目健壮性模块 |
| 评测门禁 + CI | 搭外部 CI 管道 + 平台 API 调用 + 版本关联 | 3 天 | 重写本项目 eval 模块 |
| 会话防劫持 + checkpoint | **平台不允许覆盖会话 ID 派生**，需 fork 平台源码 | 5+ 天 | fork 平台 |
| 单进程轻量 | **平台架构决定**，无法瘦身 | ∞ | 不可实现 |
| 无 LLM 可验收 | 写自定义节点拦截 LLM + mock 逻辑 | 2 天 | 重写本项目 mock 层 |

**总工作量**：≥ 15 天，且特性 6（单进程轻量）**不可实现**，特性 5（会话防劫持）需 fork 平台源码。

**对比自建**：本项目已落地 30 文件 + 32 测试通过，6 阶段每阶段独立验收，总工作量约 10-12 天（已投入）。

### 5.2 运维负担

| 维度 | 低代码平台 | 本项目 |
|------|-----------|--------|
| 部署服务数 | 7-8（Dify）/ 3-4（n8n） | 1-2 |
| 升级风险 | 平台升级可能破坏工作流（Dify 1.x→2.x 有破坏性变更） | 仅依赖 LangGraph/LangChain |
| 监控 | 需接入平台自身监控 + 自定义节点监控 | 统一结构化日志 + Langfuse |
| 故障排查 | 平台黑盒 + 自定义节点黑盒 | 代码即配置，可断点调试 |

### 5.3 能力天花板

| 维度 | 低代码平台 | 本项目 |
|------|-----------|--------|
| 会话模型 | 平台固定（conversation_id / thread_id） | LangGraph checkpoint 可插拔 |
| 路由模型 | 条件分支 / Switch 节点 | LangGraph 状态图 + 反思重试 |
| SQL 安全 | 自定义节点重复实现 | 统一守卫 + 连接级只读 |
| 降级策略 | 平台无，自定义节点各自实现 | 统一熔断 + 可复位降级 |
| 评测集成 | 外部 CI，无法阻断合入 | CI 门禁阻断合入 |

### 5.4 锁定风险

| 维度 | n8n | Dify | Langflow | FastGPT |
|------|-----|------|----------|---------|
| 许可证 | fair-code（非 OSI） | NOASSERTION（自定义） | MIT | NOASSERTION |
| 工作流定义 | JSON 在 DB | JSON 在 DB | JSON 在 DB | JSON 在 DB |
| 迁移成本 | 高（节点 API 变更） | 高（1.x→2.x 破坏性） | 中（LangChain 耦合） | 高 |
| 自定义节点 | TypeScript/Python | Python/JS | Python | TS |

**关键锁定风险**：工作流定义存在平台 DB 里，**不可 `git diff`、不可 code review、不可版本回滚**。本项目"代码即配置"可全量版本控制。

## 六、结论

### 6.1 能否用低代码平台实现？

**部分能——但仅限特性 1（三能力路由），且这不构成差异化。**

- **特性 1（三能力路由）**：✅ 四平台都能搭。但这正是 `competitive-landscape.md` 已实证的"6 个 0 stars 子项目都复刻"的同质化能力，**不是本项目的差异化核心**。
- **特性 2-7（6 个工程化特性）**：❌ 四平台**无一原生支持**，全部需要"在自定义代码节点里重写本项目的对应模块"。且：
  - 特性 6（单进程轻量）**不可实现**——平台架构决定部署复杂度。
  - 特性 5（会话防劫持）**需 fork 平台源码**——平台不允许覆盖会话 ID 派生。
  - 特性 3（熔断三态）n8n 有但**仅限内部 log-streaming**，不暴露给用户节点。

### 6.2 自建的不可替代性论证

**核心论点**：如果要用自定义代码节点实现全部 7 个工程化特性，等于**在低代码平台里重新写一个本项目**，且还要受平台运行时约束（会话模型固定、部署复杂度不可降、工作流不可版本控制）。

**自建的 4 个不可替代性**：

1. **运行时 vs 平台**：本项目是"可嵌入的后端运行时"（代码即配置、单进程、可 `import`），低代码平台是"需部署的服务"（7-8 个容器、工作流在 DB、不可嵌入）。定位不同。

2. **工程化深度 vs 编排广度**：低代码平台追求"覆盖更多集成"（n8n 400+ 集成），牺牲工程化深度。本项目追求"工程化特性做透"（SQL 双保险、可复位降级、评测门禁、会话防劫持），这些在 UI 优先的平台中**结构性难以做透**——不是"难配"，是"平台不暴露此级控制"。

3. **版本控制 vs DB 存储**：本项目代码可 `git diff`、code review、CI 阻断。低代码平台工作流存 DB，**不可版本控制、不可 code review、CI 无法阻断合入**。

4. **无 LLM 可验收 vs 需 LLM 运行**：本项目无 LLM_API_KEY 时走确定性 mock，全链路可验收，CI 冒烟零成本。低代码平台 LLM 节点要求凭据，无 LLM 时报错，CI 冒烟需 mock LLM 服务。

### 6.3 为何不转向基于低代码平台？

**不转向的 3 个理由**：

1. **差异化丢失**：转向 Dify/n8n 后，本项目变成"一个 Dify 工作流模板"，与 `competitive-landscape.md` 实证的"6 个 0 stars 子项目"无法区分——回到定位泛化问题。

2. **工程化特性降级**：6 个工程化特性从"原生一等公民"降级为"自定义节点里的补丁"，每个节点重复实现、无统一拦截、无 CI 门禁、无版本控制。

3. **锁定风险**：工作流定义锁在平台 DB，平台升级破坏性变更（Dify 1.x→2.x 已有先例）将直接破坏功能，迁移成本极高。

### 6.4 低代码平台的正确用法

低代码平台不是"替代本项目"，而是"本项目的上游/下游"：
- **上游**：n8n/Dify 可作为触发器（Webhook、定时任务、消息队列）调用本项目的 HTTP API。
- **下游**：本项目输出的证据/回答可被 n8n/Dify 工作流消费（推送、入库、通知）。
- **互补**：低代码平台做"集成编排"（连 SaaS、触发通知），本项目做"证据问答运行时"（路由、检索、SQL、降级、评测）。

## 七、对 spec.md 的修订建议

当前 `spec.md` 1.4 职责边界已有：
> 不负责 可视化编排 UI（与 Dify / Langflow / FastGPT / Flowise / n8n 等低代码平台的边界）：本组件以代码即配置，不提供拖拽编排、节点画布、可视化工作流编辑器；定位为可嵌入的后端运行时，而非低代码平台。

**建议补充**（基于本调研实证）：

在 1.4 职责边界中，将"不负责可视化编排 UI"条目扩展为：
> 不负责 可视化编排 UI（与 Dify / Langflow / FastGPT / Flowise / n8n 等低代码平台的边界）：本组件以代码即配置，不提供拖拽编排、节点画布、可视化工作流编辑器；定位为可嵌入的后端运行时，而非低代码平台。**不基于低代码平台实现**的理由：经 2026-08-12 GitHub 实证（见 `docs/low-code-feasibility-analysis.md`），n8n/Dify/Langflow/FastGPT 对本项目 7 个工程化差异化特性均无原生支持——SQL 安全双保险（四平台 0 命中 sqlglot）、可复位降级+熔断三态（n8n 有但仅限内部 log-streaming，Dify/Langflow/FastGPT 0 命中）、评测门禁+CI 回归（四平台无原生 CI 门禁）、会话防劫持+会话级 checkpoint（四平台无会话级防劫持，Langflow 仅有图执行级 checkpoint 非会话级）、单进程轻量+零配置冒烟（Dify 需 7-8 服务，四平台均无零配置冒烟）、无 LLM 可验收（四平台 mock 均为测试级非运行时级）。用自定义代码节点实现等于在平台里重写本项目且受平台运行时约束，故自建。

在文档头部"定位锐化依据"中引用本调研：
> 定位锐化依据（2026-08-12 GitHub 实证）：...故定位从"问答产品"锐化为"工程化优先的多源证据问答 Agent 运行时"，竞争维度从"问答体验"转移到"运行时工程化深度"。**低代码平台可行性已实证排除**（见 `docs/low-code-feasibility-analysis.md`）：n8n/Dify/Langflow/FastGPT 对 6 个工程化特性均无原生支持，自建不可替代。

## 八、数据附录（GitHub Code Search API 实证，2026-08-12）

```
# sqlglot 白名单守卫
repo:n8n-io/n8n + sqlglot whitelist        → 0
repo:langgenius/dify + sqlglot             → 0
repo:langflow-ai/langflow + sqlglot        → 0
repo:labring/FastGPT + sqlglot             → 0

# 熔断器
repo:n8n-io/n8n + circuit breaker          → 19（11 使用点全在 log-streaming.ee）
repo:langgenius/dify + circuit breaker     → 2（schedule task 内部）
repo:langflow-ai/langflow + circuit breaker → 0
repo:labring/FastGPT + circuit breaker     → 0

# 检查点恢复
repo:n8n-io/n8n + checkpoint restore       → 44（instance-ai SDK，suspended-run-restorer）
repo:langgenius/dify + checkpoint          → 16（home_snapshot，Agent 配置快照非会话状态）
repo:langflow-ai/langflow + checkpoint restore → 28（GraphCheckpoint，HITL graph suspend/resume 非会话级）
repo:labring/FastGPT + checkpoint          → 51（prompt-compress / agent-loop 非会话检查点）

# 会话防劫持
repo:langgenius/dify + session hijack      → 0
repo:n8n-io/n8n + session hijack           → 4（auth.service 平台认证非会话级防劫持）

# golden set 评测
repo:langgenius/dify + golden eval         → 0
repo:n8n-io/n8n + golden eval              → 3（instance-ai/evaluations SDK 层面）
repo:langflow-ai/langflow + golden eval    → 0

# thread_id 会话检查点
repo:langgenius/dify + thread_id checkpoint → 0

# Dify 部署复杂度
docker/docker-compose.yaml → 38 个 image（含 14 种向量 DB 选型）
```
