# 方案评审报告：问数（nl2sql-service）元数据生命周期与检索质量补全方案

> 评审对象：`docs/plans/plan-nl2sql-meta-lifecycle-2026-10-17.md`（845 行 / 131 KB，2026-10-17 版，含 §11 自核验台账与 §12 冻结取证快照）
> 评审日期：2026-10-17
> 评审人：两轮独立评审合并（A 轮 = 五维架构评审；B 轮 = 现状基线对抗审计）。本文 §11 记录两轮分歧的处置。
> 评审方式：**对抗式实测** —— 不采信方案自述，逐条回源读代码 / 跑 grep / 实跑 sqlglot。全部断言标 `file:line`；无法本机实测的标注证据等级。
> 状态：<span style="color:#b35c00">**本行已按 2026-10-18 的两条新口径与方案并行追加修订，先读变更记录 v1.1 / v1.2**</span>。修订后的结论：
> - **仍是进 P0 前两项**：A1（`answer` 恒空，服务对外不产出答案）· Q25（两条 Text2SQL 路未裁，方向性风险）。
> - **A6 已改判**：使用者允许本地自建 Doris / MySQL 造数据测之后，它从"物理不可达"降为 **T-A「本窗口可做且可验」**，且是本窗口可收口的最大一块工程（见 §7-I2 v1.2④）。
> - **§5 的取值层结论已被方案 §5.8「探针单一入口契约 C1–C9」取代**，且本文 v1.0/v1.1 对 B 轮机制描述（P0-8② 打不打源）背书错误，已在 v1.2③ 自记更正。
>
> **📝 变更记录**
> - **v1.0**（2026-10-17）首版：合并 A/B 两轮。19 条现状实测（§2 A1–A6、§3 C1–C5）+ Q24 实跑结论（§4）+ 取值层合并解（§5）+ 五维评级（§6）+ 四批次工时（§7）+ 安全侧两处必改（§8）+ 待答项治理（§9）。
> - **v1.1**（2026-10-17）**撤回本文自己的一条方向错误 + 登记一条被并行批次取代的现状陈述**。基线 rev = `88a4cdc`（本文提交点），代码树自 `v1.0` 起**无已提交改动**（`git diff --name-only 88a4cdc..HEAD` 的 `.py` 计数 = 0）；但工作区存在**另一会话的未提交连接池加固批**（6 modified + 3 新文件，均在 `applications/nl2sql-service/`），故本文凡引 `dependencies.py` / `settings.py` / `postgres_client_manager.py` 者，**基线是未提交工作区态，不可复现**，对方提交后须以那个 rev 重取。
>   - ① **§11.3 瓶颈 2 的失效形状我写反了**：v1.0 记 B 轮"默认 `max_size` 下并发即排队"为成立，实则改造前 `AsyncConnectionPool(dsn)` 的默认是 `min_size=4 / max_size=None` ⇒ **无限新建后端连接**，天花板被推给 PG `max_connections`，超限以 `FATAL: too many clients` 形态冒出。**是无限扩张，不是排队**，两者排查方式相反。我当时由"共用一个池"直接推出失效形状，**没去读 psycopg_pool 的默认值**——与本文 §11.1 批评方案"凭模式猜"是同一类错，故在此自记。且这一半**已被对方本批修掉**（显式 min/max + `max_waiting=2*max_size` 快速失败 + `statement_timeout`），本文改判为「共用仍在（`dependencies.py:52` 与 `:64` 两行未变）、配额裸奔已由并行批次修复」，并**挂链其自述审计** `clients/pg_pool.py:4` 的「固化 2026-10-17 连接池审计的三个结论」⇒ 按本文 §11.3 给方案立的纪律（"须挂链不得当新发现"），瓶颈 2 的这一半是**重复发现一个已在修的问题**，不得自述为新发现。
>   - ② **§3-C2 的"唯一路由"陈述正被并行批次取代**：新增 `api/routers/pools_router.py`（`GET /api/pools`，`prefix="/api"`）⇒ 方案 §2 表里"全服务只有一个路由 / `routers/` 目录仅此一个文件 / `@router.*` 全服务命中 1"这条**现状事实一旦对方提交即失效**。C2 的结论本身不受影响（判 SSE 用的是三个真签名，与路由数无关），但引用措辞须限定为"`/api/query` 仍是唯一**问数**路由"。已在 §3-C2 就地加注。
> - **v1.2**（2026-10-18）按两条新使用者口径 + 方案并行追加做三处更正，**均在本文自身，不动方案**：
>   - ③ **§5 整节顶部加注：本文 5.3 的合并解已被方案 §5.8「探针单一入口契约 C1–C9」取代**，且 v1.0/v1.1 沿用 B 轮的机制描述**是错的**——P0-8② 不打源（它回的是问数 PG 里的字典，正是 D7 二分），真正的第二触发是 ③ 零结果分诊探针。⇒ "双重"的代价是两处形状不同、缓存键不同、超时与降级各实现一遍（故障面翻倍），不是 2× RTT。**这是本文未把机制读细就背书 B 轮的一条，自记。**
>   - ④ **§7-I2 按三档可达性重判**：使用者开了"允许本地自建 Doris/MySQL 造数据测"之后，**A6 从"物理不可行"降格为"本窗口可收口的最大一块工程"**（T-A 本地可做可验：驱动选型、每源只读机制矩阵、内省 SQL 形状、Q24 的执行侧半段）；成本类结论落 T-B 不外推；P1-5 与 Q10a 权限才是永久 T-C。⇒ v1.0 把 A6 写成"阻断"的读感（"这窗口什么都做不了"）是误导，已更正。
>   - ⑤ 三档定义与 T-C 清单**不在本文复述**，指针为方案 §0.1 与 `docs/operations/unconfirmed-items.md` E12–E16，避免四处漂移。
>
> **⚠️ 阅读顺序**：先读 §1 与 §2 的 A1/A6/A5，再读 §7 批次。§4 是本轮新增的实测证据（方案标为"需实测不靠推理"的 Q24 已跑完）。

---

## 1. 总体结论

**技术事实层面合格，工程执行层面不合格，现状基线选错。**

方案的**外部技术调研**质量高于本仓绝大多数设计文档：Doris 4.0 版本门、`ADD INDEX` 只登记定义而存量须 `BUILD INDEX`、pgvector `sparsevec` 的三条真实限制、ParadeDB 的 AGPL-3.0 与访问方法互斥、Qdrant `modifier:"idf"` 是查询时统计且引擎不分词——这些核对得准且给出了边界。§11 的自核验机制（161 条去重引用逐条回查、13 条撤回、否定式断言改用不受 `.gitignore` 影响的原始 grep）与 §12 的冻结取证快照，是本仓罕见的自证纪律。§7 归属边界（2025 内网 vs 2026 平台、"禁写已实现取值下推"、"只读保证不要答 EXPLAIN"）尤其克制，应完整保留。

但它缺四样东西：**排序、工时、owner、回滚路径**（方案 §11.6 自己承认后两条）。⇒ 所以它**批判的空洞选错了优先级**：H1–H4（构建入口 stub / 无刷新触发 / 不幂等 / 无质量回路）真实存在，但都不是当前最致命的。本轮实测出六处方案未登记的现状（§2），其中 A1 意味着**即使 P0 十项全部做完，这个服务对外仍然不产出答案**；A6 意味着**当前它只能打 PostgreSQL，打不到 Doris/MySQL**——但按 v1.2 改判，A6 是**本窗口可自建源、可做可验**的工程项而非不可达项（见 §1 表与 §7-I2）。

