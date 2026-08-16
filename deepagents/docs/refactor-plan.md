# deepagents 生产化改造方案（审核修订版 v3.6）

> 状态：✅ 已落地（Phase 0-7 全部实现，见 docs/audit-report.md）
> 日期：2026-08-10（方案定稿）/ 2026-08-11（落地完成）
> 落地提交：feat/deepagents-productionization 分支，9 个 commit（91c40d0b → 98736a6a）
> 来源：…→ v3.4 → agent3 第三轮决策落地 → v3.5 → agent3 第二轮深挖审核（P1-6~P1-9/P2-6~P2-9） → v3.6
> 定位：把 4 个独立子项目改造为"deepagents 联邦网关 + 3 子服务"的生产级多智能体系统，补齐思考规划 / 意图识别 / 意图改写 / 语义缓存 4 大缺失能力
> 约束：遵循 `AGENTS.md`，4 项目独立部署不合并代码；wenda/kefu 只读快照，改造以 deepagents/zhiku 为主

---

## 0. 审核修订追溯

本方案经两轮审核：

**第一轮：doc-expert 技能 7 维度审核**（技术时效性 / 架构合理性 / 可行性 / 合规 / 成本 / 一致性 / 风险）

| 编号 | 严重度 | 问题 | 修订 |
|------|--------|------|------|
| P0-1 | 🔴 方案错误 | 初版 Phase 4"从 create_deep_agent 迁移到 LangGraph 自建图" | Deep Agents 是 LangGraph 官方高层封装（27.6k stars，MIT），内置 planning/subagents/context mgmt。改为**扩展非重写** |
| P1-1 | 🟠 协议风险 | 初版用 Redis Stack 做语义缓存 | 改为 **Valkey + valkey-search**（BSD-3，LF 托管，命令 1:1 兼容） |
| P1-2 | 🟠 框架停滞 | zhanggui-kefu 用的 legacy 自研框架无社区维护 | 短期保持 legacy 独立；新增 **Phase 7** 长期迁移 |
| P2-1 | 🟡 选型不当 | L1 分类器用 BGE-reranker | 改为 **embedding + 原型向量余弦** |
| P2-2 | 🟡 措辞误导 | Langfuse ClickHouse "2026 新增" | 改为"自部署依赖 ClickHouse（官方 docker-compose 已含）" |
| P2-3 | 🟡 依赖未核实 | 熔断器 pybreaker | 改用 **tenacity**（已有依赖 `requirements.txt:113`，async 原生） |

**第二轮：agent1 代码实况审核**（事实性 / 架构 / 可行性 / 一致性 / 风险覆盖）

| 编号 | 严重度 | 问题 | 修订 |
|------|--------|------|------|
| A0-1 | 🔴 事实硬伤 | Phase 2 写"main_agent.py:118-126 路由扩展"——实际 118-126 是流式事件采集/监控，真正路由在 `create_deep_agent(subagents=[...])`（48-57 行） | Phase 2 路由入口改为 `get_main_agent()` 48-57 行 |
| A0-2 | 🔴 架构矛盾 | "同进程嵌套"要求 import wenda/zhiku 代码 = 合并代码，违反 AGENTS.md"不合并代码" | **默认跨服务 HTTP**；同进程标注为"需引入对方代码作依赖，属合并形式，不推荐" |
| A1-1 | 🟠 路径不一致 | `prompts/`（复数）vs 实际 `prompt/`（单数） | 全文档统一为 `prompt/` |
| A1-2 | 🟠 缓存 key 缺维度 | 单一 `kb_version` 无法覆盖多子服务 KB；缺 `gray` 维度 | 改为 `kb_versions`（按子服务）+ `gray_pct` |
| A1-3 | 🟠 spike 未前置 | TodoListMiddleware API 验证应在 Phase 4 前完成 | 前置到 Phase 0 作 spike |
| A1-4 | 🟠 加载机制未说明 | 新增 .yaml 由谁加载？`prompts.py` 只加载 `prompts.yml` | 补 `prompts.py` 改造说明 |
| A2-1 | 🟡 基线定义模糊 | Phase 0"基线报告"是静态标注还是实跑？ | 明确：无 API key 为静态标注，有 key 为实跑 |
| A2-2 | 🟡 成本承诺绝对化 | "成本降 ≥30%"依赖流量分布 | 改为"在评测集分布下成本降 ≥30%" |
| A2-3 | 🟡 Phase 7 无工期估 | 3 Flow + GraphRAG 重表达是数月级 | 标注量级 |
| A2-4 | 🟡 原型向量同源污染 | 原型向量若从评测集选则准确率虚高 | 明确来源独立于评测集 |
| A2-5 | 🟡 脱敏与缓存顺序 | PII 脱敏与缓存先后未明确 | 架构图标注 guardrail → cache 顺序 |
| A2-6 | 🟡 开发机无 Docker | ClickHouse 在无 Docker 开发机不现实 | 开发期 trace 降级 no-op（复用 agent-core） |

---

## 1. 已有基础（对齐 deepagents 阶段一~四成果）

本方案不重复已完成的工作。deepagents 已完成以下改造（见 `README.md` 改造历程 + `CHANGELOG.md`）：

| 已有能力 | 代码位置 | 本方案复用方式 |
|---------|---------|--------------|
| deepagents 0.7.5 + LangGraph 1.2.10 主管 | `agent/main_agent.py:48-57`（`create_deep_agent(subagents=[...])`） | Phase 2/4 在此基础上扩展 |
| 3 子 Agent（Tavily/MySQL/zhiku） | `agent/subagents/` | Phase 2 扩展为远程子服务 + 本地 fallback |
| SQLite checkpointer（对话状态持久化） | `main_agent.py:33-41`（`langgraph-checkpoint-sqlite>=2.0.0` 已在 `requirements.txt:56`，fallback `InMemorySaver` 作防御性降级） | 保留，语义缓存是独立新增层 |
| agent-core 共享内核（tracing/logging/guardrails） | `agent-core/` | Phase 0 Langfuse 接入复用现有 tracing span |
| SecurityGuardsMiddleware（HTTP 鉴权 + 限流） | `api/server.py` | Phase 6 限流降级复用并扩展 |
| 模型 fallback（主备路由） | `agent/llm.py` | Phase 6 成本路由扩展为多级 |
| zhiku 健康探活 + 降级 | `tools/zhiku_tools.py` | Phase 2 子服务健康探活复用此模式 |
| 工具超时隔离（asyncio.wait_for） | `tools/_timeout.py` | Phase 6 熔断器集成于此 |
| **tenacity 9.1.4（已有依赖）** | `requirements.txt:113` | Phase 6 直接复用，无需新增 |
| Docker + docker-compose（web + mysql + zhiku） | `Dockerfile` / `docker-compose.yml` | Phase 1 扩展为 4 服务编排 |
| 评测框架骨架（golden 10 题 + 三层指标） | `eval/` | Phase 0 扩展为全项目评测集 |
| 30 单元测试（3 文件 30 测试函数） | `tests/unit/` | 各 Phase 新增测试并入 |
| pyproject.toml + ruff | `pyproject.toml` | 新增代码遵循同一配置 |
| prompt 配置（单数 `prompt/`） | `prompt/prompts.yml` + `agent/prompts.py` | Phase 3/4 新增 .yaml 需扩展 `prompts.py` 加载 |

**当前待做（README 已标记）**：
- DB 子 Agent 仍连 pharma_db（会展库待准备）——本方案不解决，属数据准备
- task planning (write_todos) 未启用——Phase 4 评估启用 `TodoListMiddleware()`（来自 `langchain.agents.middleware`，langchain 1.3.14；**Phase 0 spike 首问"0.7.5 默认栈是否已挂载"**——D12）
- 评测待实跑标定——Phase 0 解决

---

## 2. 改造目标与原则

| 项 | 内容 |
|----|------|
| **目标** | 4 个独立子项目 → "deepagents 联邦网关 + 3 个独立子服务"的生产级多智能体联邦，补齐思考规划 / 意图识别 / 意图改写 / 语义缓存 4 大能力 |
| **原则** | ① 不合并代码，服务化联邦（HTTP 解耦，框架异构无关） ② 渐进式，每阶段独立验收可上线 ③ 复用已有 agent-core 内核，不重复造轮子 ④ 每阶段配评测门禁，不通过不进下一阶段 ⑤ 技术选型只用 2026 年最新稳定版（已全部实测核实） |
| **联邦 ROI 论证** | wenda 的 Text-to-SQL 比 deepagents `database_query_agent` 更完整（有完整 SQL 生成+验证+执行+ES+Qdrant 流程，本地 subagent 是简化版）；zhiku 的 RAG 比 `knowledge_base_agent` 更完整（有 Milvus+Neo4j+GraphRAG，本地是简单向量检索）；独立扩缩容：SQL 查询和 RAG 检索负载特征不同，独立扩缩有运维价值；kefu 是 deepagents 没有的客服能力，必须接入 |
| **不在范围** | 前端合并（各项目前端独立）、辅助资料、wiki 知识整理、pharma_db → 会展库数据迁移 |

