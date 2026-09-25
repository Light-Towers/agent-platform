# 全面审查报告：代码质量 / 架构 / 性能 / 安全 / 测试（2026-09-22）

> 审查日期：2026-09-22
> 审查范围：7 应用 + 3 共享包 + 根测试，670 .py 文件
> 审查方法：5 路并行 explore 子智能体 + grep 全量扫描 + 技术债务文档核对
> 与现有文档关系：补充 `tech-debt-hardcoded-logic.md`（TD-0~TD-14 已修复）与 `docs/plans/plan-tech-debt-cleanup-2026-09-22.md`（P0+P1+P2 部分完成）未覆盖的新发现问题
> 总计：新发现 42 项（P0: 9 / P1: 16 / P2: 17），其中 5 项与现有文档部分重叠

---

## 一、代码质量与健壮性

### P0（立即修复）

#### Q1 向量嵌入结果边界缺失（系统性，5 处）
- **位置**：
  - `applications/knowledge-service/knowledge_service/query_process/agent/nodes/node_search_embedding.py:57-58`
  - `applications/knowledge-service/knowledge_service/query_process/agent/nodes/node_search_embedding_hyde.py:131-132`
  - `applications/knowledge-service/knowledge_service/query_process/agent/nodes/node_item_name_confirm.py:114-115`
  - `applications/knowledge-service/knowledge_service/import_process/agent/nodes/node_item_name_recognition.py:269-271`
  - `applications/knowledge-service/knowledge_service/import_process/agent/nodes/node_bge_embedding.py:183-184`
- **问题**：`embeddings.get("dense")[0]` 模式：`None`→TypeError，`[]`→IndexError。嵌入服务异常或返回空时直接崩溃查询/导入主链路
- **修复方向**：统一加空值/空列表检查，`vec = embeddings.get("dense"); if not vec: return <降级结果>; dense_vec = vec[0]`
- **与现有文档关系**：新发现，未重叠

#### Q2 sqlite3.connect 资源泄漏
- **位置**：`applications/exhibition-agent/exhibition_agent/foundation/production_readiness_gate.py:186-190`
- **问题**：未用 `with` 语句或 try/finally，`cur.execute` 抛异常时 `conn` 不关闭，文件句柄泄漏
- **修复方向**：改用 `with sqlite3.connect(path) as conn:` 或 try/finally
- **与现有文档关系**：新发现

#### Q3 httpx.AsyncClient 手动生命周期管理
- **位置**：`applications/dialogue-framework/dialogue_framework/channels/rest_channel.py:45-47`
- **问题**：不用 `with` 语句，调用方可能忘记 `close()`，连接池泄漏
- **修复方向**：改用 `async with httpx.AsyncClient() as client:` 或确保 `close()` 在 finally 中调用
- **与现有文档关系**：新发现

#### Q4 环境变量整数解析无防护（3 处）
- **位置**：
  - `applications/agent_federation/tools/db_tools.py:44,83-85`
  - `applications/agent_federation/agent/circuit_breaker.py:32-36`
  - `applications/exhibition-agent/exhibition_agent/skill_loader/agent.py:24-25`
- **问题**：`int(os.getenv(...))` 无 try/except，配置错误（空串/含空格/拼写错误）导致模块导入失败，整个服务无法启动
- **修复方向**：用 `agent_core.config.env_int` / `env_float` 统一 helper（含异常降级 + 警告日志）
- **与现有文档关系**：部分重叠（`plan-tech-debt-cleanup-2026-09-22.md` T1.4 提及 env helper 统一，但未明确记录解析无防护的启动崩溃风险）

### P1（近期修复）

#### Q5 resp.json() 未捕获 ValueError（3 处）
- **位置**：
  - `applications/agent_server/subagents/search.py:20`
  - `applications/agent_federation/agent/async_subagents.py:114`
  - `applications/knowledge-service/knowledge_service/import_process/agent/nodes/node_pdf_to_md.py:89,173`
- **问题**：`resp.json()` 在响应非 JSON 时抛 `ValueError`，2xx 响应仍可能返回非 JSON（如 HTML 错误页）
- **修复方向**：try/except ValueError 降级为 text 解析或返回错误
- **与现有文档关系**：新发现