| 级别 | 编号 | 问题 | 必须修 |
|---|---|---|---|
| 🔴 阻断 | A1 | `answer` 键恒为空，联邦侧只 warn 不改行为 | 进 P0 前 |
| 🔴 阻断 | A6 | 无 MySQL 协议驱动，DW 仓储是 PG 专有 ⇒ D1「打 Doris」当前不可达。**v1.2 改判：非阻断，是 T-A 本窗口最大可收口工程**（本地可自建源测），详见 §7-I2 | 进 P0 档，非进 P0 前 |
| 🔴 阻断 | A5 | Q25 未裁：平台内两条 Text2SQL 路都接线在跑 | 进 P0 前 |
| 🟠 高 | A2 | `generate_sql` 丢上下文；`filter_table`/`filter_metric` 白做 | I0 |
| 🟠 高 | A3 | `add_extra_context` 是空转节点，而 P1-4 把它当既有能力 | I0.5 |
| 🟠 高 | A4 | 五处配置全是死配置，契约测试只锁值不锁行为 | I0 |
| 🟡 中 | C1–C5 | 五处内部矛盾（详见 §3） | 改方案文档 |
| 🟡 中 | F1/F2 | `filter_clause` / `extra_cols` 是裸插值 SQL 片段，标识符正则管不了 | I0 |

---

## 2. 现状实测：方案未登记的六处

> 以下全部为本轮读代码确认，非推断。方案 §2「现状事实」表与 §11.4「通过项」均未覆盖。

### A1 🔴 `answer` 从不产出——服务对外只回 SQL 与行数据，没有答案

12 个节点里**没有答案合成节点**：`extract_keywords` / `recall_column` / `recall_metric` / `recall_value` / `merge_retrieved_info` / `filter_table` / `filter_metric` / `add_extra_context` / `generate_sql` / `validate_sql` / `execute_sql` / `correct_sql`，而 `agent/graph.py:75` 是 `add_edge("execute_sql", END)`。

全仓 `"answer"` 的写入点只有两处，**都在错误分支**：`services/query_service.py:23`（graph 未初始化）与 `:39`（异常兜底），两处都写 `""`。成功路径 `:31` 是 `result.get("answer", "")` ⇒ 图状态里从无该键 ⇒ **恒返回空串**。

下游不报错：`applications/agent_federation/agent/async_subagents.py:94-98` 的 E1b 内容校验只 `logger.warning("远程响应 answer 为空（契约形状通过但内容空洞），疑似子服务退化")`，随后 `return {"answer": data.get("answer", ""), **data}` 原样透传。

**精度订正（对 B 轮措辞）**：不是"永远返回空答案 ⇒ 服务不产出"。`SqlQueryResponse` 仍带 `sql` 与 `result`（行数据），联邦侧也透传了整个 `data`。准确形状是**"有数据、无自然语言答案"**——缺一个合成节点，不是重建输出层。这个区别直接决定 I0-1 的工作量。

**后果**：P0-8④ 要加的 `matched_values` / `unmatched_terms` / `dict_hit` 与 P1-3② 的口径标签，**当前没有任何承载点**。方案把它们写成"返回体增字段"，实际是先要有答案合成这一步。

### A2 🟠 召回结果被丢弃——两个过滤节点白做，RRF 跨实体类型融合

- `agent/nodes/generate_sql.py:30` **`metric_infos=""` 硬编码**；`:29` `table_infos=retrieved_info`；`:32` `db_info=extra_context or "postgresql"`。
- 该节点只读 `query` / `retrieved_info` / `extra_context` / `llm` 四个键 ⇒ **`state["tables"]` 无消费方**。而 `filter_table.py:15/23/27` 的全部输出就是 `{"tables": ...}` ⇒ `filter_table` 与 `filter_metric` 两个节点做了事但结果进不了 prompt。
- `merge_retrieved_info.py:24` 把 `[columns, metrics, values]` **三类异构实体融进一个榜**；`:12` 的 RRF key 是 `json.dumps(item, sort_keys=True, ensure_ascii=False)` 即**全量内容哈希** ⇒ payload 任一字段微变，同一实体被当成两条，RRF 的"多路投票"退化为"去重后按单路 rank 排"。

**对方案的影响**：P0-5「别名精确匹配优先于向量」与 P0-8①「召回值改结构化绑定（不再塞 `examples`）」的落点描述**不成立**。"塞进 `examples`"是**课程侧**形状（`courses/.../merge_retrieved_info.py:38-46`）；平台侧的真实形状是"三类实体混成一个 JSON 塞进 `table_infos`"，比 examples 更粗。方案 §4 P0-8 的「涉及」列写的是基名 `merge_retrieved_info.py:38-46`——而 §9 开头自己就警告过"基名引用不可唯一定位"。

### A3 🟠 `add_extra_context` 是空转节点，P1-4 把课程侧能力当成了平台侧既有能力

平台侧 `agent/nodes/add_extra_context.py` 的**完整函数体**是：

```python
extra = state.get("extra_context", "")
return {"extra_context": extra}
```

原样返回，不注入任何东西。

而方案 P1-4 写的是：「`add_extra_context` **已注入** dialect 与 version（`dw_mysql_repository.py:19-23`）**可直接作分支依据**」。那个 `dw_mysql_repository.py` 在方案 §9 证据清单里明确列于 `courses/zhanggui-wenda/data-agent/app/repositories/mysql/dw/` 之下——**是课程侧文件**。

⇒ **P1-4 的依据是课程侧实现，被当成了平台侧既有能力**，正是方案 §7 自己明令禁止的混述。更值得注意的是它**通过了 §11 核验**：§11.4 把 `dw_mysql_repository.py:19-25` 列为"行内容逐条比对一致"——核验检查了"这行写得对不对"，没检查"这行属不属于被论证的那个系统"。**这是比行号漂移更难发现的一类错，且方案的核验方法在结构上抓不到它。**

平台侧真实形状：`generate_sql.py:32` 硬编码 `db_info=extra_context or "postgresql"`，**没有任何 dialect / version 注入**。⇒ P1-4 不是"可直接作分支依据"，是 100% 新建，且前置是给 `add_extra_context` 填上实现。

### A4 🟠 五处配置全是死配置——B 轮 C3 成立，且机制比其表述更细

| 配置 | 定义 | 读取点 | 实际生效 |
|---|---|---|---|
| `rrf_k` | `settings.py:36`、`app_config.yaml:18` | 无 | ✗ `merge_retrieved_info.py:7,24` 用字面量 `k=60` |
| `retrieval_top_k` | `settings.py:35` | 无 | ✗ `recall_value.py:22` 硬编码 `top_k=10` |
| `sql_max_correct_retries` | `settings.py:41` | `graph.py:28`、`correct_sql.py:28` 从 **state** 取 | ✗ state 从不注入 ⇒ 恒回落 3 |
| `sql_read_only_guard` | `settings.py:39` | 无 | ✗ 守卫无条件执行，开关不受控 |
| `sql_max_rows` | `settings.py:40` | `validate_sql.py:13` 从 **state** 取 | ✗ 同上 ⇒ 恒回落 1000 |

根因是一个：`services/query_service.py:25` 组装 state 时只塞 `query` / `context` / `llm`（+ 可选 `metric_config`），**settings 里的这五个键一个都没进 state**。所以"有读取点"的三项也是死的。

