# 方案：web 端「注册 + 登录」最小闭环（完整产品的第一块入口面）

- 状态：**已确认，PR-2a 开工中**（2026-11-05 拍板轮，四项见 §8；本文其余部分即执行依据）
- 日期：2026-11-05
- 分级：**T2**（2–4 天，跨 `applications/agent_server` + `packages/agent-runtime` + `web/` + 部署清单四面）
- 决策边界：登录凭据形态、会话是否按人分桶、静态 key 去留 = **D1/D2（本文给建议，人批）**；私钥落地与 enforce 档位 = **D2**
- 用户原话（需求来源）：「如果没有用户，那登录界面创建用户，如果有账号，直接登录就行」

## 1. 现状事实（逐条可复核，不是推测）

| # | 事实 | 证据 |
|---|---|---|
| F1 | `users` / `organizations` / `conversations` 三张表**已在 schema**，但产品代码**零读写** | `packages/agent-runtime/agent_runtime/migrations/013_org_user_conversations.up.sql:20-49`；`git grep -E "INSERT INTO users\|FROM users"` 在所有 `.py` 中仅命中 SQL 守卫用例与 nl2sql fixture |
| F2 | `users` 表**没有任何凭据列**（无 `password_hash`），`display_name` 是展示位 | 同上 `:27-33` |
| F3 | RS256 签发/验签的**验签侧已完整在位**，且中间件已把 `user_id` 绑进上下文 | `packages/agent-runtime/agent_runtime/identity.py:162`（`mint_token`）、`:192`（`verify_token`）、`:289`（`apply_tenant_context(tenant_id, user_id)`）；`packages/agent-runtime/agent_runtime/identity_middleware.py:101-205` |
| F4 | **`mint_token` 零生产调用者** ⇒ 没有签发方 = 没有登录；A5（user 断言）在册状态 = 未做 | `git grep mint_token` 命中面 = 定义 + tests + 文档文字；`docs/plans/plan-platform-tenant-workspace-identity-2026-10-18.md:53`「`server_user_id` 管道在、无生产绑定」 |
| F5 | agent_server 的身份门卫是**直挂** `IdentityMiddleware`（不走 `mount_identity_gate`），observe 档零行为变更 | `applications/agent_server/main.py:776`；装配点本身见 `packages/agent-runtime/agent_runtime/identity_assembly.py`（当前只有 kefu-service / nl2sql-service 走它） |
| F6 | 入口凭据 = 单把静态 `X-API-Key`，未配即不校验的旁路在位 | `applications/agent_server/api/auth.py`（`verify_api_key`）；`docs/adr/0008-auth-mode-selection.md` §2 U1/U2 |
| F7 | 会话 id = `tenant-<服务端断言主体>`，**主体是租户不是人** ⇒ 同 org 两个账号共用一条会话线 | `packages/agent-core/agent_core/guardrails/auth.py:56` `resolve_thread_identity`；调用点 `applications/agent_server/api/auth.py:resolve_thread_id` |
| F8 | 私钥/公钥/env 名字**已有约定**，不需要新增开关名 | `identity.py:139` `TENANT_JWT_PUBLIC_KEYS_FILE`、`:148` `TENANT_JWT_PRIVATE_KEY_FILE`、`:182-183` `TENANT_JWT_ISSUER` / `TENANT_JWT_AUDIENCE`，`mint_token` 默认 `ttl=900` |
| F9 | 前端目前只有「粘 key」这一个面，无登录态、无 token 存储 | `web/src/components/ApiKeyBox.vue`、`web/src/api/sse.ts:262`（`h.set('X-API-Key', apiKey)`） |
| F10 | 迁移序号下一个可用值 = **016**（最新是 015） | `packages/agent-runtime/agent_runtime/migrations/` 实测：010/011/012/013/014a/015 |

## 2. 目标 / 非目标

**目标（本轮交付的"完整产品"边界）**：浏览器打开入口 → 未登录只见登录页（同页可注册）→ 注册或登录 → 进入对话界面 → 提问得到流式回答与证据 → 刷新仍在登录态 → 退出。口令只在服务端做散列比对，前端不存明文。

