# ADR-0011: 平台内两条 Text2SQL 路（nl2sql-service / agent_server/sql）——收敛决策记录

- 状态：**已决：选项 A（2026-10-18 用户拍板）——agent_server/sql 退役，统一到 nl2sql-service。** 下文 §1-§6 为拍板前的现状与选项分析（原样保留，供追溯"为什么是 A"）；§7 起为 A 的执行记录。
- 日期：2026-10-18（初稿）；2026-10-18（决策 + Stage ①/② 落地记录）
- 来源：`docs/plans/plan-nl2sql-meta-lifecycle-2026-10-17.md` §11.6-G1（代码审计新发现）+ 待答 **Q25**
- 关联：`ADR-0006`（隔离维度契约，agent_server/sql 的 `sql_*` 三表已按 tenant/workspace 隔离）、`ADR-0007`（服务端断言身份）、`ADR-0009`（向量存储选型，pgvector 侧）

## 1. 现状（本轮逐个实读定位）

平台里存在**两条各自成型**的 Text-to-SQL 路，都不是空壳：

| 维度 | agent_server/sql（Vanna 式） | nl2sql-service（本项目） |
|---|---|---|
| 存储 | `sql_ddl` / `sql_docs` / `sql_examples` 三张 PG 表，**已按 ADR-0006 tenant/workspace 隔离**（`schema_store.py:17-83`，空 workspace 不再旁路全库） | `nl2sql_*` 六张表（列/指标/值/关系/别名）+ pgvector，作用域列默认 `''`（ tenant 维度尚未接入，见 §5.2 待拍板） |
| 上下文形态 | **自由文本三件套**：DDL 字符串 + 业务文档 + 历史范例 SQL，prompt 直接拼（`pipeline.py:24-40`） | **结构化元知识**：表/列/指标/值/关系/别名分型召回，取值结构化绑定、字面量核验、零结果分诊 |
| 管线 | 单函数：召回 → 生成 → guard → 只读执行（`pipeline.py`） | 14 节点图：extract → 四路召回 → filter → generate → validate → **validate_literals** → execute → **triage** → answer → **finalize(trace/session)** |
| 取值语义 | 无（DDL 里有列名即可，值对不对不管） | 只读探针 + 字面量核验（P0-8/P0-9），未识别取值拦截 |
| 多轮 | 无 | 四元组继承（M1-M6） |
| 数据权限 | 依赖账号（DB 侧） | L2 guard 表/列白名单 + L3 结果层脱敏（应用侧叠加） |
| 身份隔离 | **已接入**身份门 + ADR-0006 隔离 | 未接（tenant 维度待拍板，§5.2） |
| 消费方 | agent 平台内 subagent（`subagents/sql_agent.py`），通用助手场景 | 专职问数产品场景 |

⇒ 二者**能力有真实重叠**（都是"召回→生成→guard→只读执行"的 PG 向量路），但 nl2sql-service 在**取值正确性/多轮/权限**上明显更深，agent_server/sql 在**身份隔离/平台集成**上明显更前。这不是简单的"重复造轮子"，是两条各有侧重、部分重叠的路。

## 2. 未决的是什么

**收成一条，还是明确并存并写清边界。** 与 ADR-0009 同构的三选项：

| 选项 | 做法 | 代价 / 风险 |
|---|---|---|
| **A agent_server/sql 退役，统一到 nl2sql-service** | 平台 subagent 改调 nl2sql-service；`sql_*` 三表数据迁 `nl2sql_*` | ① nl2sql 要先补上 agent_server 已有的**身份隔离**（tenant/workspace 作用域 + 身份门，§5.2/Q6 拍板后才能迁）——否则是**倒退**；② 迁移 `sql_examples` 历史范例要映射到 nl2sql 的 relations/aliases 契约，不是 1:1；③ agent_server 现有调用方全部改端点 |
| **B nl2sql-service 的能力并入 agent_server/sql** | 把取值核验/多轮/权限层移植进 `pipeline.py` + `schema_store` | ① `pipeline.py` 从单函数膨胀成多节点，与 agent_server"轻量 subagent"定位冲突；② 取值探针要连业务库，agent_server 当前连的是其自管 PG，不是数仓；③ nl2sql 的元知识构建入口（P0-1/P0-2）要搬进 agent_server |
| **C 明确并存，边界写成契约**（现状 + 文档化） | 不迁；在 `ARCHITECTURE.md` 写清"哪类问数走哪条路"，加 lint 禁止起**第三**条 | 零行为风险；代价是长期维护两套（但两套服务定位不同：通用助手 vs 专职问数，未必是真浪费） |

