# 方案：隔离门卫 6/6 覆盖（roadmap 阶段 2 #11，2026-10-16）

> 状态：**本文件是 #11 的实施方案**（AGENTS.md 红线「架构级改动先出方案文档」+ roadmap §七 第 3 条）。
> 上游判据（`plan-production-delivery-roadmap-2026-10-09.md` 阶段 2 #11）：
> 改法「剩余 4 个服务接入（先"只观察不拦截"档）+ 漏装即报错的自动检查」；
> 怎么算改好「6/6 覆盖；门禁生效；灰度开关有记录」。
> 本文只覆盖**我方可独立执行且不改变任何对外响应**的那一半；其余显式转待拍板（§5）。

## 1. 目标

1. 6 个服务**每一个都有身份装配点**（当前 2/6 用共享实现），使「启用强制隔离后未接入服务仍可被自报身份绕过」这一风险变成**可机检的事实**而非约定。
2. 装配点默认**只观察不拦截**（observe 档），因此本批上线**响应体/状态码零变化**——隔离能力的引入与引入的副作用被解耦。
3. 加**存在性门禁**（漏装即在 CI 失败），与 #12 的 L-5 同族：禁止性规则（不许散落）与存在性规则（不许漏装）互补，缺一条即退化为口头约定。

## 2. 现状（本轮实读，逐条给锚点，不沿用文档口径）

| 服务 | 身份门卫现状 | 租户来源 | 证据 |
|---|---|---|---|
| agent_server | **共享实现** `IdentityMiddleware` | 8 个 router 取服务端断言（`server_tenant_id`），但 `/query` 仍自报 `req.tenant_id or "default"` | `main.py:12/13/249/640`；`sql_router.py:32`、`import_router.py:48`、`session_router.py:71`、`human_task.py:35`、`capabilities.py:91/108`、`subagents/rag.py:20`、`sql_agent.py:17`；`query_router.py:52/94/108/162/237/264/273/317/363` |
| agent_federation | **共享实现**（独立头 `X-Tenant-JWT`，桥接进联邦自有 ContextVar 防双脑） | 服务端断言 `get_asserted_tenant_context` | `api/server.py:199`、`api/identity_bridge.py:11/25-33/41`、`api/context.py:95/111`、`tools/knowledge_tools.py:141-145`（向下游签发 `X-Internal-Tenant`） |
| knowledge-service | **另一套实现**（自带 `TenantHeaderMiddleware`，开关 `TENANT_HEADER_ENFORCE`，不依赖 agent-runtime） | 签名 > 自报 > default（优先级在自身 utils 内实现） | `knowledge_service/main.py:84/89`、`utils/tenant_identity.py:71/81`、`utils/tenant_utils.py:35-53` |
| exhibition-agent | **第三套实现**（`X-Execution-Context`，DEV 档 base64 **不验签**；STRICT 档才验签） | `ctx.tenant_id`，body 自报仅做交叉校验→403 | `exhibition_agent/server.py:135-146`、`middleware/execution_context_middleware.py:63-75/91/144`；`skill_loader/app.py:70-185` **无租户校验** |
| kefu-service | **无**（全仓不 import agent-runtime） | **纯自报**：`tenant_id = req.tenant_id or "default"` | `kefu_agent/__main__.py:63`、`:111` |
| nl2sql-service | **无** | **无租户概念**：`.py` 源码内 `tenant` 零命中，契约里有 `tenant_id` 字段但从不读 | `nl2sql_service/api/server.py`、`routers/query_router.py:15-33`、`schemas/query_schema.py:9` |

⇒ 字面「2/6」只算共享实现；按「有一个门卫」算是 4/6；按「单一实现」算是 2/6。**本方案按共享实现口径推进，并把两套 fork 显式登记**（不靠放宽定义把 4/6 说成 6/6）。

同时实测：`scripts/lint_architecture.py` 里**没有任何规则**管身份/租户中间件的按服务覆盖（P12 管凭据外流、`check_retired_identity_helpers` 管退役函数名，均非覆盖度）。⇒ 漏装今天在 CI 里完全不可见，与 #12 修前的 L-3 情形同构。

另记一处**文档与代码漂移**：`identity_middleware.py:10` 写「子服务（knowledge-service 等）：验签 X-Internal-Tenant HMAC 头」，而 knowledge-service 实际跑的是自己那套、且零依赖 agent-runtime。本批顺带订正该行（改成实指的服务名），避免下一个读的人以为已经接了。

## 3. 设计（三层齐备）

