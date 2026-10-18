# nl2sql golden 基线与归属（§11.6-② 缺口收口）

- 日期：2026-10-18
- 来源：`docs/plans/plan-nl2sql-meta-lifecycle-2026-10-17.md` §11.6 两条章节级缺失之二
  （"没有基线值与 owner：§6 要求 golden 一键跑出门禁读数，却没定义 20–50 条从哪来、
  谁标、口径冲突谁裁，也没留基线数字；待答里零 owner"）
- 关联：H4（质量反馈回路，trace 落库）、`nl2sql_service/scripts/run_golden.py`（一键跑）、
  `ADR-0011`（两条 Text2SQL 路的 owner 归属）

## 1. 这份文档补什么（不补什么）

**补**：golden 的**结构与来源**、**标注流程与 owner 角色**、**口径冲突仲裁规则**、
**一键跑的命令与读数口径**、**基线数字的登记处**。

**不补**（诚实边界）：**真实基线数字**与**真实 golden 内容**——这两样需要一个活的
LLM + 可达 dw 库 + 人工标注轮次，本机/本次拿不到。基线数字留成"首跑登记处"（§5），
由首次真跑回填；本文交付的是**可复现的机制 + 归属结构**，不是伪造成数。

## 2. golden 集：结构与来源

**放哪**：`applications/nl2sql-service/golden/nl2sql_golden.jsonl`（随代码进 Git——
口径评审靠 Git review，与 §11.6 里"选 A 就必须承认口径评审靠 Git 流程"一致）。

**每条结构**（缺省字段不判，逐步补全而非一次凑满）：

```jsonl
{"id":"g01","question":"上个月每个城市的订单数","expect_tables":["orders"],"expect_values":[],"expect_nonempty":true,"notes":"口径：按收货城市；T+1 数据"}
```

| 字段 | 含义 | 判据 |
|---|---|---|
| `id` | 稳定编号（删了不复用，避免历史读数错位） | — |
| `question` | 用户问法原话 | — |
| `expect_tables` | 期望 SQL 出现的表 | SQL 文本含其一即过 |
| `expect_values` | 期望在字典/源侧确认存在的取值 | 进 `matched_values` 即过 |
| `expect_nonempty` | 期望非空结果 | 不落 `genuinely_empty` |
| `notes` | 口径说明（数据新鲜度/过滤条件/歧义） | 供标注与复盘 |

**来源（20–50 条从哪来）**：
1. **线上未命中字面量日报 top N**（H4 trace 的 `unmatched_terms`）——答错率最高的真实问法，
   优先级最高（§5.4-⑤"未命中清单直接成为别名词典种子"）；
2. **线上高频 query 抽样**（trace 的 `query` 字段去重 top N）；
3. **口径边界手搓**：每类继承/时间/指代（多轮 M3）、每类聚合（§5.11-V3）、每个已登记
   别名（§5.14-R1）各挑 1–2 条——覆盖"机制在用"而非只覆盖"常见问法"。

**专放字面变体题**（§5.4-⑤）：北京/北京市/京、廊坊/廊坊市 这类归一化题单独成组，
它们是"字面不匹配但语义同"的回归网。

## 3. 标注流程与 owner 角色

| 角色 | 职责 | 当前归属 |
|---|---|---|
| **golden 标注 owner** | 定 `expect_*` 正确答案、写 `notes` 口径、review golden PR | **待填**（问数产品/数据负责人） |
| **口径冲突仲裁** | 两个标注者对同一题 `expect_*` 不一致时谁裁 | **待填**（建议：问数产品负责人，一次裁断写进 notes，不再反复） |
| **门禁 owner** | 发版前跑 `run_golden --fail-on-regression`、读数偏离基线时放行/打回 | **待填**（建议：nl2sql 服务 owner） |
| **nl2sql 服务 owner** | ADR-0011 已决 **A**（2026-10-18）：agent_server/sql 退役、统一到 nl2sql-service。本角色负责 Stage ③（`subagents/sql_agent.py` 等消费方改端点 + 退役时序）与退役后唯一问数路的边界维护 | **待填** |

> owner 待填是**有意的诚实**——§11.6 指出的病是"零 owner"，先立**角色位与职责**，
> 具体人名由项目负责人指派后回填。立了位比空着更接近可运营。

## 4. 一键跑（命令与读数口径）

```bash
python -m nl2sql_service.scripts.run_golden \
    --golden applications/nl2sql-service/golden/nl2sql_golden.jsonl \
    --fail-on-regression
```