## 3. 可先排除的判断

- **"必须二选一，否则就是技术债"**：不成立。两条路服务**不同产品定位**（agent_server 是平台通用 agent 的一个 subagent 能力；nl2sql-service 是专职问数服务）。定位不同时，"并存"可以是正确架构，关键是边界写清（选项 C 正是为此）。
- **"nl2sql 是 agent_server 的超集，直接让 agent_server 退役"**：**当前不成立**——agent_server/sql 已接入身份隔离（ADR-0006/0007），nl2sql 还没有。在 nl2sql 补上隔离前，A 是净倒退。

## 4. 前置依赖（不论选哪条都要先答）

1. **§5.2 / Q6**：nl2sql meta 语义层的租户维度怎么落（T0-D1：schema 出生即带 `tenant_id`/`workspace_id`）——**A 的硬前置**。
2. **§5.15**：元知识三态（YAML 作者格式 / API 入参 / meta 库服务层）与 agent_server 的 `store_ddl/doc/example` 入参形态是否要对齐。
3. 谁是这两条路的**归属 owner**（见 `docs/plans/nl2sql-meta-baseline-and-ownership.md` 的 owner 章节，当前待填）。

## 5. 待用户回答（Q25）

- A / B / C。倾向 **C** 的判据：两条路定位不同、合并的硬缺口（隔离 / 探针连库 / 管线重量）都不是"顺手能做"；先把边界写成契约 + 禁第三套，比强行合并更符合"不过度设计"。若选 A，则 §4.1 的租户维度是必须先落的前置。

## 6. 重启条件

1. nl2sql 接入身份隔离（tenant/workspace + 身份门）⇒ A 的"倒退"顾虑消失，值得重算。
2. 出现明确的"同一问数需求两条路都要答"的场景 ⇒ 并存的边界契约必须当场补细。
3. 有**第三**个 Text2SQL 实现出现 ⇒ 必须当场定 C 的"禁止第三套"不变量。

## 7. 执行记录（决策后追加，2026-10-18）

**Q25 答案：A。** 判据：① §4.1 硬前置（nl2sql 租户维度）已落地——meta 五表出生即带 `tenant_id`/`workspace_id`，P1-1 隔离（三列恒过滤 + 租户漏传 fail-fast）已实装并有真库判据，A 的"净倒退"顾虑消失；② 两条路定位重叠度随 nl2sql 成熟持续上升（取值核验/多轮/追溯都是 agent_server/sql 没有的），并存维护成本大于收益。

执行分三 Stage：

| Stage | 内容 | 状态 |
|---|---|---|
| ① | nl2sql 租户/工作区隔离（A 的硬前置）：schema 作用域列 + 查询侧恒过滤 + 漏传 fail-fast | **已完成**（commit `707a29c`；`tests/governance/` 隔离判据 + 真库 `tests/ha/test_tenant_isolation_real_pg.py`） |
| ② | `sql_*` 三表数据迁移 + 映射设计 | **已完成**（commit `e233d72`/`19bfe27`/`597ce56`/`0c65f76`，映射设计见 §7.1） |
| ③ | 消费方改端点：`subagents/sql_agent.py` 等 agent_server 调用方改调 nl2sql-service，agent_server/sql 代码退役 | **已完成**（commit `e92a784`/`76f29eb`/`78b1beb`，明细见 §7.2） |

### 7.1 Stage ② 映射设计（关键决策）

| 源（agent_server/sql） | 目标（nl2sql） | 落点 |
|---|---|---|
| `sql_ddl.content`（DDL 文本） | `nl2sql_column_info` | `ddl_parser.parse_ddl`（sqlglot：CREATE TABLE + `COMMENT ON`，表级约束不产列行） |
| `sql_docs.content`（业务文档） | 同作用域表的 `table_comment` | `associate_docs_with_tables`（词边界匹配；未命中文档记账不静默）+ **表注释读路径**（`_derive_tables` 带注释、`ColumnRepository.recall` 取该列——否则 docs 迁移只写不读） |
| `sql_examples`（问题→SQL 范例） | **新表 `nl2sql_example_info`（迁移 004）** | 见下 |

