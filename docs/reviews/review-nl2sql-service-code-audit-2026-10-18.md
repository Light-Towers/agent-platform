# nl2sql-service 代码侧审计（2026-10-18）

- 对象：`applications/nl2sql-service/` 全量源码（42 个 .py + 8 个 .prompt + 配置）+ `packages/agent-core/agent_core/sql/guard.py`
- 对照基线：`docs/plans/plan-nl2sql-meta-lifecycle-2026-10-17.md`（下称"方案"）
- 方法：逐个文件实读，每条结论带 `file:line`；方案已登记项只做"仍开放"确认，不重复论证；本文增量在 §3（方案未登记项）
- 结论口径：本窗口唯一已落地的方案项是连接池工厂上移（commit `1aec092`，`clients/pg_pool.py` 已删，改走 `agent_runtime.pool_factory`）与 CLI 日志脱敏（`c6cbea7`）。其余 P0/P1/S 项在代码侧全部仍开放。
- **回写状态（2026-10-18 同日）**：本文 §3 的 15 条发现已全部回写方案——新增 §5.16（归属映射）+ P0-11（A1-A4/B2）+ S-11（pg_sleep）+ Q26（部署入口）+ 验收 23-26 + §11.1-R14（S-6 次数 10→7）+ §11.3-N8~N14；P0-1 判据、P0-5③、V2、E2 图修正、P2 卫生项已就地修订。本文与方案的分工：**本文管"是什么"（锚点与证据），方案管"归谁、何时做、怎么验收"（编号与批次）**。

## 1. 一句话结论

方案把结构性缺口耙得很全，代码侧只还了两笔（池工厂上移、DSN 脱敏）；**真正在跑的请求路径上有三处"配置/上下文断链"会直接压低答对率**（`date_info` 恒空、`metric_infos` 恒空且 `state.tables` 无消费方、settings 检索段整体没进 state），另有中文全文召回实际不可用、metric 向量召回恒空两个"看着接了其实没接"的暗断点。这些方案要么未登记，要么只记了症状没记断点。

## 2. 方案已登记项：代码侧仍开放确认

| 方案项 | 代码现状（2026-10-18 实读） | 状态 |
|---|---|---|
| P0-1 构建入口 stub | `scripts/build_meta_knowledge.py:20-24` 构造 service 后只 print，`--config` 解析后未使用 | 仍开放 |
| H3 重建不幂等 | `meta_repository.py:17-36` 纯 INSERT 无 upsert；`pgvector_client_manager.upsert_vector` 存在但零调用 | 仍开放 |
| §5.11-V2 sql_max_rows 死配置 | `query_service.py:25` state 只注入 `query/context/llm/metric_config`；`validate_sql.py:13` 恒取默认 1000 | 仍开放 |
| §5.14 filter_metric 浪费 | `filter_metric.py:25` 写回 `state.metrics`，`generate_sql.py` 不读 | 仍开放 |
| §5.14 filter_table 空转 | 库路径下无节点写 `state.tables`（`filter_table.py:14-15` 提前返回） | 仍开放 |
| §5.14 add_extra_context 空实现 | `add_extra_context.py:6-8` 纯透传 | 仍开放 |
| E2 执行期异常无回路 | `graph.py:75` `execute_sql → END` 无条件边 | 仍开放 |
| §5.13 多轮四层全空 | `api/`+`services/` grep `session_id` 零命中 | 仍开放 |
| §5.9 脱敏/表级/行级三层零 | `dw_repository.py:16-21` 只 SET 只读后直执行 | 仍开放 |
| S-5 LLM 超时死配置 | `agent/llm.py:31-42` invoke 无 wait_for；`providers.py` build 签名无 timeout 参数可传 | 仍开放 |
| S-6 无限流 | 全服务无 semaphore/rate limit | 仍开放 |
| P0-10 标识符拼接 | `pgvector_client_manager.py:28-70`、`meta_repository.py:18-36` f-string 拼表名/列名照旧 | 仍开放 |
| §2-① pgvector 段死配置 | `settings.py:90-91` 只取 `table_prefix`；`meta_config.yaml:11-13` 的 dimension/index_type/metric 无读取方 | 仍开放 |
| §2-④ 无 DDL 入库 | 全服务 `CREATE TABLE`/`CREATE INDEX` 零命中 | 仍开放 |
| P0-4 trace/golden 零 | 无 trace 落库、无 golden 集 | 仍开放 |