读数（与 `nl2sql_query_trace` 同源，H4）：`passed/total`、`errored`、`empty`、
`literal_unmatched`、逐题 `miss`。`--fail-on-regression` 有失败返回 2，供 CI/发版门禁。

**复现纪律**：golden 跑的是同一条 HTTP 路径（TestClient 触发 lifespan，与线上请求
零偏差）；读数随 LLM/数据版本漂移是正常的——**基线是"某个版本下的快照"**，偏离时
先判"是回归还是数据/模型变了"，不是一律打回。

## 5. 基线数字登记处（首跑回填）

> 首次真跑后把下表回填，作为后续偏离的比对基准。**现在留空是刻意的**——没有真跑
> 就没有基线，编一个数字比没有更坏（§11.6 正是批"没留基线数字"，答案是有据可查的
> 真数字，不是占位数）。

| 读数 | 基线值 | 记录于 | LLM/数据版本 |
|---|---|---|---|
| passed/total | **2/3** | 2026-10-18，`golden_v3.json`（commit 见 CHANGELOG 当日段） | Qwen/Qwen3-8B（硅基免费 chat）+ BAAI/bge-m3（免费 embedding）；DW=orders(6 行)/users(3 行)，2026-10-18 |
| literal_unmatched | **0** | 同上 | 同上 |
| empty | 0 | 同上 | 同上 |
| llm_calls_avg | 3 | 同上（trace 表逐行 llm_calls） | 同上 |

**首跑明细（不粉饰）**：

| 用例 | 结果 | 说明 |
|------|------|------|
| g01 上个月每个城市的订单数 | **FAIL**（errored，miss tables） | SQL 幻觉列 `orders.create_time`（真列 `created_at`）→ correct 循环修复途中**连续 LLM 超时**（免费档当日劣化，120s×3）→ 重试耗尽 errored。**失败归因是环境（免费 LLM 超时），不是代码缺陷**——同链路 g03 用同一批列生成出了正确 SQL |
| g02 已退款的订单有多少 | PASS | 首跑曾 FAIL（membership 缓存缺陷把 `已退款` 误判不存在，见下）；修复后 matched=['已退款'] 首轮即过 |
| g03 那上个月呢（多轮） | PASS | 承接 g02 同 session，M3 时间/实体继承生效（SQL 带 `created_at >= '2026-09-01'`） |

**首跑逼出并修掉的两个真缺陷**（均在真库/在线路径复现，假池单测抓不到）：

1. `dw_repository.execute_probe` 的 `SET LOCAL statement_timeout = %s` **带绑定参数**——PG 工具命令不接受参数（`syntax error at or near "$1"`）⇒ 配了 linkable 的部署里取值探针**从来没成功跑过**。修为 int 强转后内联（`test_dw_repository_probe.py` 3 条钉死）。
2. `value_resolver` membership 缓存**键不含 literals、值只是本轮问到且存在的子集**——g01 问过 `已支付` 后 g02 问 `已退款` 命中同一键被直接判 missing（该值实际存在）⇒ 误拦进 correct 循环。修为缓存只当"已确认存在"正集合、新字面量必须真探（`test_value_resolver.py` 新增回归 1 条）。

**基线口径提醒**：本基线是"Qwen3-8B + 免费档"下的快照。免费 LLM 的延迟/超时特性会显著影响 correct 循环的成败，**换 LLM（如恢复 opencode 通道）后必须重跑并更新本表**，不得拿本表评判另一个模型的回归。

## 6. 与其他缺口的关系

- **迁移回滚路径（§11.6-①）**：已闭环——`migrations/001_meta_schema.down.sql`（v1→空）
  与 `002_meta_lifecycle.down.sql`（v2→v1，含版本标记回落）都在，"现状→终态"的回退
  有据。本文不重复。
- **G1（两条 Text2SQL 路）**：见 `ADR-0011`；其 owner 归属（§3 表末行）与本文 §3 联动。
- **G2（trace 不自造方言）**：`nl2sql_query_trace` 字段对齐 OTel GenAI 语义约定
  （query/rewritten_query/sql/error/error_class/matched_values/unmatched_terms/llm_calls/
  latency_ms/result_rows/path 等），不在应用侧另造一套 trace 结构；grep 全服务对
  `agent_core.tracing` 的既有装配在 `api/server.py::create_app`（`init_tracing`）——
  DB 落库的 query_trace 是**业务读数**（golden/日报用），与 OTel span 各司其职。