#### Q6 doc/state 缺键 KeyError（多处）
- **位置**：
  - `applications/knowledge-service/knowledge_service/import_process/agent/nodes/node_bge_embedding.py:160`（`doc["item_name"]`/`doc["content"]`）
  - `applications/knowledge-service/knowledge_service/import_process/agent/nodes/node_md_img.py:51,58`（`state["md_path"]`/`state["md_content"]`）
  - `applications/exhibition-agent/exhibition_agent/graph/nodes.py:53,56-60`（多个必需键）
- **问题**：用 `[]` 直接取键，缺键抛 KeyError
- **修复方向**：改用 `.get()` 带默认值或前置校验
- **与现有文档关系**：新发现

#### Q7 异常吞掉配置错误（4 处）
- **位置**：
  - `applications/agent_federation/agent/cache/semantic_cache.py:44`
  - `applications/knowledge-service/knowledge_service/clients/neo4j_utils.py:29`
  - `applications/knowledge-service/knowledge_service/clients/minio_utils.py:48`
  - `applications/exhibition-agent/exhibition_agent/foundation/execution_context.py:138`
- **问题**：`except Exception` 吞掉所有异常（含 ValueError/TypeError 等配置错误），配置错误被静默忽略
- **修复方向**：区分可恢复异常（连接失败）与编程错误，后者应抛出或记 ERROR
- **与现有文档关系**：部分重叠（`plan-tech-debt-followup-2026-09-22.md` D7 提及清理裸 except，但未具体到配置错误吞没）

#### Q8 admission mark_completed 参数不匹配
- **位置**：`packages/agent-runtime/agent_runtime/admission.py:236-240`
- **问题**：`conn.execute` 传了两个参数元组 `(request_id, ADMISSION_ADMITTED, ADMISSION_QUEUED)` 和 `(request_id,)`，psycopg `execute` 签名是 `execute(sql, params)`，第二个元组被忽略或抛异常。可能导致 `mark_completed` 静默失败，admission 容量泄漏
- **修复方向**：删除多余的第二个参数元组
- **与现有文档关系**：新发现

#### Q9 raise ValueError 未用 `from e` 丢失异常链
- **位置**：`applications/knowledge-service/knowledge_service/import_process/agent/nodes/node_import_milvus.py:94`
- **问题**：`raise ValueError(...)` 未用 `from e`，丢失原始异常链，调试时无法追溯根因
- **修复方向**：改 `raise ValueError(...) from e`
- **与现有文档关系**：新发现

---

## 二、架构与可扩展性

### P0（架构违规）

#### A1 knowledge-service → exhibition-agent 隐藏跨应用耦合
- **位置**：`applications/knowledge-service/knowledge_service/core/knowledge_lifecycle_integration.py:18`
- **问题**：import `exhibition_agent.foundation.knowledge_lifecycle`，违反架构红线 2（Application 不得互相 import 内部模块）；且 `knowledge-service/pyproject.toml` 未声明对 exhibition-agent 的依赖
- **修复方向**：① 在 knowledge-service/pyproject.toml 声明依赖；或 ② 将 `knowledge_lifecycle` 提取到 `packages/` 共享包
- **与现有文档关系**：新发现（现有文档未记录此跨应用耦合）

### P1（已知收敛期）

#### A2 exhibition-agent 测试 → knowledge-service 反向依赖
- **位置**：`applications/exhibition-agent/tests/test_knowledge_service_generalization.py:18-28`
- **问题**：exhibition-agent 测试 import knowledge-service 模块，pyproject.toml 未声明
- **修复方向**：随 A1 一并处理
- **与现有文档关系**：新发现

### P2（已知技术债，收敛中）

#### A3 agent-runtime 未被 kefu/nl2sql/knowledge/dialogue-framework 采用
- **状态**：已知技术债，Plan-F 收敛中（`ARCHITECTURE.md:90` 已登记）
- **与现有文档关系**：已登记，不重复

#### A4 dialogue-framework 与 agent-core 协议冗余
- **状态**：已知技术债（`ARCHITECTURE.md:91` 已登记 BaseChatClient vs BaseLLMProvider、Tracker vs memory）
- **与现有文档关系**：已登记，不重复

---

## 三、性能与效率

### P0（严重性能问题）