**非目标（本轮明确不做，不得读成已具备）**：
- **会话按人隔离的正式归属**（conversations 表写入点 + 014b `user_id NOT NULL` + 历史列表按人）= 下一刀，见 §7 PR-3；
- 忘记密码 / 邮件验证 / 验证码 / 第三方 IdP（OIDC）/ RBAC 细粒度角色（D13 已砍 memberships，只留 `is_admin`）；
- 多 org 自助开企业（注册只落部署声明的那一个 org）；
- 不翻 `TENANT_JWT_ENFORCE` / `DEPLOY_ENFORCE_IDENTITY` 的**默认值**（ADR-0008 U1 选 C 的现状保持）。

## 3. 设计决策（每条给"选了什么 + 放弃了什么 + 为什么"）

| # | 决策点 | 选定 | 放弃 | 理由 |
|---|---|---|---|---|
| D-a | 登录凭据形态 | 用户名 + 口令 → 服务端 `mint_token` 签 **RS256 JWT**，回 `Authorization: Bearer` | 会话 cookie / 不透明 session token | 验签侧与 user 绑定（F3）已在位，缺的只是签发方 ⇒ 复用单一实现，不新造第二套身份轨；cookie 需另开 CSRF 面，超出本轮 |
| D-b | 口令散列 | **argon2-cffi**（`packages/agent-runtime` 新增 extra `auth`） | bcrypt / passlib 包装 / 自研 | AGENTS.md 框架选型规则「只用成熟框架」+ OWASP 首选；passlib 已是维护尾部，直接用它底下那一层少一段依赖；不进 `agent-core`（红线 1） |
| D-c | 空散列的语义 | `password_hash` **可空**（NULL=无口令账号），校验时 NULL ⇒ 一律拒 | `DEFAULT ''` + `== ''` 比较 | `''` 默认值会造出"任何非空口令都不匹配、但空串口令可过"的窗口；可空 + fail-closed 没有这个形状 |
| D-d | 登录名的规范形 | 写入前归一化为小写 `[a-z0-9._-]{3,32}`，直接当 `users.id` | 另开 `username` 列 + 唯一索引 | 013 已定 `id TEXT PRIMARY KEY`，加列属重复；字符集与既有 `_PRINCIPAL_RE` 的目录名安全约束同族，减少一类有损改写风险 |
| D-e | 注册落哪个 org | env `SIGNUP_ORG_ID`，缺省回落部署级 `default_tenant_id`；`INSERT ... ON CONFLICT DO NOTHING` 先补 `organizations` 行 | 每人一个 org | D9 单企业语义（`013:9-12` 同值域决策）；FK 不先补 organizations 行会当场炸注册 |
| D-f | 注册开关 | env `SIGNUP_ENABLED` 默认 **true**（演示期），生产可置 false 关死 | 恒开 | 关掉后"完整产品"就退化成管理员建号，所以默认开；但必须留这一档，否则内网外暴露时无人能拦 |
| D-g | 首账号提权 | 表内**零用户**时首个注册者 `is_admin=true`，之后一律 false | 手工 SQL 建管理员 | 演示环境没人有 SQL 入口；"首账号即管理员"是可预期的、且只在 `SIGNUP_ENABLED` 下成立 |
| D-h | 登录路由不被门卫拦 | 在 agent_server 的挂载点传 `skip_paths=默认+("/auth/login","/auth/register")`，**不改中间件源码** | 改 `identity_middleware.py` 的默认 skip 集 | `IdentityMiddleware.__init__` 已支持 `skip_paths` 入参（F3 同文件 `:113`）；改默认集会碰到并行线此刻正在写的同一个文件 |
| D-i | 静态 `X-API-Key` 的去留 | **并存**：`/query` 的鉴权依赖改为"中间件已断言身份 ⇒ 视为已鉴权；否则回落既有 key 比对"，`settings.api_key` 未配的旁路**不动** | 删 key / 强制 key+JWT 双持 | 删 key 会打断机器对机器调用与其余 5 个服务的同形契约（ADR-0008 U2 未答）；旁路属 U1，本文不代答 |
| D-j | 令牌寿命 | `ttl` 走 env `AUTH_TOKEN_TTL`，默认 **28800**（8h），过期后前端 401 ⇒ 跳登录页 | 上 refresh token | 引入 refresh 要再开一个端点 + 存储与轮换语义，是另一刀的量；8h 覆盖一个工作日演示 |
| D-k | 令牌存哪（浏览器侧） | `sessionStorage` | `localStorage` / HttpOnly cookie | 关标签即失效（演示机的常见形态）；HttpOnly cookie 与 D-a 的 Bearer 模型不同轨，需另开 CSRF 面。⚠ 残余风险如实写：JS 可读 ⇒ XSS 一次即失令牌，本轮没有 CSP 面 |
| D-l | 会话是否按人分桶（本轮） | **要**：登录态下 thread 主体从 `tenant-<t>` 改为 `tenant-<t>--user-<u>`（服务端断言值拼接，字符集内）；无 user 断言时**保持逐字不变** | 什么都不动（两人共用一条线）/ 等 conversations 表 | 不拼 user = 两个账号互相看得见对方的对话，这是产品级错误而不是缺特性；拼进主体仍是服务端断言明文，不违反 `resolve_thread_identity` 的"严禁凭据/客户端可控值"约束（F7），也不触发 P6-3 治理门禁（它禁的是"凭据→摘要"入口名）。正式归属仍归 PR-3 |
| D-m | 装配点是否收敛到 `mount_identity_gate` | **本轮不收敛**，保持直挂 + 传 `skip_paths` | 顺手改用装配点 | 改走 gate 会同时引入启动守卫（fail-fast 档）与内部 HMAC 头采信面，那是 ADR-0008 U1/B 的决策内容，不该搭登录这趟车 |