## 3. 本次新发现（方案未登记或只记症状未记断点）

### A. 生成期上下文断链（直接影响答对率，优先修）

| # | 问题 | 锚点 | 后果 |
|---|---|---|---|
| A1 | `date_info` 恒空串。prompt 有"当前的时间信息如下："槽位，两个节点都传 `""` | `agent/nodes/generate_sql.py:31`、`agent/nodes/correct_sql.py:36`；`prompts/generate_sql.prompt:11-12` | "上个月/今年/最近7天"类相对时间查询，LLM 无任何日期锚点，只能编。方案 E3 只把 correct 轮的空值当"上下文少"，未定性为生成期功能缺陷 |
| A2 | `metric_infos` 恒空串，`state.metrics` 无消费方 | `generate_sql.py:30`；`correct_sql.py:34` | 指标定义只以 RRF 混合 JSON 的形式挤在 `table_infos` 里，prompt 第 2 条"必须严格遵循指标口径"失去结构化输入 |
| A3 | 库路径下 `state.tables` 恒空 ⇒ 生成期没有任何表级视图（表名清单、表注释） | `merge_retrieved_info.py:28-32` 仅 metric_config 入参时透传 tables；`generate_sql.py:27` 的 `table_infos` 实为列级 JSON | LLM 在"选哪些表、怎么 JOIN"上纯猜。方案记了 filter_table 空转，未连写到生成层后果 |
| A4 | 修正轮信息少于生成轮 | `correct_sql.py:32-40` 的 `table_infos=retrieved_info`，无 tables、无 metrics、无 date | 与 E3 同类，但 E3 只点了 metric/date 空串，没点 tables 槽缺失 |

### B. 检索层暗断点

| # | 问题 | 锚点 | 后果 |
|---|---|---|---|
| B1 | 中文全文召回实际不可用：`plainto_tsquery('simple', %s)` 的 simple 词典对中文不分词，整串当一个 lexeme，tsvector 侧无同 lexeme 即零命中 | `clients/pgvector_client_manager.py:46-49`；调用方 `repositories/pgvector/value_repository.py:19-26` | 值域召回只有"整串恰好相等"能中。方案 P0-5③ 提了 AND 改 OR，未提词典层——OR 修法在这个断点上无效 |
| B2 | 同一 embedding 输入算两遍：column 与 metric 召回分支各调一次 `embed_query(" ".join(keywords))` | `nodes/recall_column.py:25`、`nodes/recall_metric.py:26` | 每次请求双倍 embedding 延迟与费用，三路并行分支无共享点 |
| B3 | `tokenizer` 也没进 state，settings/YAML 的 tokenizer 段是死配置；且 jieba 不在依赖里，"jieba" 选项是永假分支（ImportError 静默降级 bigram） | `nodes/extract_keywords.py:25`；`conf/settings.py:61-62`；`pyproject.toml` dependencies 无 jieba | 死配置家族在方案登记的 8 个之外再 +1；TOKENIZER=jieba 部署静默得不到预期行为 |
| B4 | 5 个 prompt 死文件：3 个 extend_keywords + 2 个 filter 模板零引用，节点用内联 f-string | `prompts/` 目录；grep `extend_keywords\|filter_table_info\|filter_metric_info` 零命中 | 方案 S-6 按"extend×3"估算单问 LLM 上限 10 次，实际 extend 从未实现，真实上限 7 次；5 个文件是待清理资产 |

### C. 执行层

| # | 问题 | 锚点 | 后果 |
|---|---|---|---|
| C1 | 危险函数无防：`SELECT pg_sleep(30)` 是合法单 SELECT，guard 全放行（无函数白名单/黑名单） | `guard.py:52-54` 的 walk 只查 FORBIDDEN_NODES | 唯一护栏是 dw 池 statement_timeout=30s + max 10 连接；LLM 幻觉即可占满池。方案未登记 |
| C2 | 路由脆弱：correct 达上限时 `_route_after_validate` 返回 `execute_sql`，安全性完全依赖 `execute_sql.py:19` 的 error 非空提前返回 | `graph.py:25-30`、`execute_sql.py:18-19` | 隐式耦合。correct_sql 达上限分支的 error 一旦被改空，未校验 SQL 会被真执行。达上限应直接进错误终态 |
| C3 | 每次执行多一次往返：`SET default_transaction_read_only = on` 在池层 read_only 之后又执行一遍 | `dw_repository.py:18`；`dependencies.py:83` | 作为第三道防线是显式设计（注释已声明），可接受；但 autocommit 语义下该 SET 的持久性依赖池配置，值得一条测试钉住 |