#### P1 pgvector 向量表缺失 HNSW 索引
- **位置**：`packages/agent-runtime/agent_runtime/db.py:17-189`
- **问题**：`SCHEMA_TEMPLATE` 创建 6 张含 `embedding vector(dim)` 列的表（chunks/memories/semantic_cache/sql_ddl/sql_docs/sql_examples），但**全部 6 张表的 embedding 列均未建 HNSW/IVFFlat 索引**。检索路径 `db.py:369-376` 执行 `ORDER BY embedding <=> %s::vector LIMIT %s`，无索引时全表扫描 + 显式排序，万级以上分块延迟从毫秒退化到秒级
- **对比**：`packages/agent-core/agent_core/memory/vector_backend.py:282-283` 的 `PgVectorMemoryBackend._init_schema` 正确建了 `USING hnsw (embedding vector_cosine_ops)`，说明项目已知该做法，但 `agent_runtime/db.py` 漏建
- **影响链路**：agent_server RAG 检索 / 语义缓存 / SQL 训练三件套召回 / 长期记忆
- **修复方向**：为 6 张表补 `CREATE INDEX IF NOT EXISTS idx_<table>_embedding_hnsw ON <table> USING hnsw (embedding vector_cosine_ops);` + 会话级 `SET hnsw.ef_search = 40`
- **与现有文档关系**：新发现，重大性能缺陷

#### P2 N+1 向量检索：循环内逐条 Milvus hybrid_search
- **位置**：`applications/knowledge-service/knowledge_service/query_process/agent/nodes/node_item_name_confirm.py:112-148`
- **问题**：每个提取出的商品名串行发起一次 Milvus 混合检索，N 个商品名→N 次串行网络往返。embedding 已批量生成（第 109 行），但检索退化为 N+1
- **修复方向**：合并为一次批量 hybrid_search，或用 `asyncio.gather` 并发各条检索
- **与现有文档关系**：新发现

#### P3 N+1 embedding + N+1 DB 写入：元知识构建
- **位置**：`applications/nl2sql-service/nl2sql_service/services/meta_knowledge_service.py:23-38`
- **问题**：`build_from_tables` 循环内逐条 `await self._save_column()`（内含单条 embed + 单条 INSERT），数百列串行
- **修复方向**：① 批量 `embed_documents(texts)`；② `asyncio.gather` 并发 DB 写入或 `executemany` 批量 INSERT
- **与现有文档关系**：新发现

### P1（中等性能问题）

#### P4 RAG 双路召回串行
- **位置**：`applications/agent_server/rag/store.py:133-134`
- **问题**：向量召回与 BM25 召回无依赖关系，却串行 await，各需一次 DB 往返
- **修复方向**：`vec_ids, bm25_ids = await asyncio.gather(_vector_ids(...), _bm25_ids(...))`
- **与现有文档关系**：新发现

#### P5 SQL 训练三件套召回串行
- **位置**：`applications/agent_server/sql/schema_store.py:46-48`
- **问题**：三次独立向量检索串行，可 `asyncio.gather` 并发，延迟降为 1/3
- **修复方向**：`ddl_rows, doc_rows, example_rows = await asyncio.gather(...)`
- **与现有文档关系**：新发现

#### P6 PDF 转换节点同步阻塞
- **位置**：`applications/knowledge-service/knowledge_service/import_process/agent/nodes/node_pdf_to_md.py:155,158,165,181,204`
- **问题**：`time.sleep(poll_interval)` 同步阻塞，轮询最长 600 秒，高并发导入时耗尽 LangGraph 线程池
- **修复方向**：改 `asyncio.sleep`，`requests` 换 `httpx.AsyncClient`
- **与现有文档关系**：新发现

#### P7 BM25_CACHE 无大小限制/TTL
- **位置**：`applications/agent_server/rag/store.py:24,99-111`
- **问题**：`_BM25_CACHE` 裸 dict，无大小上限、无 TTL。多 workspace 场景下每个 workspace 一个缓存项，workspace 数无限增长会内存泄漏
- **修复方向**：加 `OrderedDict` + LRU 淘汰；规模上来后替换为 ES/PG 全文索引
- **与现有文档关系**：新发现

#### P8 nl2sql-service 连接池未配置容量
- **位置**：`applications/nl2sql-service/nl2sql_service/api/dependencies.py:35,58`
- **问题**：`AsyncConnectionPool` 未传 `min_size`/`max_size`，用默认 max_size=8，高并发下可能池耗尽
- **修复方向**：显式设置从 settings 读取
- **与现有文档关系**：新发现

