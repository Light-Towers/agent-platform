# Changelog

All notable changes to this project are documented here.

## [2.0.0] - 2026-08-11

### 生产化改造 Phase 0-7（联邦网关 + 4 大能力补齐）

> 详见 `docs/refactor-plan.md` v3.6 + `docs/audit-report.md`

#### Phase 0 · 可观测性统一 + 评测基线 + spike
- **Langfuse 适配** (`agent/tracing/langfuse_adapter.py`): 三态设计（开发 no-op / CI Langfuse / 生产 ClickHouse），与 agent-core OTel 共存
- **W3C traceparent 传播** (`agent/tracing/trace_propagation.py`): 跨服务 trace 上下文注入/提取，无 OTel 时 no-op
- **全项目评测** (`eval/run-all.py`): 4 项目评测驱动器，支持 --project/--limit/--no-judge
- **评测集扩充** (`eval/golden.jsonl`): 10 → 200 题（LLM 合成 + 人工审核标注，覆盖 5 意图 + 复合路由）
- **spike 报告** (`docs/spike-todolist-middleware.md`): TodoListMiddleware 未挂载在 0.7.5 默认栈，Phase 4 需显式传入
- **docker-compose 扩展**: 新增 langfuse + clickhouse + valkey-bundle:9.1.2

#### Phase 1 · 服务化拆分
- **wenda-adapter** (`../wenda-adapter/`): SSE→JSON 适配层，消费 wenda SSE 流聚合 QueryResponse
- **kefu-adapter** (`../kefu-adapter/`): atguigu_ai REST 适配层，转发 /api/messages
- **shared-schemas** (`../shared-schemas/`): 统一 Pydantic schema（QueryRequest/QueryResponse/HealthResponse/IntentResult/SubagentCall）
- **deepagents 入站鉴权**: 复用 SecurityGuardsMiddleware + API_KEY

#### Phase 2 · 联邦网关
- **AsyncSubAgent** (`agent/async_subagents.py`): 3 个远程子 agent（text_to_sql/rag_query/customer_service），Agent Protocol 连接
- **模式切换** (`agent/config.py`): AGENT_MODE=local/remote，remote 时用 AsyncSubAgent + 本地 fallback
- **健康探活** (`agent/health_check.py`): daemon 线程 30s 间隔探活子服务，unhealthy 时降级
- **路由事件推送**: subservice_route 事件标记 remote/local 模式

#### Phase 3 · 意图识别 + 意图改写
- **L1 粗分类** (`agent/intent/classifier.py`): embedding + 原型向量余弦，bge-small-zh-v1.5 固定本地，<10ms
- **L2 LLM 细判** (`agent/intent/llm_judge.py`): L1 <0.8 时触发，含 clarify 反问
- **原型向量** (`agent/intent/prototypes.json`): 5 类 × 20 条，与评测集零重叠
- **Query 改写** (`agent/rewrite/rewrite_node.py`): 指代消解 + standalone question
- **子问题分解** (`agent/rewrite/subquery_decompose.py`): 一问拆多问并行
- **short-circuit**: chitchat 直出，不打下游

#### Phase 4 · 思考规划扩展
- **TodoListMiddleware** (`agent/main_agent.py`): PLANNER_ENABLED 开关，根据 spike 报告显式传入
- **RubricMiddleware** (`agent/main_agent.py`): REFLEXION_ENABLED 开关，用 deepagents 内置 Reflexion（非自写）
- **planner prompt** (`prompt/planner.yaml`): 规划指令 + rubric 评估标准

#### Phase 5 · 语义缓存
- **分层缓存** (`agent/cache/layers.py`): L1 精确（<1ms）+ L2 语义（HNSW+COSINE >0.92，<10ms）+ L3 检索结果 + NullCache 防穿透
- **singleflight** (`agent/cache/singleflight.py`): 同 query 并发只算一次
- **缓存 key** (`agent/cache/config.py`): hash(intent+query+kb_versions+tenant_id+gray_pct)，kb_versions 按子服务维度
- **Valkey 降级**: 无 valkey 包/连接失败时 no-op