## 4. 影响面（文件级，逐条给"为什么动它"）

**新增**
- packages/agent-runtime/agent_runtime/migrations/016_user_credentials.up.sql 与配套 .down.sql（计划新增件，尚未存盘所以不带反引号） — `users` 加 `password_hash`（可空）+ `last_login_at`；不回改 013（checksum 钉住）
- packages/agent-runtime/agent_runtime/auth_users.py — 用户目录的单一实现：`create_user`（argon2 散列 + 归一化 + org upsert）、`verify_credentials`（NULL/错口令同文案同耗时档）、`touch_last_login`
- applications/agent_server/api/auth_router.py — 四个端点 `POST /auth/register`、`POST /auth/login`、`GET /auth/me`、`POST /auth/logout`（无状态，清前端态；见 §6 的诚实口径）
- web/src/components/LoginView.vue — 同页"注册/登录"两态，含错误体渲染
- web/src/api/auth.ts — 登录/注册/登出 + token 读写 sessionStorage
- 对应测试（计划新增，同一口径不带反引号）：packages/agent-runtime/tests/test_auth_users.py、applications/agent_server/tests/test_auth_router.py、tests/governance/ 里一条"口令不得进日志/响应"的不变量

**改动**
- `packages/agent-runtime/pyproject.toml` — 新增 `[project.optional-dependencies] auth = ["argon2-cffi>=23.1"]`
- `applications/agent_server/main.py:776` — `IdentityMiddleware` 挂载点补 `skip_paths`
- `applications/agent_server/api/auth.py` — `verify_api_key` 前置"已断言身份"分支；`resolve_thread_id` 按 D-l 拼 user 段
- `applications/agent_server/config.py` — 新增 `AUTH_TOKEN_TTL` / `SIGNUP_ENABLED` / `SIGNUP_ORG_ID` 三个设置项
- `web/src/api/sse.ts:262` — 有 JWT 时发 `Authorization: Bearer`，无 JWT 时保持 `X-API-Key`（两条通道并存，回退面）
- `web/src/stores/session.ts` — 登录态、401 处理、退出
- `web/src/App.vue` + `web/src/components/ApiKeyBox.vue` — 登录页/主界面两栏切换；ApiKeyBox 降级为"无登录态时的机器调用兜底"并在 UI 上标注
- `deploy/k8s/` 清单 — 挂 Secret：`TENANT_JWT_PRIVATE_KEY_FILE` + `TENANT_JWT_PUBLIC_KEYS_FILE`，注入 `AUTH_TOKEN_TTL` / `SIGNUP_ENABLED`
- `Makefile` / `web/` 门禁 — 登录面新增两条：`check-events.mjs` 形状不受影响，`verify-sse.mjs` 需覆盖"Bearer 与 key 二选一"的 header 装配