#### P9 Milvus 检索未设置 ef_search
- **位置**：`applications/knowledge-service/knowledge_service/clients/milvus_utils.py:153-157`
- **问题**：HNSW 索引检索时未传 `ef` 参数，用默认值。对比 `vector_backend.py:178` 正确设了 `{"ef": 64}`
- **修复方向**：`dense_params = {"metric_type": "COSINE", "params": {"ef": 64}}`
- **与现有文档关系**：新发现

### P2（轻微性能问题）

#### P10 重复读盘未用 lru_cache（5 处）
- **位置**：
  - `applications/nl2sql-service/nl2sql_service/agent/nodes/generate_sql.py:13`
  - `applications/nl2sql-service/nl2sql_service/agent/nodes/correct_sql.py:13`
  - `applications/knowledge-service/knowledge_service/core/load_prompt.py:20`
  - `applications/exhibition-agent/exhibition_agent/skill_loader/parser.py:255`
  - `packages/agent-runtime/agent_runtime/skills/workflow.py:200`
- **问题**：prompt 文件每次调用都读盘
- **修复方向**：用 `@lru_cache(maxsize=1)` 包裹加载函数
- **与现有文档关系**：新发现

---

## 四、安全性

### P0（高危）

#### S1 多个服务完全无鉴权
- **位置**：
  - `applications/nl2sql-service/nl2sql_service/api/server.py:14-18`（`POST /api/query` 完全开放）
  - `applications/kefu-service/kefu_agent/__main__.py:87-98`（`/invoke` 与 `/api/messages` 无鉴权）
  - `applications/exhibition-agent/exhibition_agent/skill_loader/app.py:65-188`（`/api/chat`、`/api/invoke`、`/api/skills`、`/api/config` 全部无鉴权）
- **问题**：任何人可触发 Text-to-SQL 生成与执行、kefu 对话、exhibition 工具调用
- **修复方向**：接入 `SecurityGuardsMiddleware` 或 `Depends(verify_api_key)`，配置 `API_KEY`
- **与现有文档关系**：新发现，生产安全风险

#### S2 agent_server / knowledge-service api_key 默认空 fail-open
- **位置**：
  - `applications/agent_server/api/auth.py:16-22`（`api_key: str = ""` 默认空 → 鉴权完全关闭）
  - `applications/agent_server/config.py:19`
  - `applications/knowledge-service/knowledge_service/core/config.py:140`
- **问题**：生产环境若忘记配置环境变量，所有受保护端点无条件开放
- **修复方向**：启动期 fail-fast：生产模式（`runtime_mode=distributed`）要求 `api_key` 非空
- **与现有文档关系**：新发现

#### S3 kefu /api/messages 接受裸 dict
- **位置**：`applications/kefu-service/kefu_agent/__main__.py:99`
- **问题**：端点直接接受 `dict`，未经过 Pydantic 校验，`query` 无长度上限，可构造超大 payload
- **修复方向**：改用 Pydantic 模型，加字段长度约束
- **与现有文档关系**：新发现

### P1（中危）

#### S4 SQL 拼接：列名/表名未做标识符白名单
- **位置**：
  - `applications/nl2sql-service/nl2sql_service/repositories/postgres/meta/meta_repository.py:18-34`（`data.keys()` 直接拼入列名）
  - `applications/nl2sql-service/nl2sql_service/models/postgres/postgres_model.py:16-31`
  - `applications/nl2sql-service/nl2sql_service/clients/pgvector_client_manager.py:28-70`（`table`/`embedding_col`/`filter_clause` 直接拼接）
  - `packages/agent-core/agent_core/memory/vector_backend.py:313-347`（`self._table` 直接拼接）
- **问题**：列名/表名/通道名未做标识符校验，用户可控输入可注入
- **修复方向**：复用 `agent_runtime/db.py:360-368` 的 `_IDENT` 正则做白名单校验
- **与现有文档关系**：新发现
- **对比正面案例**：`packages/agent-runtime/agent_runtime/db.py:360-368` 的 `vector_search` 已正确做白名单

#### S5 路径遍历
- **位置**：`applications/agent_federation/utils/path_utils.py:35,38,50`
- **问题**：`resolve_path` 在 `updated/` 分支、无 `session_dir` 分支、绝对路径分支均直接 `resolve()`，未强制限制在 `session_dir` 子树内。LLM 工具调用可构造 `../../etc/passwd` 等路径
- **修复方向**：所有分支统一加 `is_relative_to(session_path)` 校验
- **与现有文档关系**：新发现