**范例为什么不用 `session_state.confirmed_pairs`**：后者是按 `session_id` 隔离的**会话态**（M6：人不确认的错题不进范例库），全局训练语料塞进某个 session 行既无自然语义、又会被会话生命周期管理干扰。故新表承载：`question` 自然键（重训练 upsert 更新 SQL 不叠副本）、`source human/machine`（机提未确认不进召回，同 `alias_info` 语义）、按 question 相似度向量召回（`ExampleRepository` + `recall_example` 节点 + 生成期 few-shot 槽）。**这条同时补上了 nl2sql 缺的 few-shot 能力**——agent_server 退役不等于能力净损失。

**铁律**：迁移只取文本、向量一律用目标侧 embedder 重算（源 embedder 可能不同模型/维度，拷贝 = 炸库或静默劣化）；作用域保真（源 tenant/workspace 原样带，`--tenant ''` 显式折叠单租户 legacy 库）；prune 只删范例（列有 MetricConfig + 迁移双写入源，误删会删掉配置构建的行）。

**验证状态**：单测 26 条 + 真库用例（`test_migration_write_path_on_real_pg`，skipif 双 DSN：写入/维度/注释合并/租户不串味/幂等/prune/ANN 召回机械性全过）。⚠️ 语义质量待复核：siliconflow 余额耗尽（402）期间迁移数据用的是确定性假向量，余额恢复后重跑同一命令即自动更新（upsert 自然键不变）。

### 7.2 Stage ③ 退役执行（2026-10-18）

** federation 侧早已就绪**：`agent_federation` 的 `text_to_sql` 能力在本 Stage 前已路由到 nl2sql-service `/api/query`（adapter 更早退役），真正 import `agent_server.sql` 包的只有三个消费方：

| 消费方 | 改法 | 契约变化 |
|---|---|---|
| `subagents/sql_agent.py`（图节点证据生产） | 改 nl2sql 瘦客户端（httpx POST `/api/query`） | 无（函数签名保留，llm 参数兼容保留但不再使用——LLM 归 nl2sql）；未配置 `NL2SQL_SERVICE_URL` 返回明确提示（同 search.py 降级契约）；HTTP 错误分类进证据 |
| `api/sql_router.py` `/sql/train`（上线端点） | 对外契约不变（路径/鉴权/请求响应形状），内部改 POST `/api/meta/ingest` | 响应新增可选 `report` 字段（摄入计数 + 三类记账）；flag 语义为"已摄入"；上游不可达 502、上游状态码透传 |
| `api/health_router.py`（`sql_backend` 标志） | `detect_dialect` 迁到 `agent_server/db_dialect.py` | 无（运维可见性不属于 Text2SQL 能力）〔⚠️ 本行的处置已由 §7.3 推翻：2026-10-28 灯与字段一并退役〕 |

**`/api/meta/ingest`（nl2sql 侧新增，commit `e92a784`）**：与迁移 CLI 共用同一写入 core（`services/ingest_service.py` 的 `build_migration_plan` + `write_scope`，Stage ② 上移的共享件）——在线摄入与批量迁移两条路只有一份写入逻辑。分工：CLI 搬历史 + `--prune`；端点管在线增量、**不 prune**（范例差异删是显式运维动作）。请求形状对齐 `SqlTrainRequest`（ddl/docs/examples 单串或列表都收）；作用域走 `resolve_scope`（ADR-0007 断言 > 请求体 > default，同 `/api/query`）；响应带回实际落点 scope + 三类记账。未接身份门（S-1）下与 `/api/meta/refresh` 同級定位（内部/运维端点，文档明示）。

**退役删除**：`applications/agent_server/sql/`（pipeline/schema_store/guard）+ `test_schema_store.py` + `test_sql_pipeline.py`；`test_sql_guard.py` 改导 `agent_core.sql.guard`（guard 是平台共享件，不随包退役）；`test_corpus_tenant_isolation.py` 删 3 条 sql_* 判据（留 skip 壳注明移交）；`test_isolation_dimension_contract.py` 的谓词配对扫描面改扫 nl2sql `meta_repository.py`（隔离契约未断，换承载文件）；README U-1 / query_router / rag.embed / pool_factory 的引用同步为史实。