`tests/test_nl2sql_contracts.py:129-131` 只断言默认值（`retrieval_top_k == 10`、`rrf_k == 60`、`sql_read_only_guard is True`）⇒ **B 轮 C3 成立**：方案 §11.1-R1 撤回了「契约测试只锁开关值不锁行为」，但这句话对上述配置**仍然为真**。R1 撤回的只是"没有任何 guard 用例"那半句（`tests/nl2sql_service/test_nodes_validate_sql.py:7-49` 确有 6 个行为用例），撤回范围被读宽了。

### A5 🔴 Q25 必须排第一——两条 Text2SQL 路都是接线在跑的

方案把 Q25 列为待答第 25 项、自定前三优先级是 Q10a → Q23 → Q24。实测两条路**都不是备选，都在装配线上**：

- **agent_server 侧**：`capabilities.py:42` 注册 `sql_query` → `subagents/sql_agent.py:7,18` 调 `text_to_sql` → `sql/pipeline.py`；`agent/intent_bridge.py:18` 把 `text_to_sql` 意图映射到 `sql`。
- **federation 侧**：`agent/async_subagents.py:279` 与 `agent/config.py:50-55` 把 `text_to_sql` 子服务指向 nl2sql-service `/api/query`。

且 **agent_server 那条已有 nl2sql 缺的三样**：
1. `sql/guard.py:6-14` 的 `detect_dialect(dsn)` 动态方言（sqlite / postgres / mysql，其余回落 postgres）；
2. `sql/pipeline.py:111` 正确消费 `settings.sql_max_rows`（对照 A4，nl2sql 侧是死的）；
3. `sql/schema_store.py:17-30` 的 `store_ddl` 每行带 `tenant_id` + `workspace_id` 且过 `resolve_tenant`（ADR-0007 服务端断言）。

反过来 nl2sql 那条有 agent_server 缺的：12 节点 LangGraph 图、指标/取值三路召回、`correct_sql → validate_sql` 回环（`graph.py:74`）。

而 agent_server 那条**执行层只支持 sqlite 与 postgres**——`pipeline.py:86` 对其它 DSN 直接 `raise RuntimeError(f"暂不支持的业务库类型: ...（MySQL 留待 Phase 3）")`。

⇒ 收敛方向决定 P0-1 / P0-2 / P0-5 / P1-6 是"新建"还是"复用"。**答错它等于把语义层建两遍**，40+ 人日投错方向。前三优先级应改为 **Q25 → Q23 → Q10a**；Q24 已由本轮实测解决（§4），不必占位。

### A6 🟠 无 MySQL 协议驱动，DW 仓储是 PostgreSQL 专有 ⇒ D1 当前只能打 PG（v1.2：由阻断改判为 T-A 工程项）

| 断言 | 证据 | 结论 |
|---|---|---|
| 依赖里没有任何 MySQL/Doris 客户端 | `applications/nl2sql-service/pyproject.toml:20-27` 只有 `psycopg[binary,pool]` + `pgvector` | 探针与执行都无载体 |
| DW 仓储用 PG 专有语句 | `repositories/postgres/dw/dw_repository.py:18` `SET default_transaction_read_only = on`；`:33` `obj_description((...)::regclass)` | 连接级只读这道防线在 MySQL/Doris **不存在** |
| 内省方法是死码且有缺陷 | `get_table_schema`（`:23`）/ `list_tables`（`:31`）全仓**零调用方、零测试** | 从未被执行过 |
| 配置也是 PG 形状 | `conf/meta_config.yaml` `dw_db.schema: "public"` | — |

**关于 `get_table_schema` 的一处待实跑确认（证据等级：静态判据 + 死码事实）**：它 `SELECT column_name, data_type, column_comment FROM information_schema.columns`。PostgreSQL 的 `information_schema.columns` **没有 `column_comment` 列**（PG 取列注释用 `col_description()`）；同文件 `list_tables` 恰恰用了 PG 正确写法 `obj_description(...)`，两处不一致本身即是佐证。该方法零调用方零测试 ⇒ 从未执行 ⇒ 缺陷不会暴露。**待一次实跑确认**，但无论结果如何，P0-3 都不能建立在它之上。

⇒ 方案 P1-4 被写成"谓词模板按源分支"，实际是**驱动层 + 连接池 + 每源只读机制 + 元数据内省**四处重建。这是全案最大的工时低估来源。

**改进（新增 P0-0「源访问层」）**：驱动选型（Doris 走 MySQL 协议 ⇒ `aiomysql` 可用）、独立连接池、**每源只读机制矩阵**（PG = 会话 GUC／MySQL = `SET SESSION TRANSACTION READ ONLY` + 只读账号／Doris = `GRANT SELECT_PRIV` + workload group）、超时、参数化风格；判据 = 同一条 SELECT 在三源各跑通一次并留下 EXPLAIN。第一个用例就修 `column_comment`。

---

## 3. 方案内部矛盾五处

### C1 §3 非目标写"不改节点链拓扑"，但拓扑一定会变

P0-8③ 要新增零结果分诊探针、④ 要返回体语义、P1-3② 要口径标签、A1 要答案合成节点——这些都需要**新节点** + `SqlQueryResponse` 契约变更。§3 的括注（"但要改生成上下文的注入契约"）覆盖面不足。**非目标这一句低估了 blast radius，直接影响工时可信度。**

### C2 §5.3 轴 3 用"SSE 流式、用户等首 token"论证检索选型，而该服务零 SSE

精确重测：`StreamingResponse` / `text/event-stream` / `EventSourceResponse` 三个真签名在 `applications/nl2sql-service/` 命中 **0**；`api/routers/query_router.py:15` 是普通 `POST /api/query`，返回 `SqlQueryResponse` JSON。

⚠️ **措辞限定（v1.1）**：本文 v1.0 写的"唯一路由"已被并行批次取代——工作区新增 `api/routers/pools_router.py`（`GET /api/pools`，运维可观测）。准确表述是「`/api/query` 是唯一**问数**路由」。⇒ 连带地，方案 §2 现状表里"全服务只有一个路由 / `routers/` 目录仅此一个文件 / `@router.*` 全服务命中 1"这条**现状事实**在对方提交后即失效，须一并订正（该条不是本文结论的前提，C2 判的是 SSE 有无，与路由数无关，故撤回范围按纪律收窄到措辞）。

⚠️ 复测注意：不区分大小写地 grep `sse` 会命中 57 处**假阳性**（`assert` / `assembly` 的子串）。B 轮与本轮都先被这个骗过一次。

⇒ §5.3 轴 3 的 800 ms 首 token 预算**前提不成立**（SSE 在 agent_server / federation 侧，不在本服务）。延迟预算仍需要，但论证依据要换成"`/api/query` 是同步 JSON、上游联邦子代理有 HTTP 超时"，且预算值本身仍是 Q20 待答。

### C3 见 §2-A4

### C4 "消除取值副本"是核心收益，但有一条路径上副本问题不存在

`agent/nodes/recall_value.py:12-15`：`metric_config` 非空时直接返回配置里的 `values`，**根本不碰仓储**。⇒ 走 API 入参注入这条路时，P0-7「副本退役」针对的问题不存在。方案未区分两条路径，会把"退役副本"的收益算重。

### C5 P0-1 判据过软，能放过一个静默丢数据的实现