**不动（刻意）**：`packages/agent-core/agent_core/guardrails/auth.py`（内核函数签名与产物形状不变）、`identity_middleware.py` 源码（D-h）、ADR-0008 的 U1/U2/U3 默认值。

## 5. 密钥与部署（私钥绝不进仓）

1. 在 241 或 126 上 `openssl genrsa 2048` 生成一套（或复用已有网关密钥对——**待你确认有没有既有的**）；私钥 → Secret `agent-platform-jwt`，公钥 → 同 Secret 的另一 key；
2. Pod 内两把文件各自 bind，env 只给路径；
3. 轮换：公钥集是 kid→PEM 的多枚结构（`load_public_keys` 支持），所以换钥时可以新旧公钥并存、私钥只留新的；
4. 本机冒烟不需要密钥：`SIGNUP_ENABLED=true` + 私钥在位才开登录，未配私钥时 `/auth/login` 返回 503 + 固定 code（**不静默降级成 key**）。

## 6. 验收标准（每条都要绑证据件，口径见 `docs/operations/evidence-format.md`）

| # | 判据 | 手段 | 反证（种错必须红） |
|---|---|---|---|
| A1 | 注册新用户 ⇒ 201，且库内**存的是 argon2 散列、不是明文** | packages/agent-runtime/tests/test_auth_users.py + 真库用例（requires_pg） | 把散列换成明文存储 ⇒ 用例必须红 |
| A2 | 对口令 200 拿 JWT；错口令 401；**NULL 口令账号 401** | applications/agent_server/tests/test_auth_router.py | 把 NULL 当空串比较 ⇒ 红 |
| A3 | 错口令与"用户不存在"**同文案同 code**（不泄露账号存在性） | 同上，逐字比对两条响应体 | 分支返回不同 detail ⇒ 红 |
| A4 | 带合法 JWT 的 `/query` ⇒ 200，且服务端断言到该 `user_id`（`/capabilities` 面回读） | 集成用例 | 只绑 tenant 不绑 user ⇒ 红 |
| A5 | enforce 档（注入 `TENANT_JWT_ENFORCE=true`）下 `/auth/login`、`/auth/register` **仍可通**，其余无凭据请求 401 | 单测驱动中间件 + `skip_paths` | 忘传 skip_paths ⇒ 登录自己 401，红 |
| A6 | 同租户两个账号的 thread 不同（D-l），且无 user 断言时 thread 值与改前**逐字相同** | 用例锁定两态字符串相等/不等 | 主体改成客户端可传值 ⇒ P6-3 治理门禁必须红 |
| A7 | 口令/私钥/JWT **不出现在任何日志与响应体** | `tests/governance/` 不变量 | 把异常文本直接回显 ⇒ 红 |
| A8 | 前端：未登录只见登录页；登录后进对话；刷新仍登录；401 跳回登录页 | `make ci-web`（lint/typecheck/build）+ 浏览器面实拍 V 类截图 | token 读不到时不跳登录（静默空白）⇒ 截图面必须能看出异常 |
| A9 | 现网：Pod 内 `/auth/login` 真通、`/ui/` 真能注册登录问答（探针新增 C8–C10） | 126 现取读数，绑 rev | 私钥未在位却报 200 ⇒ 说明测的是 observe 档，判据不成立 |
| A10 | 回归不变：`make test` 九 session + 启发式 eval 不新增长红 | CI 门禁 | — |

**一句话不得宣称**：本轮**不**宣传"会话按人隔离已具备"（F1 的 conversations 归属表还没写入点），只宣传"入口有账号体系、同租户账号不共用会话线"。

## 7. 拆刀（每刀 < 400 行、可独立回退）