#### S6 SSRF / 路径占位符注入
- **位置**：`applications/exhibition-agent/exhibition_agent/skill_loader/app.py:125-132`、`agent.py:215-222`
- **问题**：`/api/invoke` 的 `path` 占位符用用户传入的 `v` 替换，未做 URL 编码或路径遍历过滤。结合无鉴权（S1），任意调用方可探测内网
- **修复方向**：对 `v` 做 URL 编码 + 路径遍历过滤
- **与现有文档关系**：新发现

#### S7 敏感信息暴露：异常直出客户端（4 处）
- **位置**：
  - `applications/agent_federation/api/server.py:273,289`（`/api/files` 返回 `str(e)`）
  - `applications/exhibition-agent/exhibition_agent/skill_loader/app.py:109`（返回异常串 + LLM 配置信息）
  - `applications/nl2sql-service/nl2sql_service/agent/nodes/execute_sql.py:31`（SQL 执行异常直出）
  - `applications/knowledge-service/knowledge_service/api/query_router.py:163`（SSE 错误事件含原始异常串）
- **问题**：可能泄露内部路径、数据库表名、DSN、配置信息
- **修复方向**：5xx 返回通用文案，详情仅入日志（参考 `knowledge_service/api/errors.py:50-56` 的 `_sanitize_detail`）
- **与现有文档关系**：新发现

### P2（低危）

#### S8 CORS 配置过于宽松
- **位置**：`applications/agent_server/main.py:304-314`、`applications/knowledge-service/knowledge_service/main.py:69-74`
- **问题**：`allow_credentials=True` + `allow_methods=["*"]` + `allow_headers=["*"]`，若误配 `CORS_ALLOW_ORIGINS=*` 形成危险组合
- **修复方向**：收窄 `allow_methods` 为实际所需，禁止 `allow_origins=*` + `credentials=True` 组合
- **与现有文档关系**：新发现

#### S9 exhibition DEV 档 JWT alg=none 不验签
- **位置**：`applications/exhibition-agent/exhibition_agent/middleware/context_codec.py:89,46-56`、`config.py:24-28,77-79`
- **问题**：DEV 档下 JWT 不验签，攻击者可伪造任意 ExecutionContext JWT 绕过身份/租户/scope
- **修复方向**：生产部署文档强调 `execution_mode=STRICT`，启动期校验
- **与现有文档关系**：新发现

#### S10 NOTIFY/LISTEN 通道名 + vector_backend._table 未做标识符校验
- **位置**：`packages/agent-runtime/agent_runtime/planner/durability_pg.py:296,310`、`packages/agent-runtime/agent_runtime/admission_gateway.py:247,295`
- **问题**：`NOTIFY`/`LISTEN` 通道名直接拼接，当前为构造常量但未做白名单
- **修复方向**：加白名单正则
- **与现有文档关系**：新发现

---

## 五、测试覆盖率

### P0（High 风险盲区）

#### T1 admission.py 无专门测试
- **位置**：`packages/agent-runtime/agent_runtime/admission.py`（270 行）
- **问题**：`AdmissionQueue` 和 `RateLimiter` 在 `agent_server/main.py` 中使用，但无单元测试。`wait_for_admit`/`mark_completed`/`recover_on_startup` 并发与崩溃恢复路径未测
- **修复方向**：补并发 + 崩溃恢复测试
- **与现有文档关系**：部分重叠（`plan-tech-debt-cleanup-2026-09-22.md` T1.3 列的 5 项不含 admission）

#### T2 tracing_propagation.py 无测试
- **位置**：`packages/agent-core/agent_core/tracing_propagation.py`
- **问题**：W3C traceparent 跨服务传播无测试
- **修复方向**：补传播/解析/边界测试
- **与现有文档关系**：新发现

#### T3 guardrails/web.py 无测试
- **位置**：`packages/agent-core/agent_core/guardrails/web.py`
- **问题**：Web 护栏无测试
- **修复方向**：补 Web 护栏测试
- **与现有文档关系**：新发现

#### T4 api/routes.py 完整分支未覆盖
- **位置**：`applications/agent_server/api/routes.py`（426 行）
- **问题**：仅覆盖 coordinator reject/cache hit/冒烟，LLM 错误、SSE 中断、超时、并发等分支未测
- **修复方向**：补分支测试
- **与现有文档关系**：部分重叠（`plan-tech-debt-followup-2026-09-22.md` D6 涉及 routes.py 拆分，但未涉及测试覆盖）