`services/meta_knowledge_service.py:24` 是 `stats = {"columns": 0, "values": 0}`，而 `:25-28` 的循环**只处理 `table.get("columns", [])`，`stats["values"]` 此后从未自增**。YAML 的 `values:` 段（`config/metric_config.example.yaml` 里确实有）根本不写；metrics 在另一个方法 `build_from_metrics` 里，`build_from_tables` 也不碰。

⇒ 方案 P0-1 的判据"跑一次能把 YAML 声明 + DDL 派生结果落到元数据库，并产出可查的构建报告"，会被一份 `{"columns": N, "values": 0}` 的报告**满足**，而全部值定义静默丢失。

**判据收紧为**：YAML 声明条数 == 落库条数（分 columns / metrics / values 三类各自比对）、二次运行 diff == 0、三类计数**均非零**（源声明非空时）。

---

## 4. Q24 实测结论：守卫方言能力矩阵（方案标为"需实测不靠推理"，本轮已跑）

**先纠一个方案未登记的事实**：本仓实装 **sqlglot 30.20.0，原生支持 `doris` 与 `starrocks` 方言**（`sqlglot.dialects.dialect.Dialect.classes` 实测含二者）。方案把方言当未知风险，其实方言是现成的。

用 `agent_core.sql.guard.validate_sql` 实跑 8 组语句 × 3 方言：

| 语句 | `postgres` | `doris` | `mysql` |
|---|---|---|---|
| `where city match_any '廊坊 廊坊市'` | **拒·解析失败** | **拒·解析失败** | 拒 |
| `match_phrase` + `score()` | **拒** | **拒** | 拒 |
| MySQL `match(name) against('展会' in boolean mode)` | **放行但改写成 `name @@ '展会'`** | 正确保留 | 正确保留 |
| 反引号标识符 `` `order id` `` | **拒** | 放行 | 放行 |
| 无 LIMIT / 超大 LIMIT | 三方言均正确补齐/截断 | 同 | 同 |
| `date_format` / `IN` / 普通谓词 | 三方言一致 | 同 | 同 |

**两条硬结论**：

1. **方言错配是"静默改写成错语法"，不是报错。** MySQL 全文匹配被 `postgres` 方言改写成 PG 的 `@@` 运算符——发到 MySQL 会失败或语义漂移。这证实了方案 §11.2-W3 的警告方向（"不能写成白名单照样生效"），也说明 P1-4 不只是"加谓词模板"，**必须先按源把 dialect 参数传对**。`detect_dialect` 在 `agent_server/sql/guard.py:6-14` 已有现成实现可抄；注意它只有 sqlite/postgres/mysql 三个分支、其余回落 postgres，而 Doris 走 MySQL 协议时 DSN 是 `mysql://` ⇒ 会返回 `mysql`，这条恰好可用。

2. **Doris 的 `MATCH_ANY` / `MATCH_PHRASE` / `score()` 连 sqlglot 的 `doris` 方言都不认** ⇒ 白名单守卫会**拒绝**它们。这直接打掉两件事：
   - §5.7 路线一 / 路线二（Doris 倒排索引）作为备选路径**当前不可用**——生成的 SQL 过不了守卫；
   - **P0-8③ 零结果分诊探针的示例 SQL 本身就是 `select 1 from t where city match_any '廊坊 廊坊市' limit 1`，会被自己的守卫拦下。** 方案通篇没有意识到"守卫与被守卫 SQL 的方言能力不匹配"这一层。

**改进（新增 P0 级前置「守卫方言能力矩阵」）**，三个候选：

| 候选 | 做法 | 代价 | 判定 |
|---|---|---|---|
| 甲 | 系统自发的探针/分诊 SQL **不过 `validate_sql`**，走固定模板 + 参数绑定 | 需新增一条独立白名单路径 | **推荐**：探针是代码生成而非 LLM 生成，用固定模板比 SQL 解析更安全 |
| 乙 | 给 sqlglot 注册 Doris 方言扩展支持 `MATCH_*` | 长期维护成本、跟随 sqlglot 升级 | 不推荐 |
| 丙 | 放弃 Doris 倒排索引路线 | 与 §5 的合并解冲突 | 部分采纳 |

**推荐甲 + 丙 组合**：系统自发探针用固定模板 + 绑定参数；LLM 生成的 SQL 只允许 `=` / `IN` / `LIKE`；Doris 全文能力**不进 LLM 可生成集合**。这样不必改 sqlglot，Q24 从"未证"变成"已定形"。

---

## 5. 取值层：探针路线的成本模型与合并解

> **⚠️ 本节 v1.2 已被方案取代，且含一处对本文的更正（2026-10-18）**
> 方案已新增 **§5.8「探针单一入口契约 C1–C9」**（由并行会话追加），其结论比本节 5.3 的合并解**更紧也更正确**，三件事按此读：
> 1. **本文 §5.1/§5.3 沿用 B 轮的机制描述是错的**：B 轮说"双重触发 = P0-9 召回探针 + P0-8② 生成后探针，冷缓存 5×2=10 次往返"。实则 **P0-8② 不打源**——它的动作是 sqlglot 抽 `(列, 常量)` 回**问数 PG 里的字典**校验（正是 D7 的"码表＝元数据在 PG"二分），本地零源成本。真正的第二触发是 **P0-8③ 零结果分诊探针**（仅空结果/全 0 时发）。⇒ 所以"双重"的代价不是 2× RTT，而是**两处形状不同（取集合 vs 验成员）、缓存键不同、超时与降级各实现一遍**——故障面翻倍。本文 v1.0/v1.1 把这条判为"方向正确、修法可采纳"，属**未把机制读细就背书**，此处更正。
> 2. **本文 5.3 的合并解已被 §5.8 覆盖并加强**：C2 召回阶段零源查询、C3 每问 1–3 个字面量批量 `IN` 一次查完、C5 分区裁剪强制（不带分区谓词**不允许发**）、C7 探针超时**不得依赖池级 `statement_timeout`**（dw 池 30s 对探针太松）改为 resolver 内 `asyncio.wait_for` + 连接级 `SET LOCAL` 双保险 + 信号量并发 2–4、C8 降级链从 P2 提到默认能力。⇒ 收敛后的验收是"**冷缓存单问源查询次数 ≤ 3**"，比本文建议的"≤4 次 / 300 ms"更严格且多了可抓文本断言的那半。本文的 5.3 分层表**不再作为落点**，只作论证留档。
> 3. **本文 5.2「路线一才是正解、应恢复为默认」这一条被方案 §5.8-C9 采纳，但采纳的是契约位置、不是成本结论**：C9 写"权限（Q10a）下来后字典优先、探针兜底……把路线一当'性能债备选'会长期停留在探针形态，而它才是消除探针的正解"。⇒ 本文这条判断成立。但它原先赖以成立的判据（M1 重灌耗时、探针 P95、O1 新数据曝光比）现在落在 **T-B / T-C**（见方案 §0.1），所以本条的最终状态是**「方向已定、成本结论纸面待现网」**，而不是"已验证"。

### 5.1 两轮评审的分歧

- **A 轮**：只读探针的**成本模型不成立**——扇出是二维的、把"候选生成"当"存在性检查"、T+1 缓存每日集体冷启动。
- **B 轮**：只读探针是**最强的设计点**（不动源、无幽灵值、无陈旧统计），但指出"探针双重触发"是最贵的隐形开销。

**处置：两轮都对，且 B 轮的修法解决了 A 轮的主要批评。** 详见 5.3。

### 5.2 A 轮的三点成本分析