---

## 3. 目标架构

```
                         ┌──────────────────────────────────────────┐
   用户 ──HTTP/WS──────▶ │   deepagents-gateway (联邦网关/主管)       │
                         │   ┌──────────────────────────────────┐   │
                         │   │ guardrail (PII 脱敏 + 注入检测)    │   │ ← 先于缓存
                         │   │ L1 意图分类 (embedding+原型余弦)   │   │
                         │   │ L2 LLM 细判 + 置信度               │   │
                         │   │ Query 改写 (指代消解+子问题分解)    │   │
                         │   │ 语义缓存 (Valkey Search + TTL)     │   │
                         │   │ Planner 扩展 + Reflexion           │   │
                         │   └──────────────────────────────────┘   │
                          └───────┬──────────────┬───────────────────┘
                                  │ Agent Protocol│（subagent 委派，复用 monitor 链路）
              ┌──────────────────┼───────────────┼──────────┐
              ▼                  ▼               ▼          ▼
         wenda-service      zhiku-service    kefu-service   Tavily
          (FastAPI)          (FastAPI)        (legacy)   (SaaS)
         Text-to-SQL        RAG 知识库       对话+GraphRAG
         MySQL+ES+Qdrant    Milvus+Neo4j     Neo4j+BGE
         独立部署/扩缩       独立部署/扩缩     独立部署/扩缩

                         ┌──────────────────────────────────────────┐
                         │  横切：Langfuse(ClickHouse) trace + 评测   │
                         │  + tenacity 限流降级 + 成本路由 + guardrail │
                         │  + 灰度 + 多租户                          │
                         └──────────────────────────────────────────┘
```

**子 Agent 集成模式**（默认 AsyncSubAgent + Agent Protocol）：

- **AsyncSubAgent + Agent Protocol**（**默认**，独立扩缩容）：用 deepagents 内置 `AsyncSubAgent(url=...)`，子服务实现 Agent Protocol 即可被自动连接。符合"不合并代码"约束
- ~~同进程嵌套~~（**不推荐**）：wenda/zhiku 的 `CompiledStateGraph` 直接传入 `create_deep_agent(subagents=[...])`——deepagents 官方支持，但要求 `import` 对方代码到同一进程 = 引入依赖 = **合并代码的一种形式，违反 AGENTS.md 约束**。仅在性能瓶颈时作为可选优化，且需明确标注"引入对方代码作依赖"

**请求处理顺序**（guardrail → cache）：
```
请求 → guardrail(8PII 脱敏+注入检测) → 意图识别 → query 改写 → 语义缓存查询
  → [命中] 直接返回
  → [未命中] Planner → 子服务 HTTP 调用 → Reflexion → 写缓存 → 返回
```

---

## 4. 技术选型（2026 稳定版，全部实测核实）

| 组件 | 选型 | 版本 | 协议 | Stars | 用途 | Phase | 核实来源 |
|------|------|------|------|-------|------|-------|---------|
| 主管框架 | **Deep Agents** | 0.7.5+ | MIT | 27.6k | 网关 + planning + subagents + **RubricMiddleware(内置 Reflexion)** | 2,4 | github.com/langchain-ai/deepagents |
| 编排底座 | **LangGraph** | 1.2.10+ | MIT | 39.4k | wenda/zhiku 子图 | 1 | github.com/langchain-ai/langgraph |
| 远程子 Agent | **AsyncSubAgent + Agent Protocol** | — | — | — | 跨服务子 Agent 通信（deepagents 内置） | 2 | deepagents.middleware.async_subagents（Agent Protocol-compliant server） |
| 可观测 | **Langfuse** | latest | MIT | 32.8k | trace + eval + prompt mgmt | 0 | github.com/langfuse/langfuse（自部署依赖 ClickHouse，官方 docker-compose 已含） |
| Web 框架 | **FastAPI** | latest | MIT | 101.5k | 4 服务 API | 1 | github.com/fastapi/fastapi（uv 管理） |
| HTTP 客户端 | **httpx** | 0.28.1 | BSD-3 | — | 网关调子服务（async） | 2 | 已在 `requirements.txt:39` |
| 缓存 | **Valkey + valkey-search** | 9.1.2 (bundle) | BSD-3 | 26.8k | 语义缓存 + 向量检索 | 5 | `valkey/valkey-bundle:9.1.2`（预装 search 1.2.1，无需 `--loadmodule`） |
| L1 分类 | **embedding + 原型向量余弦** | — | — | — | 意图粗分 <10ms | 3 | 复用 Valkey Search embedding |
| 熔断/重试 | **tenacity** | 9.1.4 | MIT | — | 限流降级 | 6 | **已有依赖** `requirements.txt:113`，直接复用 |
| 客服（短期） | legacy 自研框架 | — | demo | — | kefu 独立（自研框架无社区维护） | 1-2 | `zhanggui-kefu/legacy/`（模仿 Rasa 架构的自研框架，非 Rasa） |
| 客服（长期） | **deepagents + LangGraph 重写** | — | MIT | — | 统一技术栈 | 7 | 消除自研框架无维护风险 |
| 包管理 | **uv** | latest | MIT/Apache-2.0 | — | 依赖管理 | 全 | FastAPI/Deep Agents 均用 uv |

> Stars/版本为 2026-08-10 webfetch 快照，以安装时 `uv lock` 锁定版本为准。

**已摒弃的选型及原因**：
- ~~Redis Stack~~：2024 协议变更为 RSALv2/SSPLv2（非 OSI 开源），云厂商不支持新版本
- ~~BGE-reranker（L1 分类）~~：cross-encoder 重排序模型，不是分类器
- ~~pybreaker（熔断）~~：维护状态未核实，tenacity 已在依赖中
- ~~自建 LangGraph 主管图~~：Deep Agents 已是 LangGraph 官方高层封装，重写丢弃内置能力
- ~~同进程嵌套（默认）~~：违反"不合并代码"约束，改为跨服务 HTTP 默认

---

## 5. 分阶段实施

### Phase 0：可观测性统一 + 评测基线 + spike（前置）

| 项 | 内容 |
|----|------|
| **目标** | 先建度量再改造；统一 4 项目 trace；前置 spike 验证 |
| **前置** | 无 |
| **改动** | ① 部署 Langfuse（自部署，官方 docker-compose 含 ClickHouse 后端）② deepagents 已有 agent-core tracing（`start_span`），加 Langfuse `@observe()` 装饰器适配层，复用现有 span ③ zhiku 已有 LangGraph，加 Langfuse LangChain callback ④ 扩展 `eval/golden.jsonl` 为全项目评测集（每项目 50+ 样本，含期望路由/意图/答案） ⑤ 写 `eval/run-all.py` 跑全量评测出报告 ⑥ **TodoListMiddleware 集成 spike**：`TodoListMiddleware` 来自 `langchain.agents.middleware`，**首问"0.7.5 默认栈是否已挂载"**（多篇官方教程称默认栈含 TodoListMiddleware，但 README 写"v0.7 改为 opt-in"——两者矛盾，spike 需澄清），再决定 Phase 4 是"启用"还是"调参"，产出 spike 报告 |
| **关键文件** | `deepagents/docker-compose.yml`（扩，含 Langfuse + ClickHouse + Valkey）、`deepagents/agent/tracing/langfuse_adapter.py`（新）、`deepagents/eval/golden.jsonl`（扩）、`deepagents/eval/run-all.py`（新）、`deepagents/docs/spike-todolist-middleware.md`（新，spike 报告） |
| **实现要点** | Langfuse 自部署用官方最新 docker-compose（含 ClickHouse）；`@observe()` 与 agent-core `start_span` 共存，通过 OpenTelemetry bridge 统一；eval 集复用 PROPOSAL.md 三层指标；**trace 三态**：开发期 no-op（agent-core OTel 无 SDK 自动 no-op）、CI/preview 起 Langfuse、生产 ClickHouse，三态分别验收；**跨服务 trace 传播用 W3C traceparent**（httpx 请求头注入，子服务提取并关联 span），否则联邦架构下"全链路"名不副实；**wenda 评测断言**：wenda `/api/query` 是 SSE 流式，评测集对**最终合成文本**断言（消费流 → 聚合 → 比对期望），非逐 chunk 断言；spike 用最小示例验证 `from langchain.agents.middleware import TodoListMiddleware` + `create_deep_agent(middleware=[TodoListMiddleware()])` 集成行为（源码级已验证：`TodoListMiddleware.__init__(self, *, system_prompt, tool_description)`，提供 `write_todos` 工具） |
| **验收** | 4 项目 trace 上报 Langfuse（或开发期 no-op 降级）；评测集 ≥200 样本（**LLM 合成 + 人工审核标注期望路由/意图**，golden 10 题保留作核心回归）；**基线报告**：无 API key 时为静态标注报告（标注期望路由/意图），有 key 时为实跑报告（JSONL + HTML）；spike 报告产出（TodoListMiddleware 可用/不可用/需适配） |
| **风险** | Langfuse ClickHouse 内存 ≥2GB，开发机无 Docker 时走 no-op 降级 |
| **回滚** | Langfuse 为旁路观测，关闭即回退，不影响主链路 |