#### Phase 6 · 横切能力
- **限流** (`gateway/rate_limit.py`): Token bucket，按 tenant_id 隔离
- **熔断** (`gateway/circuit_breaker.py`): CLOSED/OPEN/HALF_OPEN + fallback
- **输入 guardrail** (`gateway/input_guard.py`): PII 脱敏（5 类）+ prompt injection 检测（7 模式）
- **输出 guardrail** (`gateway/output_guard.py`): PII 泄漏检测 + 质量检查
- **灰度** (`gateway/gray.py`): user_id % 100 < gray_pct
- **成本路由** (`agent/intent/cost_router.py`): cheap/standard/premium 三级
- **多租户** (`api/context.py`): tenant_id ContextVar 隔离

#### Phase 7 · kefu 迁移
- **kefu-service** (`../kefu-service/`): atguigu_ai → deepagents + LangGraph 重写
  - 9 种命令 (`agent/commands.py`): 对应 atguigu_ai command_prompt.jinja2
  - 3 个 Flow 子图 (`agent/flows/`): order/logistics/postsale，接入真实业务服务
  - GraphRAG (`agent/graph_rag.py`): 6 步流程，配置驱动知识库
  - 业务服务 (`agent/services.py`): 订单/物流/售后查询 + 槽位提取
  - M7 验收: 10/10 对话 + 5/5 GraphRAG 全通过

## [1.0.1] - 2026-08-09

### Phase 3 · 可靠性（补全）

#### Added
- **DB 连接池** (`tools/db_tools.py`): `MySQLConnectionPool` 替代每次 `connect()`，线程安全懒初始化，`MYSQL_POOL_SIZE`/`MYSQL_POOL_RESET_SESSION` 可配置
- **模型 fallback** (`agent/llm.py`): 主备模型路由（`_FallbackModel` 代理），主模型异常时自动切到 `LLM_QWEN_FALLBACK`，支持 `invoke`/`ainvoke`/`stream`/`astream`/`bind_tools` 全接口
- **zhiku 健康探活 + 降级** (`tools/zhiku_tools.py`): `check_zhiku_health()` 异步探测 `/health` 端点，`is_zhiku_healthy()` 只读缓存；`zhiku_retrieve` 不健康时快速返回降级提示
- **lifespan 集成** (`api/server.py`): 启动时后台线程探测 zhiku 健康

#### Changed
- **待做清单** (`README.md`): DB 连接池 / 模型 fallback / zhiku 健康探活 标记为 ✅ 已完成；tenacity 重试描述修正（zhiku/tavily 已实现）
- **`.env.example`**: 新增 `LLM_QWEN_FALLBACK`、`OPENAI_FALLBACK_*`、`MYSQL_POOL_*` 环境变量

## [1.0.0] - 2026-08-09

### Phase 1 · P0 止血

#### Fixed
- **SQL 注入防护** (`tools/db_tools.py`)
  - `get_table_data`: 动态表名白名单（`SHOW TABLES` 获取）+ `_validate_identifier` 正则校验
  - `execute_sql_query`: sqlparse 三层防护（SELECT-only 校验 + LIMIT 自动注入 + DB 只读用户建议）
- **CORS 配置** (`api/server.py`): `allow_origins` 从 `.env` `ALLOWED_ORIGINS` 读取，去掉 `*`
- **脱敏** (`.env.example`): 真实 IP (`121.4.54.247`, `43.137.12.90`) 和 RAGFlow key 替换为占位符
- **重复定义** (`utils/path_utils.py`): 删除被覆盖的第一个 `resolve_path` 定义
- **副作用 print** (`agent/prompts.py`): 删除模块级 `print(main_agent_content)` / `print(sub_agents_content)`
- **私有方法调用** (`agent/main_agent.py`): `monitor._emit("error", ...)` → `monitor.report_error(...)`
- **流式结果覆盖 bug**: 原 `ragflow_tools.py:85` 的 `result = part.content`（赋值非累加），因选项 B 整体替换为 `zhiku_tools.py` 而消除