#### T5 超大输入场景无专门测试
- **问题**：未找到专门测试超大 query/context/tool result 的用例
- **修复方向**：补超大输入边界测试
- **与现有文档关系**：新发现

### P1（Medium 风险盲区）

#### T6 memory/{semantic,mongo}.py 无测试
- **位置**：`packages/agent-core/agent_core/memory/semantic.py`、`mongo.py`
- **问题**：语义记忆/Mongo 后端无测试（仅 checkpointer 有）
- **修复方向**：补后端降级测试
- **与现有文档关系**：新发现

#### T7 main_agent.py 核心编排分支覆盖不全
- **位置**：`applications/agent_federation/agent/main_agent.py`（31K，最大文件）
- **问题**：仅基线测试，核心编排逻辑分支覆盖不全
- **修复方向**：补分支测试
- **与现有文档关系**：部分重叠（`plan-tech-debt-cleanup-2026-09-22.md` T2.2 涉及拆分 main_agent.py，但未涉及测试覆盖）

---

## 六、技术债务确认总结

### 已登记并全部修复的债务

| 来源文档 | 登记数 | 已修复 | 仍成立 |
|----------|--------|--------|--------|
| `docs/tech-debt/tech-debt-hardcoded-logic.md`（TD-0~TD-14） | 15 | 15 | 0 |
| `docs/analysis/2026-09-21/02-debt-diagnosis.md`（TB 14 + TD 15 + U 1 + Roadmap 8 + S0/S1 新发现 10） | 48 | 48 | 0 |
| `docs/plans/plan-tech-debt-cleanup-2026-09-22.md`（P0+P1+P2 部分） | — | P0+P1+P2(T2.1/T2.3) 已完成 | P2(T2.2/T2.4)+P3 待实施 |
| `docs/plans/plan-tech-debt-followup-2026-09-22.md`（D1~D10） | 10 | 0 | 10（后续追踪中） |

**仍成立的 3 条附条件关闭**（非技术债）：
- TB-7：docker compose 冒烟需 Docker（可选环境依赖）
- TB-11：双轨配置体系（agent_core dataclass + 应用 pydantic-settings，有意分层设计）
- TB-13：双轨认知成本（Plan-F 已消解）

### 代码中仍存在的 TODO 标记

**packages/agent-core 和 packages/agent-runtime 中：0 处 TODO/FIXME**（grep 确认）

**exhibition-agent 中：约 15 处 TODO**，均为**骨架占位实现**（非技术债，属于尚未落地的功能）：

| TODO 标记 | 对应未落地功能 | 位置 |
|-----------|---------------|------|
| TODO(F1-D) | Vault/KMS 凭证后端接入 | `execution_context.py:255,286,288` |
| TODO(F2) | 真实 LLM 连接接入 | `model_router.py:109`、`data_egress.py:265,282` |
| TODO(F01) | enforce_scope_filter 落地 | `evaluation.py:17,58` |
| TODO(F03) | 同具体性不同租户样本规则 | `evaluation.py:145` |
| TODO F02 | READY 数据源连接 | `production_readiness_gate.py:180` |
| TODO nl2sql endpoint | nl2sql-service 通用化后填充端点 | `skills/data_analysis/skill.py:31,33,102,104` |
| TODO 占位 | skill_router 集成 | `foundation/skill_router.py:12` |

**结论**：exhibition-agent 的 TODO 是该子项目功能尚未完全落地的设计占位，待 F01/F02/F03/F1-D/F2 决策后实施，不属于技术债务范畴。

---

## 七、新发现技术债务汇总（按优先级排序）

### P0（立即修复，9 项）