### Phase 1：服务化拆分

| 项 | 内容 |
|----|------|
| **目标** | 4 项目暴露统一 HTTP 接口，可独立部署 |
| **前置** | Phase 0 |
| **改动** | ① **wenda**：新建 `wenda-adapter`（薄 FastAPI 层），**wenda `/api/query` 是 SSE 流式（`text/event-stream`），与目标 JSON schema 不兼容**——wenda-adapter 需做流→JSON 适配（消费 SSE 流 → 聚合为 `{answer, data, trace_id}` JSON），并提供 `/health`（wenda 无健康端点）；wenda 快照零改动 ② **zhiku**：`app/main.py` 已有 `/query` + **三级 `/health`/`/health/live`/`/health/ready`**（复用，不另起），对齐 schema ③ **kefu**：legacy 已有 FastAPI server + `/api/messages`（`legacy/api/server.py`），包一层适配器 `kefu-adapter/main.py` 转统一 schema ④ 各项目加 Dockerfile（zhiku 已有，wenda-adapter/kefu-adapter 新建） ⑤ 统一 `api/schemas.py`（Pydantic，共享包） ⑥ **修订 AGENTS.md 边界表**：新增 wenda-adapter/kefu-adapter/shared-schemas/kefu-service 行 ⑦ **deepagents 入站鉴权**：网关侧加 API Key 鉴权（复用 `SecurityGuardsMiddleware`），子服务鉴权内网直连可关 |
| **关键文件** | `zhanggui-wenda/data-agent/api/schemas.py`（新）、`zhanggui-zhiku/app/api/schemas.py`（对齐）、`kefu-adapter/main.py`（新）、`kefu-adapter/Dockerfile`（新）、`shared-schemas/`（新，统一 Pydantic schema 包） |
| **实现要点** | 统一 schema 用 Pydantic v2（FastAPI 已依赖）；wenda-adapter/kefu-adapter 是薄适配层，不改 wenda/kefu 快照业务代码；shared-schemas 作为独立小包，各服务 Dockerfile 构建时 `pip install ../shared-schemas`（非 editable，避免容器化路径问题） |
| **验收** | 4 服务独立 `docker compose up` 起来；`/health` 全绿；`/query` 端到端返回正确 schema |
| **风险** | wenda/kefu 是只读快照（AGENTS.md 约束），只加 Dockerfile + adapter，不改业务代码 |
| **回滚** | 各服务独立，可单独回滚 |

### Phase 2：deepagents 升级为联邦网关

| 项 | 内容 |
|----|------|
| **目标** | deepagents 主管从"调本地子 Agent"升级为"联邦网关"，默认跨服务 HTTP 调子服务 |
| **前置** | Phase 1 |
| **改动** | ① 新增 `agent/async_subagents.py`，用 `AsyncSubAgent(url=..., description=...)` 定义 3 个远程子 agent（`text_to_sql` / `rag_query` / `customer_service`），deepagents 通过 **Agent Protocol** 自动连接子服务（源码级已验证：`AsyncSubAgent` 连接 Agent Protocol-compliant server） ② **远程替换本地**（非并行）：`text_to_sql` 替换 `database_query_agent`、`rag_query` 替换 `knowledge_base_agent`、`customer_service` 全新；原 3 个本地子 Agent 降级为 **fallback**（仅远程挂时激活，工具集不爆炸：3 远程正常 + 3 本地 fallback） ③ **路由入口在 `get_main_agent()` 48-57 行**（`create_deep_agent(subagents=[...])`）——`subagents` 列表改为 3 个 `AsyncSubAgent`；`main_agent.py:117-126` 是流式事件采集/监控（`monitor.report_assistant`），不是路由逻辑，不需改 ④ **远程子服务以 subagent 形态包装**（D14：非裸 tool——`create_deep_agent(subagents=[...])` 接受子代理定义，不是裸 tool；若包装成普通 tool，`monitor.report_assistant` 只在 `task` 工具调用即子代理委派时触发，路由推送会断） ⑤ WebSocket 前端增加"命中子服务 / 走 fallback"状态推送 ⑥ 子服务健康探活复用 `zhiku_tools.py` 已有模式 |
| **关键文件** | `deepagents/agent/async_subagents.py`（新，3 个 `AsyncSubAgent` 定义）、`deepagents/agent/main_agent.py`（改 `get_main_agent` 48-57 行的 `subagents=[...]`）、`deepagents/agent/config.py`（新，子服务 Agent Protocol 地址配置） |
| **实现要点** | `AsyncSubAgent` 是 deepagents 内置的远程子 agent 机制（通过 Agent Protocol 连接，非手写 httpx）；子服务需实现 Agent Protocol（LangGraph Platform 原生支持，FastAPI 服务用 `langgraph-protocol` 包适配）；健康探活异步周期性 ping `/health`；fallback 触发时发 Langfuse 事件标记降级；**默认跨服务 Agent Protocol**（符合"不合并代码"约束），同进程嵌套不推荐（需引入对方代码作依赖） |
| **验收** | 主管能路由到 3 个远程子服务；故意 kill 某子服务，自动降级到 fallback；WebSocket 前端显示路由路径 |
| **风险** | HTTP 模式增加网络延迟（~1-5ms 内网），可接受 |
| **回滚** | `config.py` 设 `mode=local` 即回退到纯本地子 Agent |

### Phase 3：意图识别 + 意图改写

| 项 | 内容 |
|----|------|
| **目标** | 网关层补齐两级意图识别 + query 改写，**short-circuit 模式**：L1/L2 只拦截 chitchat/单意图直接回（<10ms，不打下游），复杂 query 仍交主管 LLM 全工具路由（不替换 LLM 路由，只短路简单意图） |
| **前置** | Phase 2 |
| **改动** | ① **L1 粗分类器**：用网关已有 embedding 模型对 query 编码，与 5 个意图原型向量（`text_to_sql` / `rag_knowledge` / `customer_service` / `web_search` / `chitchat`）算余弦相似度，top-3 候选 + 置信度，<10ms ② **L2 LLM 细判**：仅当 L1 置信度 < 0.8 时触发，用 LLM 在 top-3 里细判（复用 kefu `legacy/dialogue_understanding/generator/templates/command_prompt.jinja2` 决策规则表模式） ③ **置信度兜底**：<0.5 走 `clarify` 反问 ④ **Query 改写**：网关入口加 `rewrite_node`，做指代消解 + standalone question（复用 zhiku `rewritten_query_and_itemnames.prompt`）+ 子问题分解（一问拆多问并行） ⑤ 改写前后 A/B 评测（召回率/正确率） ⑥ 意图原型向量可在线更新（管理 API） |
| **关键文件** | `deepagents/agent/intent/classifier.py`（L1，embedding+余弦）、`deepagents/agent/intent/llm_judge.py`（L2）、`deepagents/agent/intent/prototypes.json`（5 类原型向量，可更新）、`deepagents/agent/rewrite/rewrite_node.py`（新）、`deepagents/agent/rewrite/subquery_decompose.py`（新）、`deepagents/prompt/intent.yaml`（新）、`deepagents/prompt/rewrite.yaml`（新）、`deepagents/agent/prompts.py`（扩，加载新增 .yaml） |
| **实现要点** | L1 embedding **固定本地 sentence-transformers（如 bge-small-zh），与 Phase 5 缓存 embedding 解耦，永不切换**（避免向量空间不同导致原型向量重建+重标定）；**原型向量初始化用每类 20 条典型 query 的 embedding 均值，来源必须独立于评测集**（避免同源污染导致准确率虚高）；子问题分解用 LLM 产出 `[{subquery, intent}]` 列表，并行调 Phase 2 路由；`prompts.py` 扩展为加载 `prompt/` 下所有 .yaml（当前只加载 `prompts.yml`） |
| **验收** | 意图准确率 ≥95%（评测集）；低置信度走反问；改写后召回率提升 ≥5%；L1 延迟 <10ms（本地 sentence-transformers 需 benchmark 确认） |
| **风险** | 原型向量质量依赖初始 query 代表性，首版用人工选 20 条/类（独立于评测集）；本地 sentence-transformers 首次加载慢（模型加载 ~2s），推理 <10ms 需 benchmark |
| **回滚** | L1 可关闭（`config.intent_l1_enabled=false`），回退到纯 LLM 路由 |

### Phase 4：思考规划扩展（不重写，扩展 deepagents）