1. **扇出是二维的**。探针次数 = |提及实体| × |`linkable` 候选列|。方案 §5.2-B1 批判课程实现"对每个关键词单独 `await search`，线性放大时延、无并发无批量"——探针路线是**同一形状的更贵版本**：每次代价从"查一个索引"变成"扫一个 4 亿行列存"，放大系数还多一维。方案没有对照自己。
2. **存在性检查 ≠ 候选生成**。探针答的是"值 X 在不在列 C"（可走索引）；value linking 要的是"给定『廊坊』，找哪列哪个规范值"（需扫描）。对非 key、非分区列做 `LIKE 'x%'`，方案自己承认"4 亿行仍是秒级开销"。⇒ **便宜的码表已被放进 PG（D7），昂贵的自由文本恰好留给探针**，成本分布与设计意图相反。
3. **缓存每日集体冷启动**。T+1 ⇒ `source_snapshot` 每日变一次 ⇒ 全量缓存每早失效。"版本不变则永久有效"在 T+1 语义下等于"有效期 ≤ 24 h"。方案把它写成"复杂度大降"，但没算命中率、没提预热。

**由此得出的一条与方案相反的默认值**：§5.7 路线一（在**问数自有 Doris 库**里建派生取值字典小表，`INSERT OVERWRITE` 全量覆盖）**不应降级为性能债备选**。理由：
- 它**不违反 D6**——D6 是"不改数据源"，在自己库里建派生表只读源、不写源；
- 方案自己写了它"只需 Q10a、不求 BI 团队"、"每次全量覆盖 ⇒ 幂等 / 幽灵值 / 陈旧统计三个问题**结构性不存在**"；
- 它同时规避了 §4 结论 2 的守卫问题——派生表上的匹配由**系统自发的固定模板 SQL** 完成，不需要 LLM 生成 `MATCH_*`。

⇒ **方案把具备全部优点的选项降级为备选，依据是对 D6 的过宽解读，而非成本分析。这是全文最该被推翻的一个默认值。**

### 5.3 合并解（收敛后的取值层设计）

B 轮瓶颈 1 的修法是"召回阶段不探针，只做生成后字面量校验（每问 1–3 个字面量）"——把二维扇出砍成一维，A 轮采纳。但它留了一个洞：**召回阶段完全不匹配取值 ⇒ 生成时模型手里没有规范值**，只能凭字面猜，靠生成后校验纠正 ⇒ 校正循环次数上升，而 `sql_max_correct_retries` 恰好是死配置恒为 3（A4）。

**合并后的分层**：

| 取值种类 | 召回阶段 | 生成后校验 | 依据 |
|---|---|---|---|
| 码表（定义出来的：行政区划、行业分类、状态） | **PG 的 L1 别名/码表**，热更新，带 alias + deprecated | 不需要（注入的是编码） | D7；C4 证明 `metric_config` 路径已有雏形 |
| 低基数枚举（distinct 出来但基数 < 5,000） | 不探针；靠 L1 或直接让模型写字面 | **探针存在性校验**，每问 1–3 次，带分区裁剪 + 批量 `IN` | B 轮瓶颈 1 修法 |
| 高基数自由文本（展会名、场馆名、企业名） | **§5.7 路线一派生小表**（问数自有 Doris 库，全量覆盖） | 同上 | A 轮 5.2；规避 §4 守卫问题 |
| 未声明 `linkable` 的列 | 一律不进候选，并**记录原因** | — | P1-2 |

**探针的三条硬约束**（缺一不可，写进 §6 验收）：
1. **列名只能取自 `linkable` 枚举，LLM 不得指定新列**——否则 LLM 可指名探任意列，绕过基数闸门读到手机号/证件号，这是真实的越权读；
2. **值参数走绑定，探针 SQL 文本里不出现未转义的用户输入**；
3. **每请求探针预算上限**（建议 ≤4 次、并发 2、单次超时 300 ms），超限走拒答而非硬扫。

**MySQL 侧缓存失效必须给 TTL 兜底**（B 轮瓶颈 3）：Doris 有分区号可做 `source_snapshot`，MySQL 的"水位"是 Q16 待答 ⇒ 实时源等价于**永久缓存**，陈旧召回不会报错。建议缓存键有效期取 `min(source_snapshot, 15 min)`。

**跨源语义必须显式声明**（B 轮瓶颈 4）：D5 只解决"用户选源"，没回答"同一问题是否需要跨源合并"。不支持就写进非目标并定义拒答话术；支持则口径标签与缓存键都要按 `(源, 快照)` 复合。

### 5.4 P0-9 与 P1-5 的依赖必须做成硬门（最高事故风险）

探针把 LLM 触发的 ad-hoc 扫描打进与 **BI 大屏共用**的 Doris 集群（D2），唯一护栏是 P1-5 的 workload group，而 P1-5 吊在 Q15（能否申请、谁批，跨团队）。方案只写了一句"并与 P1-5 的 workload group 排队联动"。

⇒ **在负载隔离未确认前上线探针 = 拿 BI 大屏做压测。** 把"P1-5 已实测生效（`SHOW WORKLOAD GROUP` 可查 + 超限查询被排队/拒绝）"写成 P0-9 的**上线前置门**，不是并列项。未过门则探针只允许打 MySQL 只读副本，或改走 5.3 的派生小表。

另注意方案已登记的一条官方约束：workload group 排队参数**只在单 FE 粒度生效**，实际并发 ≈ `max_concurrency` × FE 数——配错等于没配。

---

## 6. 五维评级

| 维度 | 评级 | 依据 |
|---|---|---|
| 架构设计 | **中** | 加分：D7 二分（码表=元数据 / distinct=数据）是全案最高价值判断；"要匹配的东西在不在查询引擎里"是可用判据；改名保旧名 alias + deprecated（§5.3 轴 2 细化）体现了真实领域理解。扣分：未裁 Q25 就默认在 nl2sql-service 建第二套语义层（A5）；**图拓扑与数据流契约脱节**——12 节点里 1 个空转（A3）、2 个白做（A2）、1 个输出键从不产出（A1） |
| 技术选型 | **良** | 元数据留 PG + 取值下推 + 不引 ES/Qdrant，方向正确且省运维；四层降级 + 每层记命中来源是对的；反模式清单质量高（尤其"在无重灌作业的前提下把 IDF 乘死"、"BM25 绝对分设跨查询固定阈值"，且区分了同一个 0.6 在 ES 是误用、在 Qdrant 是 cosine 可比）。扣分：§5.1–§5.3 已被自身判定"作废/备查"，占全文约三成，属决策日志而非方案；探针默认值的依据是对 D6 的过宽解读（5.2） |
| 实施路径 | **差** | 无依赖图、无切片、无工时。P0 十项平铺而实际有强序（§7）；P0-1 判据过软（C5）；缺"退役一条在工作的检索路"的回归判据（§7-I2）；缺 SSE/返回体契约的消费者审计（§7-I3） |
| 风险控制 | **中下** | §7 归属边界是全文最该保留的部分，Q21 的 11 处受影响面清点很扎实。扣分：探针默认路线**没有降级链**——源超时/不可用 ⇒ 取值匹配整条断，而 P2 把"降级与拒答"写成"想到即可，不必先做"；P0-9 与 P1-5 的依赖没做成硬门（5.4）；22 个待答零 owner、零截止、零默认假设（§9） |
| 资源投入 | **不合格** | 服务实测 **1,690 LOC（含 289 行测试）**，方案 845 行 / 131 KB。P0+P1 落地估 3.5–4.5 K LOC + 1.5 K 测试 ⇒ **服务规模约 ×3**；A 轮独立估算 **≈55–85 人日（≈3–4 人月，单人，不含跨团队等待）**。两个口径都指向同一结论：**不可能全做**，Q5 的答案必须是"P0 里选 5–6 项" |