> 下面三片的**交付层已就地标注**（口径：接线 ≠ 启用，代码已交 ≠ 环境已达；逐格读数在取证件 §44）。

- **PR-2a 后端身份面**：迁移 016 + `auth_users.py` + `auth_router.py` + `main.py` skip_paths + `auth.py` 并存分支 + 测试（本刀最大，估 300–380 行）—— **代码 + 测试已交（2026-11-05 刀㊹）**：test_auth_users 61 passed / test_auth_router 24 passed / `lint_architecture` rc=0；未提交、未部署 ⇒ 现网上这组端点仍读 503
- **PR-2b 前端登录面**：`LoginView.vue` + `auth.ts` + `session.ts` + `sse.ts` 换头 + `App.vue` 两态 + ci-web 门禁随动（估 250–330 行）—— **代码 + 两把量具已交（2026-11-05 刀㊹，同刀）**：六步 rc 全 0、行为门 143 条、变异反证六枚存活 0。**同日晚些时候追加一枚形态改判（刀㊺，见 §8 第五项）**：建号态撞 409 由“只切态、等再点一次”改为“同一次提交内补发一发登录”；行为门现为 150 条（+7），四枚新变异全咬（逐格绑件见取证件 §45.2）；未构建未 rollout
- **PR-2c 部署与现网取证**：Secret/env 清单 + 探针 C8–C10 + runbook 加一步（估 <150 行）—— **清单面已落（刀㊺，未提交）**：00-config 三键 +21、20-agent-platform 五枚 env 与 tenant-jwt 卷 +52、tests/deploy 三枚新齿 +135（72 passed，两枚真面反证全咬，读数在 §45.3）。**还缺两件**：README 的密钥生成与写入条目（§6.3）、runbook 的密钥装配步与探针 C8–C10 ⇒ “注入点已在清单里”不等于“现网能签令牌”（Secret 对象还不存在，缺它 Pod 直接 fail-closed 起不来）
- **PR-2c 部署与现网取证**：Secret/env 清单 + 探针 C8–C10 + runbook 加一步（估 <150 行）—— ~~一行未动~~（该条已作废，形状见上一行）
- **⚠ 拆刀假设的一条修正（开工后才读到）**：原估「每片可独立回退」对 PR-2b 不成立 —— 新增的 `web/src/api/auth.ts` 从 `web/src/api/errors.ts` 取 describeError（工单件 §3 那条唯一收敛点），而后者正被 2026-11-04 起那条并行线重写 ⇒ **两条线共存能绿、各自单独回退不行**（实物：两族断言在同一工作区同时绿 143 条；而口径只到「本轮读到这个形状」）
- **PR-3（下一刀，不含在本方案）**：conversations 写入点 + thread 转不透明 uuid + 014b + 历史列表 API ⇒ 那时才叫"会话按人隔离"

## 8. 拍板结论（2026-11-05 已收；第 1–4 条均为人在选项里逐项点头的决定，第 5 条是同日晚些时候的**形态改判**，档位不同，见该条）

