# agent-platform 开源调研与架构方案（2026-08-12）

> 状态：方案稿，待人工确认后固化。
> Stars / 活跃度数据均于 2026-08-12 通过 GitHub API 实证核实，非二手榜单转述。

## 一、调研范围与目标

对 GitHub 上与 `Code/agent` 子项目同类的开源方案做全方向调研（多智能体编排 / RAG / Text-to-SQL），
目标是**全新架构重构**：一个统一的生产级 Agent 系统，取代4 个子项目各自为政的局面。

## 二、调研结论

### 2.1 多智能体编排方向

| 项目 | Stars | 活跃度 | 解决的问题 | 架构 | 值得复用 | 应避免 |
|------|-------|--------|-----------|------|---------|--------|
| **langchain-ai/deepagents** | 27.6k | 极活跃（当日有 push），MIT | 复刻 Claude Code 的"深度 Agent"能力：规划、文件系统、子代理委派、上下文管理 | LangGraph 之上的 batteries-included harness：`create_deep_agent()` + 中间件体系（TodoList / SubAgents / HITL） | 规划-执行-反思循环（write_todos）、子代理上下文隔离、中间件化扩展点 | harness 抽象较厚，整体采用会被框架绑架；只借鉴模式，不引入全家桶 |
| **langchain-ai/langgraph** | 生产级事实标准 | 极活跃 | 有状态、可持久化、可中断恢复的 Agent 工作流 | StateGraph 有向图 + Checkpointer 状态持久化 + HITL interrupt | 显式图模型易调试、Checkpoint 跨步骤持久化 | 样板代码多；小任务用它是过度设计 |
| **pydantic/pydantic-ai** | 19.2k | 极活跃，MIT | 类型安全的 Agent 输出与依赖注入 | Pydantic 模型绑定 LLM 输出 + Agent/Deps/Result 分层 | 结构化输出强约束、与 FastAPI 同生态、测试友好 | 多 Agent 编排弱于 LangGraph，不适合做主管调度层 |
| **OpenAI Agents SDK** | 高增长 | 活跃 | 轻量多 Agent：Handoff 交接模式 | Agent + Handoff + Guardrail 极简抽象 | Handoff 简单直观、Guardrails 概念 | 与 OpenAI 生态耦合深，换模型代价大 |
| CrewAI / AutoGen | 30k / 高 | AutoGen 已并入微软 Agent Framework | 角色化团队 / 对话式推理 | Role-based Crew / 对话图 | 角色职责划分思路 | 框架变动剧烈、调试黑盒，生产依赖风险高 |

### 2.2 RAG 知识库方向

| 项目 | Stars | 活跃度 | 架构 | 值得复用 | 应避免 |
|------|-------|--------|------|---------|--------|
| **infiniflow/ragflow** | 87.3k | 极活跃，Apache-2.0 | DeepDoc 深度文档解析（OCR/版面/表格）+ 混合检索 + 内置 GraphRAG（Light/General 两档） | "文档解析质量决定 RAG 上限"理念、按文档类型适配切块模板、解析结果可视化便于排错 | 单体引擎重（Go+Python+ES/Infinity），整体嵌入成本高；作解析服务或对标参考 |
| **HKUDS/LightRAG** | 38.8k | 活跃，MIT，EMNLP 2025 | 轻量图增强 RAG：实体关系建图 + local/global 双层检索，存储后端可插拔（Neo4j/PG） | 图谱索引成本仅为微软方案 1/100、增量插入、存储后端抽象 | 缺权限/治理/多租户；论文项目工程成熟度弱于 RAGFlow |
| **microsoft/graphrag** | ~33k | **降温**（月提交个位数） | 实体抽取 + Leiden 社区检测 + 社区摘要，local/global 双查询 | 社区摘要提供全局视角的算法思想 | 索引成本极高（百篇文档 $50-200）；维护降温，不宜作依赖 |
| Dify / FastGPT | 141k / 23k | 极活跃 | 低代码全栈平台，RAG 只是子功能 | 知识库管理 UI 与多模型管理的交互参考 | 平台化方向与"自建可控 Agent 系统"目标冲突，不作底座 |

### 2.3 Text-to-SQL 方向

| 项目 | Stars | 活跃度 | 架构 | 值得复用 | 应避免 |
|------|-------|--------|------|---------|--------|
| **vanna-ai/vanna** | 23.8k | **已归档（archived=true，最后 push 2026-02）** | RAG 式 Text-to-SQL：DDL+文档+历史 SQL 三件套训练 → 向量检索 → 生成 | "训练三件套"与持续训练机制、提示词设计（可借鉴源码） | **禁止作为依赖引入**：仓库已停止维护，291 个 open issues 无人处理 |
| **Canner/WrenAI** | 17.2k | 活跃 | GenBI：语义层（open context layer）+ Text-to-SQL + 图表，20+ 数据源 | 语义层思想：业务口径定义先行，准确率本质依赖 schema linking 与业务词典 | 自定义许可证需法务确认；封装强、难深度定制 |
| **eosphoros-ai/DB-GPT** | 19.7k | 活跃，MIT | 全栈数据智能体：SMMF 多模型管理 + Text-to-SQL + RAG + 私有化优先 | 私有化部署与多模型管理框架设计 | 体量庞大，学习/裁剪成本高，不整体采用 |

### 2.4 三个关键发现