---

## 7. 批次、依赖与工时

> 人日为单人、含测试、**不含跨团队等待**。B 轮给 LOC 口径、A 轮给人日口径，下表取 A 轮。

### I0 止血（≈5 人日，不动架构，收益立即可见）

| # | 动作 | 补的洞 | 估算 |
|---|---|---|---|
| 1 | 新增答案合成节点 + `matched`/`unmatched`/`dict_hit`/口径标签契约字段 | A1 | 2 |
| 2 | 接线五处死配置（`query_service.py:25` 把 settings 注入 state），每项加**行为**用例而非值断言 | A4 | 1 |
| 3 | 修 `generate_sql` 丢上下文（传 `tables`、`metric_infos`）；RRF 改**同类内部多路融合**、key 用 `(table, column)` 业务键 | A2 | 1 |
| 4 | `nl2sql_*` DDL 入版本控制（Q23），含修 `get_table_schema` 的 `column_comment` | A6、N4 | 1 |
| 5 | `filter_clause` / `extra_cols` 收敛为结构化谓词 | F1/F2（§8） | 含在 4 |
| — | **裁 Q25**（不裁则 I1 之后全部可能返工） | A5 | 决策 |

### I0.5 契约与方言（≈3–5 人日，两轮都漏了的批次）

| # | 动作 | 依据 |
|---|---|---|
| 1 | `add_extra_context` 填实现：注入 dialect + version | A3 |
| 2 | dialect 按源传对（抄 `agent_server/sql/guard.py:6-14` 的 `detect_dialect`） | §4 结论 1 |
| 3 | 守卫方言能力矩阵：系统自发探针走固定模板 + 绑定，不过 `validate_sql`；LLM 可生成集合限 `=`/`IN`/`LIKE` | §4 结论 2 |
| 4 | **元数据契约 schema 化**：pydantic 模型定义 YAML（含 `aliases` / `linkable` / `datasource_id` 三个新字段）+ 加载期 fail-fast + `metric_config.example.yaml` 同步 + 契约测试 | 方案只在 §5 备选 A 备注里提了一句"要把 YAML lint/schema 校验做上"，**无编号项、无判据**；而 P0-5 / P0-9 / P1-6 三项都要新字段，不做则各自发明字段名 |

### I1 生命周期（15–20 人日）

P0-1（**判据按 C5 收紧**；必须合并既有 P3 的 N+1 —— `meta_knowledge_service.py:47-51` 逐列 embed + 逐列 save，改批量）+ P0-2（稳定 ID + 差异重建）+ P0-3（漂移检测，两源两套内省 SQL）。

### I2 取值层（25–35 人日）

> **v1.2 状态更新（2026-10-18，使用者开了"允许本地自建 Doris/MySQL 造数据测"之后）**：本批次里各项的**可验证性不再同一档**，按方案 §0.1 三档重判——
> - **P0-0 源访问层：从"待环境"升为「本地可做且可验」（T-A）**。这是本条更新里最重要的一件事：v1.0 我把 A6 写成"物理不可行"，读起来像"这窗口什么都做不了"；实际是"缺驱动、但驱动可以在本地装上并跑通"。⇒ **A6 不再是阻塞项，而是本窗口可收口的最大一块工程**（驱动选型 `aiomysql`、每源只读机制矩阵、内省 SQL 形状、sqlglot 规整后的语句真源能否执行——含本文 §4 的 Q24 执行侧半段，全部本地可答）。
> - **P0-9 探针 / 方案 §5.8 C1–C9**：机制层 T-A 可验（单一入口、批量 `IN`、分区谓词必带、超时与信号量、降级链）；**成本结论 T-B 不外推**（本地造不出 4 亿行的真实争用与冷/热分布）。
> - **P0-7 副本退役的 A/B**：T-A 可做（同一 golden 集双跑比 Recall@K），但 golden 用的是本地样例库 ⇒ 结论强度写"机制层不下降"，不得写"检索质量不下降"。
> - **P1-5 负载隔离：永久 T-C**（workload group 与多 FE 排队见 `docs/operations/unconfirmed-items.md` E13；"大屏不受影响"只能 BI 团队答，方案 D2 已定问数不拥有那些表）。
> - **§5.7 路线一（派生取值字典小表）**：机制与 SQL 形状 T-A 本地可验；**能否落地 T-C**（E12 权限）。
> ⇒ 由此推论：本文 §6 资源投入那一格的"≈73–105 人日"**不是一次性投入**，而是按档切分——T-A 段本窗口能做且可验，T-C 段应显式出列、不进一期判据。

**P0-0 源访问层单列一项、提到 P0 档**（A6 的直接后果，5–8 人日）→ P0-9 按 §5.3 合并解收缩范围 → P0-7 副本退役（**带 A/B**，见下）→ P0-8 五道闸。

**I2 的两条前置门**：
- **P1-5 已实测生效**才允许探针上线（5.4）；
- **P0-7 退役判据**：同一 golden 集**双跑**（旧 `value_repository` 路 vs 新路），Recall@K 不下降且 empty-result 率不上升，才允许退役；退役分两步（先双读比对一个周期，再摘旧路）。方案 §6 目前**没有任何"替换前后质量不下降"的判据**，§5.3-O3 形状对但写的是 ES→引擎。这同时补上 §11.6 承认缺失的"迁移与回滚路径"。

### I3 观测与门禁（10–15 人日 + 业务侧 2–3 人日标注）

- **P0-4 对齐 OTel GenAI 语义约定，不自研 trace 表**（方案 §11.6-G2 自己已承认）。理由：AGENTS.md「架构决策原则」要求横切关注点三层齐备（单一实现 + 全局装配 + 强制门禁），并明写"接线散落 = 反模式"；仓内已有 `agent_core/tracing.py`、`agent_core/observability/`、`agent_core/events.py`、`agent_runtime/tracing.py`，OTel/Langfuse 已在 `deploy/k8s/20-agent-platform.yaml:113-138` 接线。新建 nl2sql trace 表 = 第四条观测路。
  ⚠️ **精度提示**：`grep gen_ai packages/agent-core/agent_core/tracing.py` **命中 0** ⇒ "对齐 GenAI 语义约定"是**新增属性工作**，不是白拿现成基座。`meta_revision` / `source_snapshot` 应作为 span attribute，不建独立表。
- **golden 判据 = 固定 revision 快照上的结果集比对 + 数值容差，不要比 SQL 文本**（文本不同而语义等价的问法会全红）。⚠️ 现有 `eval/wenda_data_agent_golden.jsonl` 用的恰恰是 `expected_sql_contains`（文本包含）——**这个坑现在就在仓里**。
- **golden 集不是"从哪来"的开放问题**：`eval/wenda_data_agent_golden.jsonl` **已存在 5 条**，已被 `docs/architecture/agent-harness-capability-map.md:287` 与 golden 总数口径 342（`docs/agno-agentos-comparison.md:154`）登记；但 `eval/run_eval.py:36` 硬编码只读 `golden.jsonl` ⇒ **这 5 条没有任何 runner**。方案 §11.6 说"没定义 20–50 条从哪来"却没引这条既有资产，正是它自己在 N5 强调的"须挂链不得当新发现"的反例。⇒ 改写为"扩既有 5 条 → 20–50 条真实会展口径 + 给 `run_eval.py` 加 golden 路径参数 + 回写 capability-map:287 计数"。且这 5 条是合成 `orders/products` schema，**不能当真实基线**。
- **P0-4 分两阶段**：`deploy/` 全目录 grep `nl2sql` 命中 **0**、k8s 只有一个 `agent-platform` 镜像、`.env.example:204` 写"空 = 不注册 nl2sql skill" ⇒ **本服务未部署**。所以 (a) §11.6 担心的"已上线如何灰度"不成立；(b) 但**没有线上流量**，golden 只能人工造，P0-8⑤ 的"未命中字面量日报"上线前无数据。方案把日报当既定能力。

