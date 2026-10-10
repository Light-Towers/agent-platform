# 方案（待拍板，未动代码）：`/query` 的租户边界取客户端 body，而入库侧取服务端断言

日期：2026-10-10　类型：横切 + 契约（影响 1.2 基线 2 的表述能不能说出口）
关联：`docs/adr/0006-*`（租户安全边界）、`docs/adr/0007-server-asserted-tenant-identity.md`、
`docs/operations/minimal-release-runbook.md` §5 基线表 / §3 反证读数

## 1. 硬读数（代码，不是推断）

| # | 事实 | 位置 |
|---|---|---|
| 1 | 全仓**只有 `query_router.py` 读 `req.tenant_id`**（客户端 body 字段），共 11 处；其余入口（`/import`、`/sql/train`、`/session/revert`、`/capabilities`、`subagents/rag`、`subagents/sql_agent`）一律用 `server_tenant_id()`（服务端断言） | `grep -rln "req.tenant_id" applications/agent_server` → 只有 `api/query_router.py` |
| 2 | `/query` 里客户端值决定了：**工作区解析**（`:52`）、**调度器租户维度**（`:94`）、**预算门控维度**（`:108`/`:359`）、**语义缓存读/写桶**（`:162`/`:313`）、**graph 兜底 state**（`:237`）、**PlannerContext**（`:264`/`:273`） | `api/query_router.py` |
| 3 | `PlannerContext.tenant_id` 一路传进能力调用（`deterministic.py:87/112/129/142/173/205` 等），最终成为检索 SQL 的租户谓词 | `planners/deterministic.py` |
| 4 | `subagents.rag_query()` 明确写着 **"不收客户端表单值（ADR-0006 T9）：显式传入优先，否则回退部署级 DEFAULT_TENANT_ID"** —— 而调用方 `:205` 正是**显式传入 `plan.tenant_id`（= 客户端值）** ⇒ 这道守卫被调用方按参数语义合法绕过 | `subagents/rag.py:10-19` vs `planners/deterministic.py:205` |
| 5 | 服务端断言值的来源：`server_tenant_id()` = ContextVar（由 JWT 验签或 `SINGLE_TENANT` 绑定）→ 否则 `DEFAULT_TENANT_ID`（默认 `default`） | `workspace_registry.py:81-90`、`identity.py:296-305` |
| 6 | 控制台页面**不发** `tenant_id`（grep 命中 0）⇒ 本版演示链路两边走的是同一个 `default`，**今天是自洽的** | `static/console.html` |

## 2. 两种会真的爆出来的读法

1. **越权读/串桶（多租户时）**：任何持有 API_KEY 的客户端在 body 里写 `tenant_id: "<别人的租户>"`，即可
   （a）按别人的工作区过滤检索、（b）读到别人写进 `semantic_cache` 的答案原文、（c）把自己的答案写进别人的缓存桶；
   同时 per-tenant 的调度并发与预算（`scheduler_max_concurrent_per_tenant`、`budget_limit_*`）都可被自选租户绕过。
2. **现场最容易踩的一版（不改代码也会踩）**：把 `SINGLE_TENANT` 按"部署单元注入真实租户"的口径改成非 `default`
   （例如 `acme`）后，`/import` 写入 `acme`，而 `/query`（页面不发 tenant_id）读 `default` ⇒
   **资料确实入库了，问答却永远检索不到**，且没有任何报错。
   本轮清单把 `SINGLE_TENANT` 钉成 `"default"` 恰好掩盖了这个分叉 —— 这是巧合，不是设计。

所以：1.2 基线 2 那句"租户由服务端断言，不信客户端"**目前只对会话归属成立**（`resolve_thread_id` 塌缩为
`tenant-<断言租户>`，已实测），对**数据面/治理面不成立**。对外表述必须收窄，或把代码补齐到整条链路。

## 3. 选项

| 选项 | 做法 | 影响 | 判断 |
|---|---|---|---|
| **A（建议）** | `/query` 的 11 处 `req.tenant_id` 全部换成 `server_tenant_id(settings.default_tenant_id)`；`QueryRequest.tenant_id` 保留在**契约**里（其它服务在消费），但**服务端不再据其定边界**，若客户端值与断言值不一致则记一条 WARNING（便于发现误配） | 行为变更：显式传 tenant_id 的现有调用方（联邦网关？须先审消费者）会从"自选桶"变成"落到部署断言的桶" | 与 ADR-0006/0007 同向；把"守卫"从"记得不传"变成"传了也不用" |
| B | 只修 §2.2 那条（把 `DEFAULT_TENANT_ID` 与 `SINGLE_TENANT` 的取值口径在清单/手册里钉死为同一个值），数据面仍信客户端 | 零代码风险 | 只是把坑标注出来，越权面仍在；**不能**再宣称基线 2 成立 |
| C | 网关模式：承认"上游是可信断言方"，仅当请求来自网关（带 mTLS/内部签名）才 honor `req.tenant_id`，直连客户端一律忽略 | 需要一条可信上游标识机制（本版没有） | 属独立方案，不与本版绑定 |

⚠ 消费者审计（已查，别当成未知）：仓内**向 agent_server `/query` 发请求的只有控制台页面**（不发 `tenant_id`，
grep 命中 0）与测试。联邦网关那条 `endpoint="/query"` 是 **knowledge-service** 的（`agent_federation/agent/config.py:56-62`），
它给下游子服务传 `tenant_id` 的位置是 `async_subagents.py:115-125` —— 与 agent_server 的 `/query` 不是同一条边。
⇒ 选项 A 的兼容面比"怕破坏上游"要小得多；真正要确认的只有**仓外**调用方（若有）。

## 4. 验收（A 的话，须当场可证）

1. 双租户实跑：`/import` 以断言租户 `acme` 入库；`POST /query` 带 `tenant_id: "other"` ⇒ 检索**不得**命中 `acme` 的资料，且日志出现一条"客户端租户声明与断言不一致，按断言执行"的 WARNING。
2. 缓存：`other` 租户的请求**不得**命中 `acme` 写入的 `semantic_cache` 行（用 `SELECT tenant_id, count(*) FROM semantic_cache GROUP BY 1` 作证）。
3. 治理：per-tenant 并发/预算只按断言租户计数。
4. 回归：控制台页面（不发 tenant_id）行为不变；`eval/run_eval.py` 15/15 不变。

## 5. 待拍板

① 选 A/B/C；② 是否存在**仓外**调用方给 `/query` 传 `tenant_id`（仓内已审：只有控制台页面与测试，页面不发该字段）；③ 本版对外的口径措辞：
是"会话归属已断言、数据面租户边界为单租户自洽"还是"租户由服务端断言"。