### D. 契约、构建入口与运维

| # | 问题 | 锚点 | 后果 |
|---|---|---|---|
| D1 | 双契约分叉：运行路径用 `config/metric_config_schema.py` 的 MetricConfig，`entities/` 五件套只被契约测试引用 | `tests/test_nl2sql_contracts.py:8-84`；grep entities 命中仅测试与定义 | 测试给不参与运行的契约兜底，真契约无测试。方案未登记 |
| D2 | metric 向量召回恒空：`build_from_tables` 只写列（带 embedding），metric/value 的 embedding 没有任何写入路径 | `services/meta_knowledge_service.py:32-38, 40-51` | `MetricRepository.recall` 要求 embedding 非 NULL（`metric_repository.py:16-17`），metric_info 表无 embedding 数据时该路恒空。方案记了构建 stub，未连到此后果 |
| D3 | `.env.example` 维度自相矛盾：`EMBEDDING_MODEL=bge-small-zh` 与 `VECTOR_DIM=1536` 并存 | `.env.example:13,45`；`meta_config.yaml:11` | 按模板部署 huggingface 后端时维度不符，pgvector 插入直接报错。方案只记了 pgvector 段死配置 |
| D4 | 文档漂移两处：注释引用已删除的 `clients/pg_pool.py` | `conf/app_config.yaml:25`、`.env.example:59` | 1aec092 删文件后未清引用 |
| D5 | console script 指错入口：`nl2sql-service` 命令映射到构建 CLI 而非 server，且该 CLI 是空壳 | `pyproject.toml` `[project.scripts]` | 安装后按命令名启动得到空转脚本 |
| D6 | `/health` 恒 HEALTHTY，不探池状态 | `api/server.py:14-15`；契约测试钉死 `dependencies == []`（`pools_router.py` docstring 有记录） | 池全挂时探针放行流量到坏实例。pools_router docstring 解释了为何不开在 /health，但 readiness 缺口本身未登记 |
| D7 | state 携带不可序列化对象：`context`（持连接池）与 `llm` 进 TypedDict | `agent/state.py:21-22`；`query_service.py:25` | 无 checkpointer 时能跑；平台若上统一 session/checkpoint（§5.13 提到），池对象进 state 即炸。方案未登记 |

### E. 方案已登记、本文仅确认仍为空（不展开）

多轮继承（§5.13 M1-M6）、权限三层（§5.9 L1-L3）、S-1~S-10 中除已修 S-4 外的全部、P0-5 别名检索、P0-7 取值下推、P0-8 五道闸、P1-3/P1-6 datasource 维度、P1-4 方言分支、P1-5 负载隔离、§5.14 R1-R7 关系声明、H2 刷新触发、H4 质量回路、§11.6 G1/G2 两条章节级缺失（无迁移回滚路径、无基线与 owner）。

## 4. 建议批次（按依赖排序）

**批次 1（不依赖任何拍板，预计 1-2 人日，纯本地改动）**：A1 date_info 注入（含业务日期/系统日期区分）、A2+A3 把 `state.tables`/`state.metrics` 接进 generate/correct 的 prompt 槽（与方案 R3 同批）、B2 embedding 单算后共享、B3 tokenizer 接线或删 jieba 死选项、C2 达上限改错误终态、D3/D4/D5 文档与入口修正、S-3 错误分类回显（方案已列 I0）。

**批次 2（依赖批次 1 的上下文契约，或与方案 P0-5/P0-8 同批）**：B1 全文词典修复（随 P0-5③ 重构一并做，单独改 OR 无效）、C1 执行期异常回路（方案 E2 设计已成型，含三分类）、D2 构建入口实装必须同时补 metric/value embedding 写入（P0-1）。