| 项 | 内容 |
|----|------|
| **目标** | 在 deepagents 框架上扩展显式 Planner + Reflexion，不重写主管图 |
| **前置** | Phase 3 + **Phase 0 spike 报告**（TodoListMiddleware API 已验证） |
| **改动** | ① **启用 task planning**：根据 Phase 0 spike 报告——**若 0.7.5 默认栈已挂载 TodoListMiddleware**（多篇官方教程称默认栈含），Phase 4 从"启用"改为"调参"（传 `system_prompt`/`tool_description` 定制）；**若未挂载**，`from langchain.agents.middleware import TodoListMiddleware`，传入 `create_deep_agent(middleware=[TodoListMiddleware()])` 显式启用 ② **自定义 planner prompt**：扩展 `prompt/prompts.yml` 的 main_agent system_prompt，加入"先规划再执行"指令 + JSON schema 约束的 step 格式 `[{step_id, tool, input, depends_on}]` ③ **Reflexion 用内置 `RubricMiddleware`**：`from deepagents.middleware import RubricMiddleware`，传入 `create_deep_agent(middleware=[RubricMiddleware(model=..., max_iterations=3)])`——源码级已验证：`RubricMiddleware` 是"self-evaluated iteration against a rubric"，含 `CriterionPass/CriterionFail(gap)` 差距分析 + `on_evaluation` 回调，**不需要自己写 reflexion.py** ④ **早停**：所有 step 成功或 rubric 评估通过 → 合并答案输出 ⑤ 规划结果落 Langfuse trace 可审计 ⑥ **zhiku enable_thinking 处置**：`app/lm/lm_utils.py:35` 的 `extra_body={"enable_thinking": False}` 是**全局默认**，**不移除**（直接移除会让 zhiku 所有 LLM 调用打开思考链，成本/延迟全涨）；改为**按调用点透传**——在需要规划的节点通过 `extra_body={"enable_thinking": True}` 覆盖全局默认，注释已说明"宿主经 extra_body 透传"机制 |
| **关键文件** | `deepagents/agent/main_agent.py`（启用 `TodoListMiddleware` + `RubricMiddleware`，引用 spike 报告）、`deepagents/prompt/prompts.yml`（扩 planner 指令）、`deepagents/agent/prompts.py`（扩，加载新增 .yaml） |
| **实现要点** | **不替换 `create_deep_agent`**——它是 LangGraph 官方高层封装，内置 planning/subagents/context mgmt/skills。**不自己写 Reflexion**——`RubricMiddleware` 是 deepagents 内置的自我评估迭代中间件（源码级已验证：`__init__(*, model, system_prompt, tools, max_iterations=3, on_evaluation)`，docstring "drives self-evaluated iteration against a rubric"）；**TodoListMiddleware 来自 langchain（`langchain.agents.middleware`），源码级已验证：`__init__(self, *, system_prompt, tool_description)`，提供 `write_todos` 工具**；**D12：Phase 0 spike 首问"0.7.5 默认栈是否已挂载"**（官方教程与 README 矛盾），已挂→Phase 4 调参，未挂→显式传入，避免重复挂载或无用功 |
| **验收** | 复杂跨域 query（如"查订单再搜相关政策再总结"）能自动拆 3 步；失败 step 能重规划；trace 可见 plan→execute→reflect 全链；简单 query 不过度规划（直连子 Agent） |
| **风险** | 过度规划增加延迟和成本，需 prompt 调优 |
| **回滚** | TodoListMiddleware 可关闭，Reflexion 可关闭，回退到隐式委派 |

### Phase 5：语义缓存（Valkey）

| 项 | 内容 |
|----|------|
| **目标** | "之前问过的问题命中缓存直接返回答案"，不打到下游 |
| **前置** | Phase 3（需要意图 + 改写后的 query 做缓存 key） |
| **改动** | ① 部署 Valkey 9.1.1 + valkey-search 模块（BSD-3，LF 托管） ② **缓存 key = `hash(intent + rewritten_query + kb_versions + tenant_id + gray_pct)`**，其中 `kb_versions = {wenda: v1, zhiku: v2, kefu: v3}`（按子服务维度，kefu 更新不失效 wenda 缓存） ③ **分层缓存**：L1 精确缓存（hash 命中，<1ms）→ L2 语义缓存（embedding 相似度 > 0.92 且 TTL 内，<10ms）→ L3 检索结果缓存（只重算 LLM） ④ 写入：query 答完后异步写缓存（不阻塞响应） ⑤ **防脏命中**：知识库更新时 bump 对应子服务 `kb_version` 自动失效；缓存 value 含 `trace_id` 可溯源 ⑥ **防击穿**：singleflight（同 query 并发只算一次）+ 空值缓存（防穿透） ⑦ 命中率指标上报 Langfuse + 采样人工审核 |
| **关键文件** | `deepagents/agent/cache/semantic_cache.py`（新）、`deepagents/agent/cache/layers.py`（新，L1/L2/L3）、`deepagents/agent/cache/singleflight.py`（新）、`deepagents/docker-compose.yml`（扩，加 valkey 服务）、`deepagents/agent/cache/config.py`（新，阈值/TTL 可配置） |
| **实现要点** | Valkey 用 **`valkey/valkey-bundle:9.1.2`** Docker 镜像（官方预装 valkey-search 1.2.1 + json + bloom + ldap，无需 `--loadmodule`）；Python 客户端用 `valkey` 包（API 兼容 redis-py，BSD）；valkey-search 命令与 RediSearch 1:1 兼容（`FT.CREATE`/`FT.SEARCH`/HNSW/COSINE）；L2 向量索引用 HNSW + COSINE；singleflight 用 `asyncio.Lock` per query_hash；**缓存 key 含 `gray_pct` 防灰度期间脏命中**（灰度用户走新链路、普通用户走旧链路，缓存隔离） |
| **验收** | 重复 query 命中 L1 <1ms；语义相似 query 命中 L2 <10ms；命中率指标上报 Langfuse；KB 更新后旧缓存自动失效；缓存 value 可溯源到 trace_id；灰度期间无脏命中 |
| **风险** | 语义缓存脏命中（相似但答案不同）——靠 `kb_versions` 失效 + 阈值 0.92 + 采样审核缓解；valkey-search 模块需 GCC 12+ 编译，用预编译 Docker 镜像避免 |
| **回滚** | 缓存层可关闭（`config.cache_enabled=false`），所有请求穿透到下游 |

### Phase 6：横切能力（可并行）

| 能力 | 改动 | 关键文件 | 复用已有 |
|------|------|---------|---------|
| **限流降级** | LLM 调用 token bucket 限流；子服务超时降级到 fallback；tenacity 熔断 + 重试 | `deepagents/gateway/rate_limit.py`（新）、`deepagents/gateway/circuit_breaker.py`（新） | 复用 `SecurityGuardsMiddleware` 已有限流 + `tools/_timeout.py` 超时；**tenacity 已在 `requirements.txt:113`** |
| **成本路由** | 简单意图走便宜模型，复杂意图走大模型；接 Anthropic prompt caching / OpenAI cached_prompt | `deepagents/agent/intent/cost_router.py`（新） | 扩展 `agent/llm.py` 已有模型 fallback |
| **安全 guardrail** | 输入 PII 脱敏 + prompt injection 检测；输出 guard（复用 kefu guard 节点模式）；SQL/工具白名单 | `deepagents/gateway/input_guard.py`（新）、`deepagents/gateway/output_guard.py`（新） | 复用 `sql_validation.py` 已有 SQL 防护 |
| **灰度发布** | 新 prompt/新链路按 `user_id % 100 < gray_pct` 灰度；对比 SLO | `deepagents/gateway/gray.py`（新） | Langfuse 已有实验对比能力 |
| **多租户** | `tenant_id` 隔离 thread_id / 缓存 namespace / KB 权限；**各子服务必须支持 tenant_id 隔离，不支持的服务禁用缓存（防串租户数据）** | `deepagents/api/context.py`（扩） | 复用 `api/context.py` 已有 ContextVar 会话隔离 |

| 项 | 内容 |
|----|------|
| **验收** | 限流生效（超限返回 429）；降级自动触发；**在评测集分布下成本降 ≥30%**（口径：评测集全量实跑，对比新旧链路 token 总成本，Langfuse cost 字段聚合）；guardrail 拦截注入；灰度按比例分流；多租户隔离无串 |
| **回滚** | 各中间件独立开关，可单独关闭 |

### Phase 7：kefu 从 legacy 迁移到 deepagents（长期）