| ID | 维度 | 问题 | 位置 |
|----|------|------|------|
| Q1 | 健壮性 | 向量嵌入结果边界缺失（5 处） | knowledge-service 多个节点 |
| Q2 | 健壮性 | sqlite3.connect 资源泄漏 | exhibition-agent production_readiness_gate.py |
| Q3 | 健壮性 | httpx.AsyncClient 手动生命周期 | dialogue-framework rest_channel.py |
| Q4 | 健壮性 | 环境变量整数解析无防护（3 处） | agent_federation + exhibition-agent |
| A1 | 架构 | knowledge-service → exhibition-agent 隐藏耦合 | knowledge_lifecycle_integration.py |
| P1 | 性能 | pgvector 6 张表缺失 HNSW 索引 | agent_runtime/db.py |
| P2 | 性能 | N+1 向量检索 | node_item_name_confirm.py |
| P3 | 性能 | N+1 embedding + DB 写入 | meta_knowledge_service.py |
| S1 | 安全 | 多个服务完全无鉴权 | nl2sql/kefu/exhibition |
| S2 | 安全 | api_key 默认空 fail-open | agent_server/knowledge-service |
| S3 | 安全 | keku /api/messages 接受裸 dict | kefu __main__.py |

### P1（近期修复，16 项）

| ID | 维度 | 问题 | 位置 |
|----|------|------|------|
| Q5 | 健壮性 | resp.json() 未捕获 ValueError（3 处） | search/async_subagents/node_pdf_to_md |
| Q6 | 健壮性 | doc/state 缺键 KeyError（多处） | knowledge-service/exhibition-agent |
| Q7 | 健壮性 | 异常吞掉配置错误（4 处） | semantic_cache/neo4j_utils/minio_utils/execution_context |
| Q8 | 健壮性 | admission mark_completed 参数不匹配 | agent_runtime/admission.py |
| Q9 | 健壮性 | raise ValueError 未用 from e | node_import_milvus.py |
| A2 | 架构 | exhibition-agent 测试 → knowledge-service 反向依赖 | test_knowledge_service_generalization.py |
| P4 | 性能 | RAG 双路召回串行 | agent_server/rag/store.py |
| P5 | 性能 | SQL 训练三件套召回串行 | agent_server/sql/schema_store.py |
| P6 | 性能 | PDF 转换节点同步阻塞 | node_pdf_to_md.py |
| P7 | 性能 | BM25_CACHE 无大小限制 | agent_server/rag/store.py |
| P8 | 性能 | nl2sql 连接池未配置容量 | nl2sql_service/api/dependencies.py |
| P9 | 性能 | Milvus 检索未设置 ef_search | milvus_utils.py |
| S4 | 安全 | SQL 拼接列名未白名单（4 处） | nl2sql + agent_core |
| S5 | 安全 | 路径遍历 | agent_federation/path_utils.py |
| S6 | 安全 | SSRF 占位符注入 | exhibition skill_loader |
| S7 | 安全 | 异常直出客户端（4 处） | agent_federation/exhibition/nl2sql/knowledge |
| T1 | 测试 | admission.py 无专门测试 | agent_runtime/admission.py |
| T2 | 测试 | tracing_propagation.py 无测试 | agent_core/tracing_propagation.py |
| T3 | 测试 | guardrails/web.py 无测试 | agent_core/guardrails/web.py |
| T4 | 测试 | api/routes.py 完整分支未覆盖 | agent_server/api/routes.py |
| T5 | 测试 | 超大输入场景无专门测试 | — |

### P2（择机修复，17 项）

| ID | 维度 | 问题 | 位置 |
|----|------|------|------|
| P10 | 性能 | 重复读盘未用 lru_cache（5 处） | nl2sql/knowledge/exhibition/agent-runtime |
| S8 | 安全 | CORS 配置过于宽松 | agent_server/knowledge-service main.py |
| S9 | 安全 | exhibition DEV 档 JWT alg=none | exhibition context_codec.py |
| S10 | 安全 | NOTIFY/LISTEN 通道名未校验 | durability_pg/admission_gateway |
| T6 | 测试 | memory/{semantic,mongo}.py 无测试 | agent_core/memory/ |
| T7 | 测试 | main_agent.py 核心编排分支覆盖不全 | agent_federation/agent/main_agent.py |

---

## 八、正面发现（安全/性能实践良好的位置）

为完整起见，列出已正确处理的点，供后续改进参考：