### 合计

| 批次 | 人日 |
|---|---|
| I0 + I0.5 | 8–10 |
| I1 | 15–20 |
| I2 | 25–35（含 P0-0 的 5–8） |
| I3 | 10–15（+ 业务侧 2–3） |
| P1-1..P1-6 | 15–25 |
| **总计** | **≈73–105 人日** |

⇒ **最小可交付集**（闭合 H1–H4 且不被待答项卡住）：I0 + I0.5 + I1 ≈ **23–30 人日**。P0-5 / P0-7 / P0-8 / P0-9 属检索质量第二阶段，全部吊在 Q10a / Q11 / Q15 / Q20 上。

---

## 8. 安全侧必改两处

**F1 `filter_clause` 是整段 SQL 片段，标识符正则管不了。** `clients/pgvector_client_manager.py:29-30` 是 `sql += f" WHERE {filter_clause}"`——裸插值一个含运算符的谓词。方案 P0-10 写"凡把表名 / 列名 / `filter_clause` / `tsvector_col` 拼进 SQL 的位置一律加标识符校验，直接复用 `_IDENT` 正则（`^[a-z_][a-z0-9_]*$`）"——**对该参数是范畴错误**：要么拒掉所有合法过滤（功能废掉），要么不校验（洞留着）。而 §6 验收第 12 条只测表名/列名，**测不到它**。

**F2 `extra_cols` 同样是裸插值的多列片段**（`pgvector_client_manager.py:28`：`f"SELECT {extra_cols}, {embedding_col} <=> %s AS distance FROM {table}"`）。方案 P0-10 列了 `pgvector_client_manager.py:28-70` 这个范围，但没区分"单标识符"与"多 token 片段"两类。

**改法（两处同一解）**：`filter_clause` 收敛为结构化谓词 `(column, op, param)`，`extra_cols` 收敛为 `list[str]`，两者都由代码拼 SQL、列名过 `_IDENT`、值走绑定，**不接受字符串入参**。验收第 12 条补两个用例：非法 `filter_clause` 结构、非法 `extra_cols` 元素。

**F3 探针是新增攻击面**（见 §5.3 三条硬约束）：列名只能取自 `linkable` 枚举、值参数必须绑定、每请求探针预算上限。**第二条尤其重要**——LLM 抽取的提及文本参与构造发往源的查询，若列名可由 LLM 指定，就能绕过 P1-2 基数闸门读到手机号/证件号。

---

## 9. 待答项治理：owner + fail-safe 默认假设

22 个待答**零 owner、零截止、零默认假设**（方案 §11.6 自己承认）。其中 ≥5 项是跨团队依赖，响应周期是周级不是小时级：Q10a/b（Doris DDL 权限，问 BI/DBA）、Q15（workload group，问 BI）、Q19/Q22（内网 MySQL `ngram_token_size`，非动态变量、改配置要重启并重建索引，问 DBA）、Q1–Q3（2025 内网系统取证，代码在公司内网、本地不可读）。

⇒ **每个待答加三列：owner / 提问日期 / 无答复时的 fail-safe 默认。没有默认假设的待答项等于把方案挂起。**

| # | 建议默认假设（无答复时按此推进） |
|---|---|
| Q10a | 假设**能**在自有库建表（否则 5.3 的高基数分支无解，须退纯精确匹配并写进非目标） |
| Q10b | 假设**不能** ⇒ 路线二永久出局 |
| Q15 | 假设**拿不到** workload group ⇒ **探针不得上线**（5.4 硬门），改走派生小表或仅精确匹配 |
| Q16 | 假设 MySQL 侧无可用快照 ⇒ 缓存 TTL 兜底 15 min（5.3） |
| Q18 | 假设维度**未定** ⇒ 先接线 pgvector 配置（N1），接线前不改 YAML |
| Q20 | 假设无独立探针预算 ⇒ 采用 §5.3 的 ≤4 次 / 300 ms 默认值，实测后再调 |
| Q22 | 假设 `ngram_token_size` **改不动** ⇒ MySQL 侧中文模糊匹配退精确 + 前缀 |
| Q25 | **不给默认**——这是架构分叉，必须由使用者裁定（A5） |

**新增两个待答**：
- **Q26**：业务库（MySQL 8.0+）**有没有只读副本、能不能拿到只读账号**？P1-3③ 把它写成要求，但 §8 没有任何 Q 问它的存在性——与 Q10a 同级的权限依赖，漏登记。
- **Q27**：`nl2sql_*` 元数据表当前**由谁创建、在哪个库**？（Q23 问的是"由谁建"，这里补"在哪个实例"——I0-4 的 DDL 入库需要知道对齐哪个现网形状。）

---

## 10. 文档治理

845 行 / 131 KB、平均 155 字节/行、五轮修订叠压。§5.1（自标"备查手册"）、§5.2 末段、§5.3 默认路线表、§5.4 的 Q8 分叉、§5.5 甲方案、§5.7 路线一的默认地位——**全部已作废或已被改写但原文保留**，只靠状态横幅提示。实施者读到 §5.1 就可能去装 `pg_search`。方案 §11.1-R13 已经发生过一次"往表格单元格里加长内容 ⇒ 嵌套代码块吃掉列分隔符 ⇒ 整行从 4 列塌成 3 列"的事故；**继续原地追加，下一次事故只是时间问题**。

另：§11.5 整节（投递物陈旧度、简历 PDF、`java-senior-v1.md`、`big-data-v1.md`）与本方案的技术改造**无关**，是从另一个工作流混进来的，应移出。

**拆三份**：
1. **决策摘要**（≤1 页）：§0 裁定 + 结论 + 批次 + 验收 + owner；
2. **可执行 spec**：§4 的 P0/P1（每项带 owner、估算、依赖批次、判据）+ §6 + §7 + §8（带默认假设）；目标 ≤250 行；
3. **论证附录**：§5.1–§5.7 的作废路线与选型论证 + §11 核验台账 + §12 冻结快照。

⚠️ **§12 尤其要独立成文件**：它是防 `courses/` 目录删除后证据失效的**唯一副本**（该目录未被 git 跟踪、`.gitignore:100` 排除、用户表示将删除）。混在方案里会随方案归档而被忽略。

**索引登记**：`docs/README.md:169` 现写"`docs/reviews/` — 2 份评审件（09-23）"，实际目录已有 3 份（含 `review-plan-deep-research-app-2026-10-16.md`），加本文共 4 份。该处计数**已陈旧**，本评审未擅自改动（`scripts/check_doc_sync.py` 只校路径存在性与 Makefile session 数，不校此计数，故不会 CI 报红）⇒ 列为待办，由使用者决定是否同批更新。

---

## 11. 核验方法、两轮分歧与证据等级

### 11.1 方法