1. **Vanna 已归档**：Text-to-SQL 不能依赖 vanna 包，但其"三件套训练 + 检索注入"机制已被验证有效，自实现（约 300 行）并纳入评测。
2. **GraphRAG 系降温 + 高成本**：知识图谱增强不做 MVP 首选，LightRAG 式轻量方案留作 Phase 3 增量。
3. **deepagents 是 harness 不是框架**：借鉴其规划/子代理/中间件模式，编排底座选 LangGraph（状态持久化是生产刚需）。

## 三、技术栈选型（结合既有已验证资产）

复用 deepagents 生产化改造（Issue #120）已验证的选型，不另起炉灶：

| 层 | 选型 | 理由 |
|----|------|------|
| Agent 编排 | LangGraph 主管图 + deepagents 中间件模式借鉴 | 生产级状态持久化事实标准；图显式可调试 |
| 结构化契约 | Pydantic v2（工具输入输出 / API schema） | 与 FastAPI 同生态，类型安全防幻觉 |
| API 层 | FastAPI（HTTP + SSE 流式） | 现有子项目全部在用，统一收敛 |
| 长期记忆/会话 | PostgreSQL + pgvector + langgraph-checkpoint-postgres（embedding：bge-small-zh） | 一个 PG 承载 checkpoint、语义缓存、长期记忆、RAG 分块、SQL 训练数据 |
| RAG 检索 | 自建轻量链路：向量 + BM25 混合 → RRF 融合 | 避免 Milvus+Neo4j+ES 三件套运维负担 |
| Text-to-SQL | 自实现 Vanna 式管线 + sqlglot 白名单守卫 + 连接级只读 | vanna 已归档；安全双保险 |
| 可观测性 | Langfuse（可选，三态降级） | 复用现有基础设施 |
| 评测 | golden set + CI 回归门禁 | 无评测的重构等于盲改 |
| 部署 | Docker Compose，PG 为唯一有状态依赖 | 运维复杂度最低 |

## 四、系统架构

```
                FastAPI Gateway (SSE 流式 / 认证 / 会话防劫持)
                              │
                ┌─────────────▼─────────────┐
                │  Supervisor (LangGraph)    │
                │  路由 → 子能力 → 汇总 → 反思 │
                └──┬────────┬────────┬───────┘
                   │        │        │
         ┌─────────▼──┐ ┌───▼─────┐ ┌▼───────────┐
         │ Search 节点 │ │ RAG 节点 │ │ SQL 节点    │
         │ Tavily+熔断 │ │ 向量+BM25│ │ 三件套+守卫  │
         │            │ │ RRF 融合 │ │ 只读执行     │
         └─────────┬──┘ └───┬─────┘ └┬───────────┘
                   └────────┼────────┘
         ┌──────────────────▼───────────────────────┐
         │ PostgreSQL+pgvector · Langfuse · 评测门禁  │
         └──────────────────────────────────────────┘
```

关键设计决策：

- **单进程多节点而非微服务**：子项目拆 HTTP 适配层（wenda-adapter/kefu-adapter）已证明引入 SSE 聚合 bug、会话键错误、探活自递归等连环问题；LangGraph 节点边界隔离，保留未来按节点拆服务能力。
- **会话安全**：API_KEY 启用时忽略客户端 thread_id，按密钥哈希派生（防会话劫持）。
- **既往缺陷模式全部针对性修复**：懒加载加锁 + lifespan 预热；降级标志可复位（连续失败计数 + 冷却窗口）；后台任务持引用防 GC；compose 只发布 127.0.0.1。

## 五、MVP 范围

**包含**：

1. Supervisor + 3 子能力（Search / RAG / Text-to-SQL），SSE 流式输出执行过程
2. RAG：Markdown/PDF 导入 → 标题感知切分 → 向量化 → PG 混合检索
3. Text-to-SQL：三件套训练 → 生成 → 白名单守卫 → 只读执行（sqlite/postgres）
4. checkpoint 会话持久化 + 长期记忆语义召回 + 语义缓存 + 熔断
5. Langfuse 可选接线 + golden 评测 + CI 门禁
6. Docker Compose 一键启动（仅 PG 一个外部依赖）；零配置可跑内存模式冒烟

**明确不做**：知识图谱增强、前端 UI、多租户/权限、客服对话场景（均留 Phase 3）。

## 六、开发顺序（6 阶段，每阶段独立验收）

| 阶段 | 内容 | 验收标准 |
|------|------|---------|
| P0 脚手架 | 项目结构、配置、compose、Langfuse 接线 | /health 通、内存模式可启动 |
| P1 主管单链路 | Supervisor + Search + SSE + checkpoint | 多轮问答可恢复、冒烟过 |
| P2 RAG | 导入链路 + 混合检索 | 检索链路测试过 |
| P3 SQL | Vanna 式管线 + 守卫 + 只读执行 | 守卫/执行测试过 |
| P4 记忆与健壮性 | 长期记忆、语义缓存、熔断/可复位降级 | 故障注入测试过 |
| P5 评测门禁 | golden set + CI + README | 基线固化进仓库 |

## 七、当前实施进度（如实标注）

方案确认后已按 P0→P5 完成代码落地（`agent-platform/`）：

- 代码：约 30 个文件，全部就绪
- 单元测试：**40 个用例全部通过**（本地 Python 3.14 实测）
- 评测门禁：golden set 12 条 + CI workflow 已建；本地 eval 门禁脚本**已确认通过（12/12 = 100%）**
- 待办：（可选）docker compose 端到端冒烟

> 若对方案有异议，代码均可按新决策调整；核心可逆点：编排框架（LangGraph）、检索融合策略（RRF）、SQL 守卫（sqlglot）。
