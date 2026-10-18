# ADR-0011: 平台内两条 Text2SQL 路（nl2sql-service / agent_server/sql）——收敛决策记录

- 状态：**未决（本文不替用户拍板；只把现状、选项与代价摆清，供 Q25 回答）**
- 日期：2026-10-18
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