### 安全
1. **SQL 白名单守卫**：`agent_core/sql/guard.py:34-67` 用 sqlglot 解析，只放行单条只读 SELECT，禁止 DROP/DELETE/UPDATE
2. **标识符白名单**：`agent_runtime/db.py:360-368` 的 `vector_search` 用正则 `^[a-z_][a-z0-9_]*$` 校验表名/列名
3. **只读连接双保险**：`agent_server/sql/pipeline.py:48,75-79` sqlite `mode=ro` + PG `default_transaction_read_only=on`
4. **统一异常脱敏**：`knowledge_service/api/errors.py:50-56` 5xx 通用文案
5. **trace 脱敏**：`agent_runtime/otel.py:128-133` 的 `redact_question` 只存长度 + 哈希
6. **会话防劫持**：`agent_server/api/auth.py:25-30` 在 API_KEY 启用时按密钥派生 `thread_id`
7. **yaml.safe_load**：`agent_runtime/skills/workflow.py:201`，无 `yaml.load`/`pickle`/`eval`/`exec`
8. **.env 未入库**：`.gitignore` 正确忽略

### 性能
1. **lru_cache 已广泛使用**：router/config/classifier/rerank 等多处
2. **asyncio.gather 已用于执行图分层并行**：`execution_graph.py:309`
3. **asyncio.to_thread 已用于移出事件循环**：embedder/vector_backend/classifier
4. **embedding/rerank 批处理已实现**：`embedder.py:192-207` batch_size=16、`rerank.py:79-104` batch_size=64
5. **连接池懒加载加锁**：`agent_runtime/db.py:209`
6. **Milvus HNSW 索引正确创建**：`vector_backend.py:138-145`（Milvus 后端）、`vector_backend.py:282-283`（PgVector 后端）

### 架构
1. **架构红线 1/3 完全成立**：agent-core 零依赖零反向导入，agent-runtime 不 import 任何 application
2. **entry_points 插件机制优雅**：解决"runtime 不得 import application"与"执行器在 application 侧"的矛盾
3. **扩展点体系完整**：Planner 协议 + SkillRegistry + EventBus + MemoryStore

### 测试
1. **测试体系成熟度高**：10 个独立 pytest session 分层清晰
2. **agent-runtime 覆盖最佳**（73% 测试/源码比）
3. **HA 灾难恢复测试优秀**（10 个文件：A kill→B 接管→B 分区→C 接管）

---

## 九、建议修复顺序

### 第一批（P0，立即）
1. **S1/S2/S3 安全**：为 nl2sql/kefu/exhibition 接入鉴权；agent_server/knowledge-service 启动期 fail-fast 要求 api_key 非空
2. **P1 性能**：db.py 为 6 张向量表补 HNSW 索引（延迟降 1-2 个数量级）
3. **Q1 健壮性**：knowledge-service 向量嵌入节点补空值/空列表检查（5 处）
4. **Q8 健壮性**：admission.py mark_completed 参数修复（防容量泄漏）
5. **A1 架构**：knowledge-service → exhibition-agent 依赖声明或提取共享模块

### 第二批（P1，近期）
6. **P2/P3 性能**：node_item_name_confirm 批量检索、meta_knowledge_service 批量 embedding
7. **P4/P5 性能**：RAG/SQL 召回改 asyncio.gather 并发
8. **S4/S5/S6 安全**：nl2sql 列名白名单、resolve_path 强制限制子树、SSRF 占位符过滤
9. **T1/T4 测试**：补 admission.py 并发+崩溃恢复测试、api/routes.py 分支测试
10. **Q4/Q5/Q6 健壮性**：环境变量解析加 try/except、resp.json() 加 ValueError 捕获、缺键加 .get()

### 第三批（P2，择机）
11. **P7/P10 性能**：BM25_CACHE 加 LRU 上限、prompt 加载加 lru_cache
12. **S8/S9/S10 安全**：CORS 收窄、JWT DEV 档加固、NOTIFY 通道名校验
13. **T2/T3/T5/T6/T7 测试**：补 tracing_propagation/guardrails/web/超大输入/memory/main_agent 测试
14. **A3/A4 架构**：agent-runtime 向 kefu/nl2sql/knowledge/dialogue-framework 收敛

---

## 交叉引用

- `docs/tech-debt/tech-debt-hardcoded-logic.md`：TD-0~TD-14 全部已修复
- `docs/analysis/2026-09-21/02-debt-diagnosis.md`：48 条债务全量闭合
- `docs/plans/plan-tech-debt-cleanup-2026-09-22.md`：P0+P1+P2(T2.1/T2.3) 已完成，P2(T2.2/T2.4)+P3 待实施
- `docs/plans/plan-tech-debt-followup-2026-09-22.md`：D1~D10 后续追踪中
- `ARCHITECTURE.md:90-91`：A3/A4 已登记的收敛期技术债