**净效果**：平台内 Text2SQL 只剩一条路（nl2sql-service）；退役方（agent_server/sql）的**能力无损失**——few-shot 范例（004 + recall_example）、业务文档（table_comment 读路径）、在线训练（/api/meta/ingest）、隔离（Stage ①）在 nl2sql 侧全部有着落且已验证。

> ⚠️ **2026-10-26 状态订正（不改本 ADR 的决策结论）**：上文两处描述已被后续改动取代，按当时记录保留、在此标注现状——① 「作用域走 `resolve_scope`（ADR-0007 断言 > 请求体 > default，同 `/api/query`）」现为**拒收请求体归属**：`applications/nl2sql-service/nl2sql_service/api/routers/ingest_router.py:67-84` 对非空 `tenant_id` / `workspace_id` 直接 400，再以 `server_tenant_id()` **无实参**（无部署 default）取断言；② 「已验证」在**网关签名头**这条链上不成立：nl2sql 服务对 `X-Internal-Tenant` / `verify_internal_header` / `IdentityMiddleware` 实取零命中，应用由 `build_api_app` 构建且无 `add_middleware`；本机探针（fresh process，ContextVar 未绑定）实测 `server_tenant_id()` 抛 `ValueError`（`agent_core/memory/_tenant_gate.py:18-26` 无 env 回退），故 `/api/meta/ingest` 当前恒 401，`applications/agent_server/api/sql_router.py:61` 的签发对这条链是无效动作。收敛决策（Text2SQL 单路）不受影响；缺口已登记 `docs/architecture/agent-harness-capability-map.md` 行 238，修法（给 nl2sql 装同一实现的验签中间件）待方案批准。

### 7.3 后续修订（2026-10-28，问数终态落地批次 5）

推翻 §7.2 消费方表里第 3 行：`sql_backend` 不该留在平台侧。当时判为「无契约变化，运维可见性不属于
Text2SQL 能力」，但它其实是**一盏住错地方的灯**。

- **它不是一开头就假的**：Stage ③ 之前平台确实自己连业务库执行 SQL，`sql_backend` 是真读数。Stage ③
  把执行权交给 nl2sql-service 后灯没跟着搬家 ⇒ `settings.sql_dsn` 指的是**平台库**（与 `DATABASE_URL` 同源），
  `/health` 报的 `sql_backend=postgres` 只证明“平台能连自己的库”。这个漂移被当过上线证据记录
 （`docs/operations/minimal-release-runbook.md` 的问数行、`docs/operations/evidence/2026-10-12-release/readings.md`），
  所以本轮不止删字段，还要把“谁该报这个位”写清。
- **改法**：`sql_dsn` / `sql_max_rows` 两个字段、`agent_server/db_dialect.py`、根 `.env.example` 与
  `docker-compose.yml` 的对应键一并退役（实测消费点为 0）；平台 `/health` 改报 `nl2sql`（子代理注册位，
  与 `search`/`llm` 同类且**不回显 URL**）；共享契约 `HealthResponse.sql_backend` **字段保留**（零破坏），
  改由真正持有业务库连接的 nl2sql-service 上报它的 dw 方言；没配数据面报 null（`detect_dialect("")` 回落
  postgres，拿它当读数就是把“没有 dw”说成“有个 pg 可问”）。
- **同批发现并修的真缺陷**：graph 与 deterministic 两处空证据判据里还钉着退役前的「SQL_DSN 未配置」，
  而子能力早在 Stage ③ 就改口为「问数服务未配置…」⇒ 一条“根本没配服务”的提示被当成**真证据**送进合成步
 （不触发重试、也不给“证据不足”）。判据与文案收敛到单一来源 `applications/agent_server/subagents/degradation.py`。
- **门禁**：`test_health_fields.py::TestNl2sqlBit`（含“即使注着 SQL_DSN 也必须报 null”的假灯回归）、
  `test_empty_evidence_markers.py`（含反证：换回退役前的判据则缺陷重现）、nl2sql 侧
  `test_identity_gate_assembly.py::TestHealthReportsItsOwnDataPlane`、清单侧
  `tests/deploy/test_k8s_manifest_wiring.py::test_platform_does_not_inject_sql_dsn`。
- **依赖方向不变**：不新增跨层 import（`application → agent-runtime → agent-core` 单向）。