#### Added
- **WebSocket 鉴权** (`api/server.py`): 可选 `API_KEY` 通过 query param 鉴权
- **上传文件名净化** (`api/server.py`): `_sanitize_filename` 防路径穿越
- **并发限流** (`api/server.py`): `asyncio.Semaphore` 限制并发任务数（`MAX_CONCURRENT_TASKS`）
- **sqlparse 依赖**: 新增 `sqlparse>=0.5` 到 requirements.txt

#### Changed
- **FastAPI 生命周期** (`api/server.py`): `@app.on_event("startup")` → `lifespan` 上下文管理器

### Phase 2 · 接 agent-core + 工程骨架

#### Added
- **`pyproject.toml`**: uv 管理，ruff 配置（无 F811 ignore）
- **知识库子 Agent 改调 zhiku** (`tools/zhiku_tools.py`): `zhiku_retrieve` 工具调用 zhiku `/api/v1/retrieve`，替代 RAGFlow SDK
- **会展业务叙事** (`prompt/prompts.yml`): 主管 + 三子 Agent prompt 统一改写为会展场景
- **懒初始化** (`agent/main_agent.py`): `main_agent` 延迟到首次调用时构建，解决 import 即初始化的启动慢问题
- **`Dockerfile`**: 基于 python:3.11-slim，含 Pango/harfbuzz 系统依赖
- **`docker-compose.yml`**: web + mysql 服务编排
- **单元测试** (`tests/unit/`): 24 个测试覆盖 SQL 验证 + 路径解析

#### Changed
- **deepagents**: 0.4.3 → 0.7.5（含 langgraph 1.2.10）
- **langchain-core**: 1.3.3 → 1.5.3
- **langgraph**: 1.0.9 → 1.2.10
- **PDF 工具**: pywin32 (Windows Word COM) → weasyprint (跨平台 HTML→PDF)
  - `convert_md_to_pdf_via_weasyprint`: weasyprint 渲染，CSS 字体回退 Noto Sans CJK SC → WenQuanYi → Microsoft YaHei
  - `convert_md_to_pdf_via_word`: 保留但改为 try pywin32 → fallback weasyprint
  - requirements.txt: 移除 pywin32

#### Removed
- RAGFlow 相关依赖（`ragflow-sdk` 保留在 requirements.txt 供 rawflow/ demo 使用）

### Phase 3 · 可靠性（部分）

#### Added
- **SQLite checkpointer** (`agent/main_agent.py`): `sqlite3.Connection` 直接实例化 SqliteSaver（非 context manager），fallback 到 InMemorySaver
- **langgraph-checkpoint-sqlite**: 声明为 requirements.txt 依赖

### Phase 4 · 文档

#### Added
- **README**: 诚实边界 + 改造历程 + 差异化对比
- **CHANGELOG**: 本文件
- **AGENTS.md**: deepagents 例外声明 + zhiku M1~M8 修正

## [1.0.0-rc2] - 2026-08-09

### agent-core 接入

#### Added
- **agent-core tracing**: `start_span` 包裹 `agent.run` / `tool.tavily` / `tool.zhiku_retrieve`
- **agent-core logging**: `get_logger` 替换全部 `print()`（server / main_agent / monitor / tools）
- **SecurityGuardsMiddleware**: HTTP 入站鉴权 + 限流 + request_id 注入（有 API_KEY 时启用，WebSocket 路径豁免）
- **init_tracing**: lifespan 中初始化（无 OTel SDK 时自动 no-op 降级）
- **sys.path setup**: agent-core 作为 sibling 目录按需加入（try/except fallback）

#### Fixed
- **SqliteSaver 实例化**: 从 `from_conn_string(":memory:")` context manager 改为 `sqlite3.Connection` 直接构造
- **langgraph-checkpoint-sqlite**: 确认声明为 requirements.txt 依赖