| 项 | 内容 |
|----|------|
| **目标** | 消除自研框架无社区维护风险，统一技术栈 |
| **前置** | Phase 2-6 完成，网关能力齐全 |
| **改动** | ① 用 deepagents + LangGraph 重写 kefu 的对话管理：9 种命令（kefu `legacy/dialogue_understanding/generator/templates/command_prompt.jinja2` 已定义：start flow / cancel flow / change flow / set slot / knowledge_answer / chitchat / cannot_handle / clarify / human_handoff）+ 业务 Flow（kefu `ecs_demo/data/flows/` 下 3 个：`flow_order.yml` / `flow_logistics.yml` / `flow_postsale.yml`）→ 用 LangGraph 状态图重表达 ② GraphRAG 能力（kefu `ecs_demo/addons/information_retrieval.py` 的 6 步流程）→ 作为 deepagents 子 Agent ③ BGE 中文 embedding → 保留或升级（评估 2026 SOTA） ④ kefu-adapter 废弃，新 kefu-service 直接是 FastAPI + LangGraph ⑤ 评测对齐：kefu **无评测数据集**（glob `zhanggui-kefu/**/eval*` 零结果），需新建评测集（复用 Phase 0 评测框架 + LLM 合成 + 人工审核） |
| **关键文件** | `kefu-service/`（新，deepagents + LangGraph 重写）、`kefu-service/agent/flows/`（Flow 用 LangGraph 重表达）、`kefu-service/agent/graph_rag.py`（GraphRAG 子 Agent） |
| **实现要点** | legacy 的 Flow 概念 → LangGraph 的子图；legacy 的 Policy → LLM 驱动的意图路由（复用 Phase 3）；legacy 的 Tracker → LangGraph State；legacy 的 NLG → deepagents 输出；**渐进迁移**：先迁移最高频 3 个 Flow，灰度切换，验证后全量 |
| **验收** | 新 kefu-service 意图准确率 ≥ legacy 原版；GraphRAG 召回率 ≥ 原版；Flow 全覆盖；legacy 可下线 |
| **风险** | **数月级工程**（3 Flow + GraphRAG 完整重表达 + legacy Tracker→LangGraph State 语义映射）；需逐 Flow 验证；legacy 对话状态管理较复杂，LangGraph 重表达需仔细 |
| **回滚** | legacy 保持运行，新 kefu-service 灰度，出问题切回 |

> **执行状态（2026-08 更新）**：第④项「kefu-adapter 废弃」**已完成**。
> 原因（已解决）：`kefu-service` 已实现且 CI 通过，已升级为 Agent Protocol 兼容 server（新增 `POST /invoke`，返回 `QueryResponse`，依赖 `shared-schemas`；旧 `/api/messages` 保留为 legacy 兼容入口）。
> ✅ `deepagents/agent/config.py` 新增 `KEFU_SERVICE_URL` + `KEFU_USE_ADAPTER` 开关（默认 `false`，直连 `kefu-service:8003`）；`async_subagents.py` 增加 httpx 远程回退（外部 `deepagents` 包未安装时直连 `/invoke`）。
> ✅ `kefu-adapter` 包已从仓库移除（无调用方，默认直连 kefu-service 生效）；`deepagents/eval/run-all.py` 的 kefu 项目改默认指向 `KEFU_SERVICE_URL`（`KEFU_ADAPTER_URL` 仍可覆盖）。
> 外部 `legacy` 退役属外部运维动作，与仓库代码无关。详见 `kefu-service/main.py` 顶部注释与 README「已知待拍板项」。

---

## 6. 目录结构变化

### deepagents 侧新增

```
deepagents/
├── agent/
│   ├── main_agent.py              # 改：get_main_agent() 48-57 行 subagents 扩展 + TodoListMiddleware + RubricMiddleware
│   ├── prompts.py                 # 改：扩展为加载 prompt/ 下所有 .yaml（当前只加载 prompts.yml）
│   ├── async_subagents.py         # 新：3 个 AsyncSubAgent 定义（Phase 2，Agent Protocol）
│   ├── config.py                  # 新：子服务 Agent Protocol 地址/模式配置
│   ├── intent/                    # 新：L1+L2 意图识别（Phase 3）
│   │   ├── classifier.py          #   L1 embedding+原型余弦
│   │   ├── llm_judge.py           #   L2 LLM 细判
│   │   ├── cost_router.py         #   成本路由（Phase 6）
│   │   └── prototypes.json        #   5 类原型向量（来源独立于评测集）
│   ├── rewrite/                   # 新：query 改写（Phase 3）
│   │   ├── rewrite_node.py        #   指代消解+standalone
│   │   └── subquery_decompose.py  #   子问题分解
│   ├── cache/                     # 新：分层语义缓存（Phase 5）
│   │   ├── semantic_cache.py
│   │   ├── layers.py              #   L1/L2/L3
│   │   ├── singleflight.py
│   │   └── config.py
│   └── tracing/
│       └── langfuse_adapter.py    # 新：Langfuse 适配（Phase 0）
├── tools/                           # 已有顶层 tools/（非 agent/tools/），不变
│   ├── zhiku_tools.py
│   ├── _timeout.py
│   └── ...（9 个已有工具文件）
├── gateway/                        # 新：限流/降级/安全/灰度（Phase 6，避免与框架 middleware 参数撞名）
│   ├── rate_limit.py
│   ├── circuit_breaker.py
│   ├── input_guard.py
│   ├── output_guard.py
│   └── gray.py
├── prompt/                         # 注意：单数 prompt/（非 prompts/）
│   ├── prompts.yml                # 扩：planner 指令
│   ├── intent.yaml                # 新（Phase 3）
│   └── rewrite.yaml               # 新（Phase 3）
├── eval/
│   ├── golden.jsonl               # 扩：全项目评测集
│   ├── run-all.py                 # 新：全量评测
│   └── run-eval.py                # 已有：deepagents 评测
├── docs/
│   ├── refactor-plan.md           # 本文档
│   └── spike-todolist-middleware.md # 新：Phase 0 spike 报告
└── docker-compose.yml             # 扩：网关 + valkey + langfuse（单一 compose，D11）
```

### 新增独立服务/包

```

├── wenda-adapter/                  # 新：wenda /api/query 适配器（Phase 1，薄层）
│   ├── main.py
│   └── Dockerfile
├── kefu-adapter/                  # 新：legacy REST 适配器（Phase 1，薄层）
│   ├── main.py
│   └── Dockerfile
├── kefu-service/                  # 新：deepagents 重写客服（Phase 7）
│   ├── agent/
│   │   ├── flows/                 # Flow 重表达
│   │   └── graph_rag.py
│   └── ...
└── shared-schemas/                # 新：统一 Pydantic schema（Phase 1）
    └── api_schemas.py
```

---

## 7. 依赖与基础设施增量

### Python 依赖增量（deepagents 侧）

| 包 | 用途 | Phase | 备注 |
|----|------|-------|------|
| `langfuse` | trace + eval | 0 | 新增，自部署，MIT |
| `valkey` | 缓存客户端 | 5 | 新增，API 兼容 redis-py，BSD |
| `tenacity` | 熔断/重试 | 6 | **已有** `requirements.txt:113`，直接复用 |
| `httpx` | HTTP 调子服务 | 2 | **已有** `requirements.txt:39`，直接复用 |

### 基础设施增量

| 组件 | 用途 | 镜像 | Phase | 必需 |
|------|------|------|-------|------|
| Valkey 9.1.1 + valkey-search | 语义缓存 + 向量检索 | `valkey/valkey-bundle:9.1.2`（预装 search 1.2.1） | 5 | Phase 5 |
| Langfuse + ClickHouse | trace + eval + prompt mgmt | 官方 docker-compose | 0 | Phase 0（开发期可 no-op 降级） |

**子服务依赖不变**：wenda 仍需 MySQL+ES+Qdrant，zhiku 仍需 Milvus+Neo4j，kefu 仍需 Neo4j+BGE。**按需起服务**，不用客服就不起 kefu。

### docker-compose 编排（最终态）

```yaml
# deepagents/docker-compose.yml（扩展后，单一 compose，D11）
services:
  gateway:           # deepagents 网关
    build:
      context: ..      # （与现有 compose 一致）
      dockerfile: deepagents/Dockerfile
    ports: ["8000:8000"]
  valkey:            # 语义缓存（Phase 5）
    image: valkey/valkey-bundle:9.1.2
    ports: ["6379:6379"]
  langfuse:          # 可观测（Phase 0）
    image: langfuse/langfuse:latest
    depends_on: [clickhouse]
  clickhouse:        # Langfuse 后端（官方 docker-compose 已含）
    image: clickhouse/clickhouse:latest
  # 子服务按需启动（wenda/zhiku/kefu 各自独立 compose）
```

---

## 8. 风险与回滚