不采信方案自述。做法：读被引文件原文 → 跑不受 `.gitignore` 影响的 grep 复核否定式断言 → 对可本机执行的断言**实跑**（sqlglot 方言矩阵）。

⚠️ 本仓 `.gitignore:100` = `courses/`，而方案证据最密集处正是 `courses/zhanggui-wenda/data-agent` ⇒ **任何尊重 gitignore 的搜索器在本仓做否定式断言都偏向"不存在"**。方案 §11 已登记这条，本轮复核确认它仍然成立。

⚠️ 复测陷阱（本轮实踩）：不区分大小写 grep `sse` 会命中 57 处假阳性（`assert` / `assembly` 子串）。判 SSE 有无必须用 `StreamingResponse` / `text/event-stream` / `EventSourceResponse` 三个真签名。

### 11.2 两轮评审的分歧与处置

| # | 分歧 | 处置 |
|---|---|---|
| D1 | 探针路线：A 轮判"成本模型不成立"，B 轮判"最强的设计点" | **两轮都对**。B 轮的修法（召回阶段不探针、只做生成后校验）把二维扇出砍成一维，A 轮采纳；A 轮补的洞（生成时无规范值 ⇒ 校正循环上升，而 `sql_max_correct_retries` 是死配置）B 轮未覆盖 ⇒ 收敛为 §5.3 的分层合并解 |
| D2 | §5.7 路线一的地位 | 采 A 轮：**恢复为高基数自由文本列的默认**，不违反 D6（5.2） |
| D3 | 架构设计评级 | 采 A 轮的**中**（B 轮给"中上"，未扣 A1/A2/A3 的分——图拓扑与数据流契约脱节不只是执行层缺失） |
| D4 | Q25 优先级 | **两轮一致**：排第一，方案自定的 Q10a→Q23→Q24 顺序错 |
| D5 | A1 措辞 | 采 A 轮订正：不是"不产出答案"，是"有数据、无自然语言答案"（影响 I0-1 工时） |
| D6 | B 轮"ParquetDB 许可" | **笔误**，方案里是 **ParadeDB**（`pg_search`，AGPL-3.0）。不影响结论 |

### 11.3 B 轮断言的逐条复核结果

**9 条硬事实成立**：A1（`answer` 恒空）、A2（无 MySQL 驱动）、A3（召回结果被丢弃）、C2（零 SSE，措辞需限定见 §3）、C3（四处死配置）、C4（`recall_value` 短路）、P0-1 判据过软（`stats["values"]` 恒 0）、`filter_clause` 正则管不了、LOC 1690 / 测试 289（实测精确一致）。

**1 条方向写反，本文 v1.0 误判为成立 → v1.1 撤回**：**瓶颈 2**。

| 分句 | v1.0 判定 | v1.1 判定 | 依据 |
|---|---|---|---|
| 同一个 `meta_pool` 同时喂 `PgvectorClientManager` 与 `MetaRepository`（`dw_pool` 才独立） | 成立 | **仍成立** | `api/dependencies.py:52` 与 `:64`，对方本批未改这两行 |
| 失效形状＝"默认 `max_size` 下并发即排队" | 成立 | **✗ 反了** | 改造前默认 `min_size=4 / max_size=None` ⇒ **无限新建后端**，天花板推给 PG `max_connections`，超限以 `FATAL: too many clients` 冒出。无限扩张与排队是两种排查路径 |
| 该项属"评审新发现" | 成立 | **✗ 一半是重复发现** | 另一会话正在修同一处，且已有自述审计：`clients/pg_pool.py:4`「固化 2026-10-17 连接池审计的三个结论」（强制显式 min/max、`max_waiting = 2*max_size` 快速失败、连接级下发 `-c default_transaction_read_only=on`）⇒ 按本文 §11.3 替方案立的"须挂链不得当新发现"纪律，本条一半须挂链、不得自述 |

⇒ 剩下的**不是配额问题**，而是**异构负载共享同一份配额**：元知识库写入（构建入口，要写）与向量召回（每查询都打、且方案 N4 已证无索引 ⇒ 可能全表扫）抢同一份 min/max。修复方向随之从"加配额"变为"**拆池或给召回单独配额**"，且 P0-0 源访问层落地时这个决策会被再次触发——现在不必动，但别再按"排队"表述它。

**5 条判断题均同意**：C1、瓶颈 1 方向、瓶颈 3、瓶颈 4、Q25 排序。

**2 条需修**：A1 措辞偏重（D5）、ParquetDB 笔误（D6）。

**A 轮补充的、B 轮未覆盖的**：A3（`add_extra_context` 空转 + P1-4 课程侧误当平台侧）、A4 的机制细化（三项"有读取点"的配置也是死的，根因是 state 从不注入）、F2（`extra_cols` 同病）、§4 的 sqlglot 方言实跑、§5.2 的路线一应恢复默认、I0.5 批次（YAML schema 化无工作项）、I3 的 golden 既有 5 条与 runner 缺失、5.4 的 P1-5 硬门、F3 的探针越权读、§9 的 fail-safe 默认假设表与 Q26/Q27。

### 11.4 证据等级标注

| 等级 | 条目 |
|---|---|
| **实跑确认** | §4 的方言矩阵（sqlglot 30.20.0 + `agent_core.sql.guard.validate_sql`，8 组语句 × 3 方言） |
| **代码逐行确认** | A1–A6、C1–C5、F1–F3、五处死配置、LOC、golden 5 条与无 runner、未部署。连接池一项仅「同一 `meta_pool` 喂两消费者」这一句成立，失效形状见下一行 |
| **v1.1 撤回（本文自己的错）** | 瓶颈 2 的失效形状「并发即排队」——改造前实为 `max_size=None` 无限新建；以及「唯一路由」措辞已被并行批次的新运维路由取代。两条均在 §11.3 与 §3 就地订正，其余判定不动 |
| **静态判据 + 死码事实，待一次实跑** | `get_table_schema` 的 `column_comment` 在 PG 不存在（A6）——该方法零调用方零测试，从未执行 |
| **判断题（非事实）** | 五维评级、批次划分、工时估算、§5.3 分层、§9 默认假设 |

---

## 附录 A：本轮实测命令要点

```bash
# 1. sqlglot 方言可用性（结论：原生含 doris / starrocks）
uv run python -c "import sqlglot; print(sqlglot.__version__); \
  print(sorted(sqlglot.dialects.dialect.Dialect.classes.keys()))"

# 2. 守卫方言矩阵（§4 那张表的来源）
#    对 8 组语句 × ("postgres","doris","mysql") 调 validate_sql(sql, dialect, 1000)
#    记录 (ok, reason, 输出文本是否被改写)

# 3. SSE 有无（必须用真签名，不能用 sse 子串）
grep -rnE "StreamingResponse|text/event-stream|EventSourceResponse" \
  --include=*.py applications/nl2sql-service/          # → 0

# 4. 五处死配置的消费方
for k in rrf_k retrieval_top_k sql_max_correct_retries sql_read_only_guard sql_max_rows; do
  grep -rn "$k" --include=*.py --include=*.yaml applications/nl2sql-service/ tests/nl2sql_service/
done

# 5. 驱动与部署面
grep -n "mysql\|doris\|aiomysql\|pymysql" applications/nl2sql-service/pyproject.toml   # → 0
grep -rn "nl2sql" deploy/                                                              # → 0

# 6. LOC
find applications/nl2sql-service -name "*.py" -not -path "*__pycache__*" | xargs wc -l  # → 1690
```
