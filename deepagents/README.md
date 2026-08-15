# deepagents 多智能体编排项目

> 基于多智能体项目改造而成的生产级多智能体编排系统。
> 联邦网关 + 3 子服务（wenda/zhiku/kefu），补齐思考规划 / 意图识别 / 意图改写 / 语义缓存 4 大能力。
> 详见 `docs/refactor-plan.md` v3.6 + `docs/audit-report.md`。

## 架构

```
用户 → deepagents-gateway（联邦网关）
         ├── guardrail（PII 脱敏 + 注入检测）
         ├── L1 意图分类（embedding+原型余弦）→ L2 LLM 细判
         ├── Query 改写（指代消解+子问题分解）
         ├── 语义缓存（Valkey L1/L2/L3）
         ├── Planner（TodoListMiddleware）+ Reflexion（RubricMiddleware）
         └── AsyncSubAgent × 3（Agent Protocol）
              ├── wenda-service（Text-to-SQL）
              ├── zhiku-service（RAG 知识库）
              └── kefu-service（客服）
横切：Langfuse trace + tenacity 限流降级 + 成本路由 + 灰度 + 多租户
```

与 [zhanggui-zhiku](../zhanggui-zhiku/) 共享 `agent-core` 内核，形成「编排深做 vs 检索深做」的差异化互补。

## 快速开始

```bash
python -m venv .venv && source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env  # 填入真实 key（不要提交 .env！）

python -m api.server  # 启动 FastAPI，默认 :8000
```

### 环境变量

| 变量 | 必填 | 说明 |
|------|------|------|
| `OPENAI_API_KEY` | ✅ | DashScope API Key |
| `OPENAI_BASE_URL` | ✅ | DashScope 兼容端点 |
| `LLM_QWEN_MAX` | ✅ | 主模型名称 |
| `LLM_QWEN_FALLBACK` | 可选 | 备用模型名称（主模型不可用时自动降级） |
| `OPENAI_FALLBACK_BASE_URL` | 可选 | 备用模型端点（默认同主模型） |
| `OPENAI_FALLBACK_API_KEY` | 可选 | 备用模型 API Key（默认同主模型） |
| `TAVILY_API_KEY` | ✅ | Tavily 搜索 API |
| `MYSQL_*` | ✅ | MySQL 连接信息（生产环境应使用只读用户） |
| `MYSQL_POOL_SIZE` | 可选 | DB 连接池大小（默认 5） |
| `MYSQL_POOL_RESET_SESSION` | 可选 | 连接归还时重置（默认 true） |
| `ZHIKU_API_URL` | 可选 | zhiku 检索服务地址（知识库子 Agent） |
| `ZHIKU_API_KEY` | 可选 | zhiku API Key |
| `API_KEY` | 可选 | 服务鉴权 Key（空则不鉴权） |
| `ALLOWED_ORIGINS` | 可选 | CORS 允许源（逗号分隔，默认 localhost:3000） |

## 改造历程