| 风险 | 影响 | 缓解 | 回滚 |
|------|------|------|------|
| Phase 4 TodoListMiddleware API 变动 | 主管行为漂移 | **Phase 0 spike 前置验证**；影子流量对比 | 关闭 middleware，回退隐式委派 |
| 语义缓存脏命中 | 返回错误答案 | `kb_versions` 失效 + 阈值 0.92 + 采样审核 + trace_id 溯源 | `cache_enabled=false` 全穿透 |
| 灰度期间缓存脏命中 | 灰度用户看到旧链路缓存 | 缓存 key 含 `gray_pct` 维度，灰度/普通缓存隔离 | 关闭灰度或清缓存 |
| PII 进缓存 key | 隐私泄露 | **guardrail 脱敏先于缓存**（架构图已标注顺序） | 关闭缓存 |
| 子服务全挂 | 网关不可用 | Phase 2 fallback 机制（保留本地子 Agent） | 自动降级到本地 |
| kefu legacy 自研框架无社区维护 | 长期维护风险 | Phase 7 迁移到 deepagents；短期监控 | 切回 legacy（保持运行） |
| Valkey search 模块编译需 GCC 12+ | 部署受阻 | 用 **`valkey/valkey-bundle:9.1.2`** 预编译镜像（含 search 1.2.1） | 退回 Redis 7.2（最后 BSD 版本） |
| Langfuse ClickHouse 内存大 | 开发机资源不足 | 生产部署给足内存；**开发期 trace 降级 no-op**（复用 agent-core） | 关闭 trace，旁路无影响 |
| 改造周期长 | 交付压力 | 7 Phase 独立上线，每 Phase 有独立业务价值 | 最小上线 M1（Phase 0+1） |
| Phase 7 数月级工程 | 长周期交付 | 渐进迁移（先 3 Flow 灰度）；legacy 保持运行不阻塞 | 切回 legacy |

---

## 9. 里程碑与验收

| 里程碑 | Phase | 交付 | 业务价值 | 验收标准 |
|--------|-------|------|---------|---------|
| **M1** | 0+1 | 可观测 + 4 服务独立部署 + spike | 度量基线 + 服务化 | 4 服务 `/health` 全绿；trace 上报（或 no-op）；评测基线报告；spike 报告 |
| **M2** | +2 | deepagents 联邦网关 | 统一入口 + 降级容错 | 路由到 3 子服务；kill 子服务自动降级 |
| **M3** | +3 | 意图识别 + 改写 | 路由准确率 ≥95% + 召回提升 | 评测集意图准确率 ≥95%；改写后召回 +≥5% |
| **M4** | +4 | Planner + Reflexion | 跨域复杂任务自动拆解 | 复杂 query 自动拆步；失败 step 重规划 |
| **M5** | +5 | 语义缓存 | 重复 query <1ms 返回 | L1 命中 <1ms；L2 命中 <10ms；命中率上报 |
| **M6** | +6 | 横切能力 | 限流/成本/安全/灰度/多租户 | 限流 429；**评测集分布下成本降 ≥30%**；guardrail 拦截 |
| **M7** | +7 | kefu 迁移 | 消除自研框架风险，统一栈 | 新 kefu 意图准确率 ≥ legacy；Flow 全覆盖 |

**推荐落地顺序**：M1 → M2 → M3 → M5 → M4 → M6 → M7
- M5（缓存）排在 M4（规划）前，因为缓存价值立竿见影且独立（仅依赖 M3 的意图+改写）
- M4（规划）依赖 M3（意图）+ Phase 0 spike，改动较大，放后
- M7（kefu 迁移）最后，数月级长期项

---

## 10. 与 AGENTS.md 约束一致性

| 约束 | 方案遵守情况 |
|------|------------|
| "勿修改子项目代码逻辑" + deepagents/zhiku 例外 | ✅ 方案主要改 deepagents（已例外），zhiku 仅加 Langfuse callback，wenda/kefu 只加 Dockerfile/adapter 不改业务代码 |
| "不合并代码" | ✅ **默认跨服务 HTTP**，同进程嵌套标注为不推荐（违反此约束） |
| "勿提交真实 .env" | ✅ 所有新增配置走 `.env.example` + 环境变量 |
| "勿提交大二进制资产" | ✅ Valkey/Langfuse 用 Docker 镜像，不入库 |
| "勿在此目录创建 wiki 内容" | ✅ 本文档是技术方案非 wiki 知识，放 `docs/` |
| Python 3.11+（>=3.11，全仓 requires-python 一致）/ LF line endings | ✅ 所有新增代码遵守 |
| kebab-case 脚本名（PREFERENCE_3） | ✅ `run-all.py` / `semantic_cache.py` / `circuit_breaker.py` 等均 kebab-case |
| async/await + uv（PREFERENCE_5） | ✅ 全部 async；依赖用 uv 管理（FastAPI/Deep Agents 均用 uv） |
| 中文为主（PREFERENCE_6） | ✅ 本文档中文 |

---

## 11. 审核修订记录（完整追溯）

### 第一轮：doc-expert 7 维度审核

#### P0-1：Phase 4 架构决策错误（已修订）

- **初版**：Phase 4 "将主管从 `create_deep_agent` 迁移到 LangGraph 自建图"
- **审核发现**：Deep Agents 是 LangGraph 官方高层封装（LangGraph README 原文推荐），27.6k stars，MIT 协议，内置 planning/subagents/context mgmt/skills/human-in-the-loop
- **修订**：Phase 4 改为"扩展非重写"——启用 `TodoListMiddleware` + 自定义 planner prompt + Reflexion 扩展点

#### P1-1：Redis Stack 协议风险（已修订）

- **初版**：Phase 5 "部署 Redis Stack（含向量检索）"
- **审核发现**：Redis 2024-03 协议从 BSD 变为 RSALv2/SSPLv2（非 OSI 开源）。Valkey 是 LF 托管的开源 fork（BSD-3），valkey-search 命令与 RediSearch 1:1 兼容
- **修订**：改用 Valkey 9.1.1 + valkey-search

#### P1-2：kefu legacy 自研框架无维护（已修订）

- **初版**：kefu 保持 Rasa 独立（**事实错误：kefu 不是 Rasa**）
- **审核发现**：kefu 用的是 legacy 自研框架（模仿 Rasa 架构，但 `requirements-legacy.txt` 无 rasa 包，`legacy/` 无 `import rasa`，`flow_order.yml` 注释写"适配legacy框架语法"）
- **修订**：短期保持 legacy 独立；新增 Phase 7 长期迁移到 deepagents

#### P2-1：L1 分类器选型（已修订）

- **初版**：用 BGE-reranker
- **修订**：改用 embedding + 原型向量余弦相似度

#### P2-2：Langfuse ClickHouse 措辞（已修订）

- **初版**："2026-01 加入 ClickHouse"
- **修订**：改为"自部署依赖 ClickHouse（官方 docker-compose 已含）"

#### P2-3：熔断器依赖（已修订）

- **初版**：用 pybreaker
- **修订**：改用 tenacity（**已有依赖** `requirements.txt:113`）

### 第二轮：agent1 代码实况审核

#### A0-1：Phase 2 路由机制描述错误（已修订）

- **初版**：Phase 2 写"main_agent.py:118-126 的 subagent_type 路由扩展为双模式"
- **审核发现**：实测 `main_agent.py`——48-57 行 `create_deep_agent(subagents=[...])` 才是路由入口；117-126 行是 `if node_name == 'model'` 内的流式事件采集/监控（`monitor.report_assistant`），不是路由逻辑
- **修订**：Phase 2 路由入口改为 `get_main_agent()` 48-57 行的 `subagents=[...]` 参数

#### A0-2：同进程嵌套违反"不合并代码"（已修订）

- **初版**：§3 "Phase 2 优先同进程嵌套"
- **审核发现**：同进程 `import` wenda/zhiku 代码 = 引入依赖 = 合并代码，违反 AGENTS.md 约束
- **修订**：**默认跨服务 HTTP**；同进程标注为"需引入对方代码作依赖，属合并形式，不推荐"

#### A1-1：prompt/ 路径不一致（已修订）

- **初版**：§6 目录结构写 `prompts/`（复数）
- **审核发现**：实测 `deepagents/prompt/prompts.yml`（单数 `prompt/`）
- **修订**：全文档统一为 `prompt/`

#### A1-2：缓存 key 缺维度（已修订）

- **初版**：`hash(intent + rewritten_query + kb_version + tenant_id)`
- **审核发现**：单一 `kb_version` 无法覆盖多子服务 KB；缺 `gray` 维度
- **修订**：改为 `hash(intent + rewritten_query + kb_versions + tenant_id + gray_pct)`，`kb_versions` 按子服务维度

#### A1-3：TodoListMiddleware spike 前置（已修订）

- **初版**：Phase 4 内"需验证 0.7.5 middleware API 兼容性"
- **审核发现**：README 已明确"需验证后加"，应先 spike 再进 Phase 4
- **修订**：spike 前置到 Phase 0，产出 `spike-todolist-middleware.md`

#### A1-4：prompts.py 加载机制未说明（已修订）

- **初版**：新增 .yaml 未说明加载方式
- **审核发现**：`prompts.py` 当前只加载 `prompts.yml`
- **修订**：补 `prompts.py` 改造说明——扩展为加载 `prompt/` 下所有 .yaml

#### A2-1：基线定义模糊（已修订）