1. **D-a 凭据形态**：✅ 口令换 RS256 JWT（本方案），已按此开工。
2. **D-l 会话分桶**：✅ 本轮把 user 拼进 thread 主体；126 上 `tenant-default` 那条老会话线「看不见」的代价已认（老数据的在册处置结论本就是删了重灌）。
3. **私钥来源**：✅ 新生成一套，**只写进 K8s Secret**，不进仓、不入账、不进取证档。
4. **开工时机**：✅ 现在就开工（选项 b）。已知后果并接受：并行线正在写同两个包 ⇒ 提交门会一直红，账面只能攒着；我按 D-h 不碰 `identity_middleware.py` 源码来降冲突。
5. **409 那一发的处置（刀㊺ 追加，属形态改判，不是一次新提问）**：✅ 建号态撞 409 ⇒ **同一次提交内**用同一份凭据补发一发登录（`session.ts:submitCredentials`）。
   - **档位差异必须写清**：第 1–4 条是用户从选项里逐项点头；本条**没有经历过选项**。触发原因是需求原文第三次被说出，本轮先取实物再判：上一轮交的「撞 409 只切两态、返回 false」在**发数**这一格不满足那句字面（屏上要求再按一次提交）。
   - **与那次「保持现状」不矛盾**：取证件 §44.1 里人否掉的是「**去掉切态控件、单按钮先试登录、401 即自动建号**」—— 那是反向自动分派，会在前端重建一个存在性 oracle，且登录名打错一个字母就静默建号。本条是**正向**（建号 → 409 → 登录），不新增那一格 oracle。人当时选的「保持现状」约束的是**屏的形态**（一屏两态、有切态控件），本条一行未改那个形态。
   - **边界四条**（实物与理由住在 `session.ts` 的 `submitCredentials` 头注，此处只登目录）：① 只有 409 触发（403/503 原样报人）；② 绝不反向；③ 补发失败上屏第二发那句、不拼第三份文案；④ 意图快照必须在第一发之前存（切态按钮未被 `authBusy` 拦）。
   - **判据与绑件**：行为门 150 条（+7）、四枚变异全咬且逐枚 BYTE-EXACT，读数在取证件 §45.2（件 e50-mutation-20261105-181533.txt）。**验收面**：代码 + 行为件已交，**未提交、未构建、未 rollout** ⇒ 不得读成现网已生效。

**开工后新发现的追加事实（不属原方案，记在此以免后人对不上账）**：迁移文件 `014a_workspaces_org_pk.up.sql` **从未被 runner 应用** —— `base.py:22` 的 `_FILE_PATTERN = ^(\d+)_(.+)\.(up|down)\.sql$` 要求数字后紧跟下划线，`014a` 的 `a` 让整条文件名不匹配；`discover()` 实测返回 `[1..13, 15]`（v14 缺位）。叠加 runner 的版本推进口径是 `MAX(version)`（`runner.py:85`）而非已应用集合，**任何版本号 ≤ 现存最大值的迁移都永久静默跳过** ⇒ 014a 的 `workspaces.org_id/visibility` 列在任何环境都不存在，`register_workspace` 每次写入都走 `_is_undefined_column` 降级分支（那条分支不是「渐进部署窗口」的保险，而是常态路径）。本刀不受阻（登录面只依赖 013 建的三张表），处置与判据登记在 §9。

## 9. 已知的后续缺口（登记，不在本轮解）

- ADR-0008 U1/U2/U3 三项仍未决（本文只绕开，不代答）；
- agent_server 未走 `mount_identity_gate`（D-m），P13 门禁的覆盖度口径与另两个服务不同形；
- `web/` 无 CSP（D-k 的残余风险面）；
- 126 现网 port-forward 是唯一用户入口，"正式可达"三选一仍待人拍。
- **迁移发现器的两处结构性缺陷**（本刀实测发现，不在本刀解，需独立一刀）：① `base.py` 的 `_FILE_PATTERN` 不收字母后缀，而目录里已存在不匹配文件名的迁移 ⇒ 它不报错、不告警，只是**不在清单里**（静默）；② `runner.py` 以 `MAX(version)` 推进而非逐条对账已应用集合 ⇒ 补一个低号迁移永久无效，且校验和比对面（`_validate_applied_checksums`）只看清单里有的条目，不会报「库里没这条记录」。**判据形状**：`discover()` 返回的 version 清单与目录里 `*.up.sql` 文件名集合逐项对账必须相同；`schema_migrations` 里的版本集合必须是清单的前缀。两面都由 `scripts/lint_migration_refs.py` 或新齿拦截，不靠人读文件名。
- 镜像依赖声明位：`Dockerfile` 安装行原本只带 `agent-runtime[langfuse]`（`identity` 与 `auth` 均未带），而本地 `.venv` 里 `pyjwt`/`argon2-cffi` 靠 `uv sync --all-packages` 的**传递依赖**在位（实取 `Required-by`: pyjwt ← exhibition-agent/mcp/openai-agents，argon2 ← minio）⇒ 本地测试绿不等于镜像里有。本刀已把两个 extra 写进安装行；残余：仓内暂无一个「镜像内 import jwt / import argon2 能成」的断言件，属 PR-2c 面禁件要补的一格。