**批次 3（平台拍板后）**：多轮 §5.13、权限 §5.9、datasource §P1-6、关系声明 §5.14-R1~R4。

### 4.1 落地状态（2026-10-18 当日，批 1 已执行部分）

| 项 | 状态 | 落点 | 验证 |
|---|---|---|---|
| A1 date_info | **已落地** | `services/query_service.py` 新增 `build_date_info()`，每请求注入 state；`generate_sql`/`correct_sql` 读它 | `test_query_service_injects_config_into_state`、`test_build_date_info_includes_note`、`test_generate_sql_uses_state_slots` |
| A2 metric_infos | **已落地** | 两个节点改 `json_block(state["metrics"])` | 同上（断言 `SUM(amount)` 进 prompt） |
| A3 tables 消费 | **已落地（单测级）** | `merge_retrieved_info` 从列召回按 `table_name` 去重派生 `state.tables`（不依赖尚未存在的 relations 表）；`build_table_infos()` 分【表】【列】【取值】三块注入 | `test_merge_derives_tables_from_columns`；真实元知识库下的端到端待 P0-1 |
| A4 correct 上下文 | **已落地** | `correct_sql` 复用 `build_table_infos`，补齐 metric/date/db_info | 与 A2 同用例覆盖（同一 helper） |
| B2 embedding 单算 | **已落地** | `extract_keywords` 算一次写入 `state["query_embedding"]`；column/metric/value 三路复用；value 路顺带复活了原本恒 `None` 的向量补位 | `test_recall_column_reuses_query_embedding`（embedder 被调用即失败） |
| B3 tokenizer + 死配置 | **已落地** | `query_service` 集中注入 `sql_max_rows`/`sql_max_correct_retries`/`retrieval_top_k`/`rrf_k`/`tokenizer`；jieba 缺包改告警不再是静默降级；`pyproject` 新增 `[tokenizer]` extra | 配置注入用例 + `test_env_template` 全绿 |
| C2 达上限路由 | **已落地** | `_route_after_validate` 返回 `END`，条件边映射补 `END: END`；不再借 `execute_sql` 的 error 早退兜底 | `test_route_after_validate` 四参数化用例 |
| S-3 错误分类 | **已落地** | `execute_sql.classify_error()` 四类映射；对外只回分类消息，原文进 `error_detail` + 日志 | `test_classify_error_categories`、`test_execute_sql_hides_raw_error` |
| B 组 prompt 健壮性（新增项，非 15 条内） | **已落地** | 新建 `nodes/_prompt.py`：`lru_cache` 一次读盘 + `format_map` 安全渲染（模板出现字面花括号不再 500） | 由 `test_generate_sql_uses_state_slots` 间接覆盖（渲染路径） |
| D3 维度矛盾 | **已落地** | `.env.example` 的 `EMBEDDING_MODEL` 改 `text-embedding-3-small` 并加"换模型须同步 VECTOR_DIM + 全库重灌"注释 | 配置文本，无测试 |
| DDL 入库（N4 / P0-1 前置） | **已落地（静态校验）** | 新增 `nl2sql_service/migrations/001_meta_schema.up.sql` + `.down.sql`：五张表 + `nl2sql_schema_meta`；`value_tsvector` 改生成列（只从 `search_text`）；HNSW→ivfflat→顺序扫描三级降级；`scripts/init_meta_schema.py` 提供 apply/dry-run/status | `tests/test_init_meta_schema.py` 7 条（文件发现/占位符替换/表齐全/幂等无 DROP/`$$` 成对/唯一约束/`value_tsvector` 表达式/dry-run 不连库）。**未在真实 PG 执行**（本机无 docker/psql） |
| D4 注释漂移 | **已落地** | `app_config.yaml:25`、`.env.example:59` 改指 `agent_runtime.pool_factory` | 配置文本 |
| B1 中文词典 | **查询侧已落地；索引侧待 Q23** | `PgvectorClientManager.fulltext_search` 入参从整段文本改为 tokens，新增 `build_tsquery()`：显式 OR + 逐 token 单引号转义 + 纯标点丢弃 + 20 词上限；空 tokens 在取连接前返回。`value_repository` 直接下传 `keywords`，不再 `" ".join` 后交给 PG 二次分词。**未解决**：`value_tsvector` 的生成方式（索引侧分词）仓内无 DDL，中文能否真正命中取决于它，卡 Q23 | `applications/nl2sql-service/tests/test_tsquery_builder.py` 8 条（OR 连接/转义/元字符/丢空/拆空格/上限/空输入不碰库） |
| S-11 pg_sleep | **已落地** | `packages/agent-core/agent_core/sql/guard.py` 新增 `FORBIDDEN_FUNCTIONS`（PG：pg_sleep 家族/dblink 家族/lo_import/lo_export/pg_read_file 家族/pg_terminate_backend/set_config；MySQL：sleep/benchmark）+ `_function_name()` 归一 schema 限定名；`exp.Func` 判型不误伤聚合 | `tests/governance/test_sql_guard.py` 新增三条：PG 五例全拒、MySQL 两例全拒、`count/sum/lower/round` 正常函数不误伤 |
| D2 构建入口 | **已落地**（commit `e847eeb`） | `MetaRepository` 三个 `save_*` 改为按 001 唯一键写死列清单 + 参数化 upsert（`ON CONFLICT DO UPDATE SET ..., updated_at=now()`，`RETURNING xmax=0` 区分插入/更新）+ `prune_*` 差异删除；`MetaKnowledgeService` 三类写入全部带 embedding 与（取值路）`search_text`；`build_meta_knowledge` CLI 去空壳（`--config` 只接受 MetricConfig，`--prune`，构建报告）。embedding 维度 != `Settings.vector_dim` 直接抛错 | `applications/nl2sql-service/tests/test_meta_knowledge_build.py` 11 条 + 1 条真库手动用例（`META_DB_DSN` 未设时 skip：search_text 非空 + `value_tsvector` 生成列有值）。fake 池按唯一键语义实现 upsert/prune，**并抓到一处真 bug**（`prune_metrics` 传 `set[str]` 被逐字符拆参） |
| D5 入口 / D6 health | **已落地**（commit `4a4915e`） | Q26 按落地方案执行：console script `nl2sql-service` 改指 `nl2sql_service.api.server:main`（新增 `main()` 用 `Settings.host/port` 起 uvicorn）；新增 `GET /ready` 探 meta/dw 两池（3s 短超时 `SELECT 1`，200/503），`/health` 未动 | `applications/nl2sql-service/tests/test_ready_probe.py` 8 条（fake pools 注入 app.state：200/缺失 503/探活失败 503/未初始化 503/短超时；`/health` 契约不变；console script 指向；main 接线） |
| D1 双契约 | **已落地**（commit `54f0b26`） | 删 `entities/` 六文件（选删除而非 re-export：`ColumnMetric`/嵌套 `metrics` 在 MetricConfig 无对应物，shim 只会继续测不运行的形状）；契约测试 entities 段整体重写为 MetricConfig 用例 | `tests/test_nl2sql_contracts.py` 16 passed（必填校验/默认值/`model_dump` 形状/`to_recall_result` 四段结构——改运行契约即红）；`grep entities` 仅剩 docstring 删除说明，零运行引用 |

**验证口径（单次实跑）**：`uv run pytest tests/governance/test_sql_guard.py tests/nl2sql_service -q` → **33 / 22 passed**（分两次跑，混跑会撞 conftest 重名）；`applications/nl2sql-service/tests` → **50 passed**；`applications/agent_federation/tests/unit` → **135 passed**；`ruff check` 对全部改动/新增文件 → All checks passed。**未跑全量 `make test`**（改动落在 nl2sql-service 与共享 guard，未触其余服务代码），提交前按 AGENTS.md 仍须对齐 CI。

## 5. 自纠与边界

- 本文只审平台侧 `applications/nl2sql-service`；`agent_server/sql/`（G1 的第二条 Text2SQL 路）不在本范围。
- B1 的结论前提是 meta 库 tsvector 列未接中文分词扩展；全服务无 DDL 入库（§2-④），tsvector 生成方式不可知，若库外手段已建 zhparser 类配置则结论收窄为"部署契约不可见"。
- 所有行号锚点取自 2026-10-18 工作区；引用前先核对，方案文档自身已有行号漂移前科（§11.1）。
- 未做任何代码修改，本文纯审计。