- **初版**：Phase 0 "基线报告产出"
- **审核发现**：无 API key 时无法实跑
- **修订**：明确——无 key 为静态标注报告，有 key 为实跑报告

#### A2-2：成本承诺绝对化（已修订）

- **初版**："成本降低 ≥30%"
- **修订**：改为"在评测集分布下成本降 ≥30%"

#### A2-3：Phase 7 无工期估（已修订）

- **初版**：Phase 7 无投入估
- **修订**：标注"数月级工程"

#### A2-4：原型向量同源污染（已修订）

- **初版**：原型向量来源未限定
- **修订**：明确"来源必须独立于评测集"

#### A2-5：脱敏与缓存顺序（已修订）

- **初版**：PII 脱敏与缓存先后未明确
- **修订**：架构图标注 guardrail → cache 顺序；缓存 key 用脱敏后 query

#### A2-6：开发机无 Docker（已修订）

- **初版**："开发用 Langfuse Cloud 免费层"
- **审核发现**：README 声明"无 Docker 环境"
- **修订**：开发期 trace 降级 no-op（复用 agent-core 已有 no-op），ClickHouse 仅生产起

### 第三轮：源码级真实验证（pip install + import + inspect）

> 方法：创建临时 venv，`pip install deepagents==0.7.5 valkey`，实际 `import` + `inspect.signature()` 验证 API 签名

| 编号 | 严重度 | 问题 | 修订 |
|------|--------|------|------|
| V0-1 | 🔴 导入路径错误 | 方案暗示 `TodoListMiddleware` 是 deepagents 0.7.5 自有 API | 实际来自 `langchain.agents.middleware`（langchain 1.3.14），通过 `create_deep_agent(middleware=[...])` 传入 |
| V1-1 | 🟠 措辞不准 | §1 写"SQLite checkpointer"注明"需单独安装" | `langgraph-checkpoint-sqlite>=2.0.0` **已在 `requirements.txt:56`**，正常安装下不会 fallback；fallback 代码保留作防御性降级，但"需单独安装"表述与依赖实况不符，已修正 |

**源码级已验证通过**：
- `create_deep_agent` 签名含 `model/tools/system_prompt/middleware/subagents/skills/memory/checkpointer/store` 等参数 ✓
- `TodoListMiddleware`：`from langchain.agents.middleware import TodoListMiddleware`，`__init__(self, *, system_prompt, tool_description)`，提供 `write_todos` 工具 ✓
- `valkey` 包：`Valkey` 类 354 方法，含 ft/search ✓
- `langgraph.checkpoint.memory.InMemorySaver` 存在 ✓
- `langgraph.checkpoint.sqlite` 需单独装 `langgraph-checkpoint-sqlite`（代码已有 try-except fallback）✓
- 版本：deepagents 0.7.5 / langgraph 1.2.10 / langchain 1.3.14 / tenacity 9.1.4 / httpx 0.28.1 全部确认 ✓

### 第四轮：agent2 架构审核 + 源码级 deepagents 内置能力验证

> 方法：agent2 交叉审核 + pip install deepagents + inspect RubricMiddleware / AsyncSubAgent 源码

| 编号 | 严重度 | 问题 | 修订 |
|------|--------|------|------|
| W0-1 | 🔴 重复造轮子 | Phase 4 自己写 `planner/reflexion.py` | deepagents 内置 **`RubricMiddleware`**（"self-evaluated iteration against a rubric"，`max_iterations=3` + `CriterionFail.gap`），直接用 |
| W0-2 | 🔴 未用官方机制 | Phase 2 手写 `httpx.AsyncClient` 包 tool | deepagents 内置 **`AsyncSubAgent` + Agent Protocol**，子服务实现 Agent Protocol 即可被自动连接 |
| W1-1 | 🟠 选型对照缺失 | 未对照 A2A 协议 | A2A（Google→LF, v1.0, Apache-2.0）是 agent-to-agent 标准协议；deepagents 用的是 **Agent Protocol**（LangChain 自有），两者定位类似但不同。Phase 1 shared-schemas 可对照 A2A 长期演进 |

**agent2 不准确处**：
- "A2A 是标准答案" → deepagents 实际用 Agent Protocol（非 A2A），两者不同
- "langgraph-supervisor 最该精读对照" → 官方 README 已标记"不推荐用于新项目"，deepagents 是替代品

### 第五轮：agent3 代码实况审核 + 决策点落地

> 方法：agent3 全仓库 grep + webfetch valkey-bundle + 逐条核实代码实况

| 编号 | 严重度 | 问题 | 修订 |
|------|--------|------|------|
| X0-1 | 🔴 事实硬伤 | **kefu 不是 Rasa**——`requirements-legacy.txt` 无 rasa 包，`legacy/` 无 import rasa，是模仿 Rasa 架构的自研框架 | 全文档 Rasa→legacy（21 处），Phase 7 迁移对象改为 legacy |
| X0-2 | 🔴 违规 | wenda 不在 AGENTS.md 例外清单，Phase 1 改 wenda 代码违规 | 新建 `wenda-adapter` 薄层转发，wenda 快照零改动 |
| X0-3 | 🔴 事实错误 | wenda 没有 Dockerfile，Phase 1 写"wenda/zhiku 已有"错误 | 改为"wenda-adapter 新建、zhiku 已有" |
| X1-1 | 🟠 伪托约束 | §10 引用"不合并代码"为 AGENTS.md 约束，但不存在 | **已写入 AGENTS.md**（D3）+ 边界表更新（D7） |
| X1-2 | 🟠 部署错误 | 裸 `valkey/valkey:9.1.1` 不含 libsearch.so | 改用 **`valkey/valkey-bundle:9.1.2`**（预装 search 1.2.1） |
| X1-3 | 🟠 返工矛盾 | Phase 3/5 embedding 后端切换需重建原型向量 | **固定本地 sentence-transformers，与 Phase 5 解耦，永不切换** |
| X1-4 | 🟠 容器化问题 | shared-schemas `pip install -e` 在容器下不可行 | 改为构建时非 editable 安装 |
| X2-1 | 🟡 命名撞车 | `middleware/` 与框架 `middleware=[...]` 参数撞名 | 改为 **`gateway/`** |
| X2-2 | 🟡 口径不明 | "成本降 ≥30%"不可验收 | 写明口径：评测集全量实跑对比 token 总成本 |
| X2-3 | 🟡 样本来源 | 评测集 200 样本纯人工成本高 | LLM 合成 + 人工审核标注 |

### 第六轮：agent3 第二轮补充审核 + 事实订正

| 编号 | 严重度 | 问题 | 修订 |
|------|--------|------|------|
| Y0-1 | 🔴 协议不兼容 | wenda `/api/query` 是 SSE 流式（`text/event-stream`），与目标 JSON schema 不兼容 | Phase 1 明确 wenda-adapter 需做**流→JSON 适配**（消费 SSE → 聚合 JSON），非简单 schema 对齐 |
| Y0-2 | 🔴 安全缺位 | deepagents 审主侧无鉴权，子服务 API Key 等于公开 | Phase 1 补充 **deepagents 入站 API Key 鉴权**（复用 `SecurityGuardsMiddleware`） |
| Y0-3 | 🔴 安全缺位 | 多租户 `tenant_id` 隔离未闭环，不支持租户的子服务缓存放行会串数据 | Phase 6 补充**租户隔离边界**：不支持 tenant_id 的服务禁用缓存 |
| Y1-1 | 🟠 资产未利用 | zhiku 已有三级 `/health`/`/health/live`/`/health/ready`，方案未复用 | Phase 1 明确复用 zhiku 三级端点，不另起 |
| Y1-2 | 🟠 验收模糊 | M1 trace "上报或 no-op"把两种互斥方案塞进验收 | 明确**三态**：开发 no-op / CI Langfuse / 生产 ClickHouse，分别验收 |
| Y1-3 | 🟠 传播缺失 | 跨服务 trace 串联未说明，联邦架构下"全链路"名不副实 | 补充 **W3C traceparent** 跨服务上下文传播 |
| Y2-1 | 🟡 断言未定 | wenda SSE 流式评测集如何断言正确性未说明 | Phase 0 明确：对**最终合成文本**断言（消费流→聚合→比对期望） |

**agent3 事实订正**：
- Valkey 9.1.1 属实（撤销上轮质疑）
- zhiku 自带三级 /health（方案未利用 → 已修订复用）
- wenda 是 SSE 流式 + 无 /health（方案低估工作量 → 已修订明确）

**agent3 不准确处**：
- #28"同进程嵌套 §3 仍主推" → v3 已改为"默认 AsyncSubAgent + Agent Protocol"，同进程标注"不推荐"，当前 v3.4 无矛盾
- #29"CompiledStateGraph 直接传入" → 已标注"不推荐"，wenda/zhiku 是 HTTP 服务非 LangGraph 库，同进程在代码层面不支持