| 层 | 落点 | 为什么这样落 |
|---|---|---|
| 单一实现 | 新增 `agent_runtime.identity_assembly.mount_identity_gate(app, service_name)`，内部只做三件事：`require_identity_startup_guard(service_name)` → `app.add_middleware(IdentityMiddleware, …)` → 记录装配档位 | 三件事的顺序与组合是易错点（守卫漏调 = 生产裸奔无人知）。放进 kernel 而不是在每个 app 抄一遍。**不能放进 `build_api_app` 工厂**：工厂在 `agent-core`，`IdentityMiddleware` 在 `agent-runtime`，依赖方向 `core ↛ runtime`（红线 1），故只能「共享实现 + 各服务装配点 + 存在性门禁」 |
| 全局装配 | 在 kefu-service、nl2sql-service 的既有装配点各调一次（与 #12 的 `init_tracing` 同处，位置即顺序） | 这两个是**零门卫**服务，接入即把 2/6 抬到 4/6；另两个（knowledge/exhibition）已有 fork 门卫，收敛是另一件事（§5） |
| 强制门禁 | `lint_architecture.py` 新增 **P13 身份装配覆盖**：枚举 `applications/*` 六个服务，每个必须能定位到身份装配点；`_IDENTITY_ASSEMBLY` 逐服务登记**它用的是哪一套实现**（shared / fork:<文件>），fork 项在规则里显式可见 | 存在性检查 + 自检（枚举结果与已知六服务不符即报「判据失义」，沿用 L-5 的 fail-closed 形状，防止"放宽阈值蒙绿"）。登记实现归属，是为了让「6/6」这句话**可审计**：门禁绿不代表都是同一实现，差在哪一眼可见 |

档位语义（不改中间件，沿用其现状）：observe（默认）= 无凭据交下游既有逻辑；enforce = `TENANT_JWT_ENFORCE=true` 时缺凭据 401。本批**只挂 observe**，故 kefu/nl2sql 的响应与状态码不变。

## 4. 迁移策略（可前滚可回退）

1. **本批只加不改**：新增装配点 + 新模块 + 新门禁；不删任何既有中间件，不改任何对外契约。
2. 翻 enforce 是**运维动作**（置 env），不是代码动作 ⇒ 回退 = 撤 env；代码回退 = revert 一个 commit。
3. 灰度开关有记录（判据第 3 条）：`mount_identity_gate` 在启动时打印一行「service / mode(jwt|single|insecure) / enforce(bool) / 档位来源 env 名」，现网可据此核对当时生效的档，不靠猜。
4. 两套 fork 门卫**保持现状运行**（它们在 126 上是活着的），收敛方案另出（§5 第 1 项）。

## 5. 本批明确不做（各给理由，不当作已完成）

1. **knowledge-service / exhibition-agent 收敛到共享实现** —— 二者各自有在跑的对外行为（KS 的 `TENANT_HEADER_ENFORCE` 与 503 就绪探针、exhibition 的 `X-Execution-Context` 且 DEV 档刻意不验签），收敛会改**响应形状与部署开关名**，属契约变更：按 AGENTS.md「边界」条须先审计消费方并另行决策。
2. **把路由里的自报租户换成服务端断言**（agent_server `/query` 9 处、kefu 2 处）—— 这是 #11 的真正收口动作，但它改变**调用方可观察的行为**（自报值不再被采信）。且 nl2sql 侧有个前置问题：**它的"租户隔离"到底隔离什么**（其数据访问今天完全没有 tenant 维度，契约里有字段但从不读）⇒ 没有定义就无法判「已隔离」，转待拍板。
3. **exhibition `skill_loader/app.py` 的无校验端点** —— 属该服务内部端点收敛，与 §5.1 同批决策更稳。

## 6. 验收标准

1. `python scripts/lint_architecture.py` 的 P13 输出为「6/6 服务均有身份装配点」；把任一服务的装配点注释掉 ⇒ P13 exit=1 且点名该服务（**反证，非空转**）。
2. kefu / nl2sql 新增用例各≥2 条：① 带合法签名头 ⇒ 上下文里是**服务端断言**的租户；② 无凭据 ⇒ 响应与接入前逐字一致（observe 档不拦），且启动日志有档位记录行。
3. 全量门禁不劣化：`ruff check .`、`lint_architecture.py`、`check_doc_sync.py`、根套件 + kefu + nl2sql session。
4. roadmap #11 判据的记账口径：**「6/6 覆盖」只在 P13 绿且 `_IDENTITY_ASSEMBLY` 归属表可审计时成立**；「enforce 生效」需 env 与现网取证，属待环境，不因本批提前宣布。

## 7. 工时与截止

roadmap 估 6 人/日。本批交付 §3 的三层 + §6 的 1/2/3 条，**截止 2026-10-17**；§5 三项不在本批承诺内（其中 1、2 需你先拍板方向）。