本项目由只读快照改造而来，改造分四阶段 + 生产化 Phase 0-7（详见 [Issue #120](../../issues/120) + `docs/refactor-plan.md`）。

### 已完成

**阶段一~四 · 基础改造**（见 CHANGELOG [1.0.0]-[1.0.1]）
- ✅ P0 止血（SQL 防护/CORS/脱敏/鉴权）+ agent-core 接入 + 工程骨架 + 可靠性 + 文档

**Phase 0-7 · 生产化改造**（CHANGELOG [2.0.0]）
- ✅ Phase 0：Langfuse 三态 trace + W3C traceparent 传播 + 评测集 200 题 + spike 报告
- ✅ Phase 1：wenda-adapter（SSE→JSON，已于 2026-08 退役，由 wenda-data-agent 直连替代）+ kefu-adapter（已移除，迁移至 kefu-service 直连）+ shared-schemas 统一 schema
- ✅ Phase 2：AsyncSubAgent 联邦网关 + AGENT_MODE 切换 + 健康探活降级
- ✅ Phase 3：L1 embedding+原型余弦 + L2 LLM 细判 + Query 改写 + 子问题分解
- ✅ Phase 4：TodoListMiddleware + RubricMiddleware（扩展非重写 deepagents）
- ✅ Phase 5：Valkey 分层缓存（L1 精确 + L2 语义 HNSW + L3 检索 + NullCache + singleflight）
- ✅ Phase 6：限流/熔断/guardrail/灰度/成本路由/多租户
- ✅ Phase 7：kefu-service（atguigu_ai → deepagents + LangGraph，9 命令 + 3 Flow + GraphRAG）

### 待做 / 已知限制

- ⬜ DB 子 Agent 仍连原库 pharma_db（会展库需另行准备）
- ⬜ 评测集 200 题为 LLM 合成 + 模板生成，需人工审核标注（golden 10 题保留作核心回归）
- ℹ️ Phase 7 kefu-service 用配置驱动模拟数据，生产环境需替换为真实 DB 查询

## 诚实边界

| 维度 | 状态 |
|------|------|
| **业务叙事** | 统一为会展领域，prompt 已改写；DB 子 Agent 仍连原库（pharma_db），README 已声明 |
| **知识库内容** | zhiku 当前仅 50 条烫金机测试数据，会展语料待导入 |
| **agent-core** | ✅ tracing + logging + SecurityGuardsMiddleware + SqliteSaver + 工具超时隔离 + DB 连接池 + 模型 fallback + zhiku 健康探活降级 |
| **Phase 0-7** | ✅ 7 Phase 全部实现（见 `docs/audit-report.md`），所有新功能默认关闭，环境变量渐进启用 |
| **评测集** | 200 题（10 人工 + 190 合成），需人工审核标注 |
| **kefu-service** | Phase 7 已补全（9 命令 + 3 Flow + GraphRAG），用配置驱动模拟数据 |
| **测试** | 24 个单元测试 + M7 验收测试（10/10 对话 + 5/5 GraphRAG） |
| **Docker** | docker-compose 含 web+mysql+zhiku+langfuse+clickhouse+valkey，未本地构建验证（无 Docker 环境） |

## 项目结构

```
deepagents/
├── agent/
│   ├── main_agent.py         # 主管 Agent（懒初始化 + SQLite checkpointer）
│   ├── llm.py                # LLM 模型初始化
│   ├── prompts.py            # YAML 配置加载
│   └── subagents/            # 3 个子 Agent 定义
├── api/
│   ├── server.py             # FastAPI + WebSocket + 鉴权
│   ├── monitor.py            # ToolMonitor 单例 + ConnectionManager
│   └── context.py            # ContextVar 会话隔离
├── tools/
│   ├── tavily_tool.py        # Tavily 联网搜索
│   ├── db_tools.py           # MySQL 查询（sqlparse 三层防护）
│   ├── zhiku_tools.py        # zhiku 知识库检索（替代 ragflow_tools.py）
│   ├── markdown_tools.py     # Markdown 生成
│   ├── pdf_tools.py          # PDF 转换
│   ├── upload_file_read_tool.py
│   ├── sql_validation.py     # SQL 校验纯函数（无 mysql 依赖，供测试直接导入）
│   └── _timeout.py           # 工具超时隔离装饰器（asyncio.wait_for wrapper）
├── prompt/prompts.yml         # 全量提示词配置（会展业务叙事）
├── utils/path_utils.py        # 路径安全工具
├── tests/unit/                # 单元测试（24 tests）
├── pyproject.toml             # 项目配置 + ruff
├── Dockerfile                 # 容器镜像
├── docker-compose.yml         # web + mysql
├── requirements.txt           # 依赖锁定
└── .env.example               # 环境变量模板（已脱敏）
```

## 与 zhanggui-zhiku 的差异化

| 维度 | zhanggui-zhiku | deepagents |
|------|----------------|------------|
| 核心范式 | RAG 检索增强 | 多智能体编排 |
| 深挖亮点 | 检索链路、向量工程 | 委派机制、会话隔离、故障隔离 |
| 技术栈 | Milvus + BGE-M3 + LangGraph | deepagents + WebSocket + Tavily/MySQL/zhiku |
| 共享内核 | agent-core | agent-core |

面试叙事：「一个是检索深做，一个是编排深做，共享同一套生产内核。」

---

*改造自多智能体项目，基于 deepagents==0.7.5 + LangGraph 1.2.10。*