### 第七轮：agent3 第二轮深挖审核（计划内部自洽性 + 代码引用核实）

> 方法：agent3 逐条核实上轮"待验证"项 + 计划内部路径/编排矛盾 + Phase 0/2/4/6/7 代码引用

| 编号 | 严重度 | 问题 | 修订 |
|------|--------|------|------|
| P1-6 | 🟠 内部矛盾 | docker-compose 三处矛盾：§6 根目录 vs §7 `docs/` vs Phase 0/5 分散 compose | **D11：单一 compose 放 deepagents 根目录**（保留现有 `build: ..` context），删除 docs/ 下分散 compose 设计 |
| P1-7 | 🟠 路径错误 | §6 目录结构把 `tools/` 画在 `agent/tools/` 下，实际在顶层 `deepagents/tools/` | 目录结构修正：`tools/` 提到顶层 |
| P1-8 | 🟠 路径错误 | Phase 6 多租户写 `agent/context.py`，实际在 `api/context.py` | 修正为 `deepagents/api/context.py` |
| P1-9 | 🟠 概念混用 | 架构图标 `HTTP tool`，但远程子服务应以 subagent 形态包装才能复用 monitor 链路 | 架构图改为 `Agent Protocol`（subagent 委派）；Phase 2 改动④明确 subagent 形态（**D14**） |
| P2-6 | 🟡 spike 目标 | TodoListMiddleware 归属表述"非 deepagents 自有"可能不准（0.7.x 默认栈或已含） | **D12：spike 首问"0.7.5 默认栈是否已挂载"**，再决定 Phase 4 是"启用"还是"调参" |
| P2-7 | 🟡 措辞不准 | V1-1 写"需单独安装"，但 `requirements.txt:56` 已有 `langgraph-checkpoint-sqlite>=2.0.0` | 修正措辞：已有依赖，fallback 保留作防御性降级 |
| P2-8 | 🟡 粒度错误 | Phase 4 ⑥"移除 enable_thinking=False"是全局默认，移除会让所有调用打开思考链 | **D13：不移除全局默认，按调用点 extra_body 透传** |
| P2-9 | 🟡 待验证 | Phase 7 ⑤"kefu 原有评测数据迁移"——kefu 无评测数据集 | 改为"kefu 无评测数据集，需新建" |

**P0-5 不成立**：方案 v3.5 已写"9 种命令 + 3 个 Flow"（第 257 行），搜索"12 类意图"无结果，此问题在 v3.5 中已不存在。

**决策点 D11-D14 落地**：
- D11：单一 compose 放 `deepagents/docker-compose.yml`（根目录），删除 `docs/docker-compose.langfuse.yml` 和 `docs/docker-compose.valkey.yml` 分散设计
- D12：Phase 0 spike 首问"0.7.5 默认栈是否已挂载 TodoListMiddleware"
- D13：zhiku `enable_thinking=False` 不移除全局默认，按调用点 `extra_body` 透传
- D14：远程子服务以 subagent 形态包装（内部挂 httpx tool），复用 task 委派 + monitor 链路

---

## 12. 技术栈核实记录（2026-08-10 实测）

| 技术 | 核实方式 | 结果 |
|------|---------|------|
| LangGraph | webfetch github.com/langchain-ai/langgraph | 39.4k stars，7,039 commits，活跃，MIT |
| Deep Agents | webfetch github.com/langchain-ai/deepagents | 27.6k stars，3,225 commits，LangGraph 官方封装，MIT，内置 planning/subagents |
| Langfuse | webfetch github.com/langfuse/langfuse | 32.8k stars，8,438 commits，自部署依赖 ClickHouse，MIT |
| FastAPI | webfetch github.com/fastapi/fastapi | 101.5k stars，7,651 commits，uv 管理，MIT |
| Valkey | webfetch valkey.io + github.com/valkey-io/valkey | 26.8k stars，13,968 commits，LF 托管，BSD-3，9.1.1（2026-07-21） |
| valkey-search | webfetch github.com/valkey-io/valkey-search | 140 stars，653 commits，BSD-3，命令兼容 RediSearch，HNSW+KNN+hybrid |
| legacy 自研框架 | grep requirements-legacy.txt + legacy/*.py | **kefu 不是 Rasa**：无 rasa 包、无 import rasa，是模仿 Rasa 架构的自研框架，已有 FastAPI server + `/api/messages` |
| deepagents 代码实况 | read main_agent.py / requirements.txt | 路由入口在 48-57 行；tenacity 9.1.4 已在 `requirements.txt:113`；httpx 0.28.1 已在 `requirements.txt:39` |
| kefu 文件实况 | glob zhanggui-kefu | `ecs_demo/addons/information_retrieval.py` ✓；`ecs_demo/data/flows/` 下 3 个 yml ✓ |
| zhiku 文件实况 | read zhanggui-zhiku/app/lm/lm_utils.py | 第 35 行 `extra_body={"enable_thinking": False}` ✓ |
| **deepagents API 签名** | **pip install + inspect.signature** | `create_deep_agent` 含 `subagents/middleware/checkpointer/tools/model` 参数 ✓ |
| **TodoListMiddleware** | **pip install + import** | 来自 `langchain.agents.middleware`（非 deepagents），`__init__(*, system_prompt, tool_description)`，提供 `write_todos` ✓ |
| **valkey 包** | **pip install + import** | `Valkey` 类 354 方法，含 ft/search ✓ |
| **langgraph sqlite** | **pip install + import** | `langgraph.checkpoint.sqlite` 需单独装 `langgraph-checkpoint-sqlite`，代码有 fallback ✓ |
| **PyPI 版本** | **Invoke-RestMethod pypi.org** | deepagents 0.7.5 / langgraph 1.2.10 / langchain 1.3.14 / tenacity 9.1.4 / httpx 0.28.1 / langfuse 4.14.3 / fastapi 0.141.1 |
| **RubricMiddleware** | **pip install + inspect** | deepagents 内置 Reflexion：`__init__(*, model, system_prompt, tools, max_iterations=3, on_evaluation)`，"drives self-evaluated iteration against a rubric"，含 `CriterionPass/CriterionFail(gap)` ✓ |
| **AsyncSubAgent** | **pip install + inspect** | deepagents 内置远程子 agent：连接 Agent Protocol-compliant server，`middleware/async_subagents.py` 8 处引用 Agent Protocol ✓ |
| **langgraph-supervisor** | **webfetch GitHub** | 1.6k stars，但官方 README 写"now recommend using supervisor pattern directly via tools rather than this library"——已不推荐，deepagents 是替代 ✓ |
| **A2A 协议** | **webfetch a2a-protocol.org** | Google→LF, v1.0, Apache-2.0，agent-to-agent 通信标准；明确"Not a sub-agent or tool-call protocol"；与 Agent Protocol 不同 ✓ |
| **kefu 不是 Rasa** | **grep requirements-legacy.txt + legacy/*.py** | 零 rasa 包、零 import rasa，是模仿 Rasa 架构的自研框架 legacy ✓ |
| **valkey-bundle** | **webfetch hub.docker.com/r/valkey/valkey-bundle** | `valkey/valkey-bundle:9.1.2` 含 valkey 9.1.1 + search 1.2.1 + json + bloom + ldap 预装 ✓ |
| **wenda 无 Dockerfile** | **glob zhanggui-wenda/**/Dockerfile*** | 零结果 ✓ |
| **AGENTS.md "不合并代码"** | **D3 写入** | 已正式写入 AGENTS.md 禁止行为 + 边界表新增 4 行 ✓ |
| **P0-5 不成立** | **grep "12类意图" refactor-plan.md** | 零结果，v3.5 已写"9 种命令 + 3 个 Flow" ✓ |
| **P1-6 compose 矛盾** | **read docker-compose.yml + grep** | 现有 compose 在根目录 `build: ..`；§7 注释 `docs/` + `build: ../..` 矛盾已修正 ✓ |
| **P1-7 tools/ 路径** | **glob deepagents/tools/** | 9 文件在顶层 `deepagents/tools/`，非 `agent/tools/` ✓ |
| **P1-8 context.py 路径** | **glob deepagents/**/context.py** | `api/context.py` 存在，`agent/context.py` 不存在 ✓ |
| **P2-7 sqlite 已有** | **read requirements.txt:56** | `langgraph-checkpoint-sqlite>=2.0.0` 已在依赖中 ✓ |
| **P2-9 kefu 无评测** | **glob zhanggui-kefu/**/eval*** | 零结果（仅 `information_retrieval.py`，非评测） ✓ |

> Stars/版本为 2026-08-10 webfetch 快照，以安装时 `uv lock` 锁定版本为准。

---

*本方案经 8 轮审核（doc-expert + agent1 + 源码级验证 + agent2 + agent3 三轮 + agent3 第二轮深挖）+ 17 决策点落地后修订落盘（v3.6）。已于 2026-08-11 全量落地（Phase 0-7），审核报告见 docs/audit-report.md。*
