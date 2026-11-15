# ADR-0015: 角色码进入 RS256 令牌 claims（角色从「表内一位」变为「服务端断言值」）

- 状态：**已外部评审（2026-11-11，模式 R，16/16 锚点复取相符）并据其 #5/#29 补第 2.6 条与代价 4；第二/三轮评审结论已并入**（第 2.6 条补 (d) 签发点唯一、第 3 节补放弃④、第 5 节 R9 补 E2E 变体、第 6 节补触发 8）；**第四轮审核订正了 (d) 的承重射程**（发送方 5→9 处、单入口不止 agent_server、新增 F21 两个必做项）——台账见方案件 §12/§14。**P1/P8/P9 已拍毕（2026-11-11：P1=viewer 兜底、P8=(a) viewer 兜底、P9=最小闭环）**。❗ **「刀 1 前置清零」是 overclaim，第四轮订正**：清零的只有 **1a/1b**；**1c 仍被两项阻塞**——① 现网 `app_config.yaml` 取证（本机不可达 126，方案 Q6/#25）；② 在途错误信封收敛件对 `identity_middleware.py`/`query_router.py` 的冲突规避（D10/R-8）。本件的**承重面 = 第 2.6 条（role 进子服务的承载）**，评审方判它是开工前必须写死的一条 D1 级决策
- 日期：2026-11-11
- 取证 rev：`d9fa8eaa`
- 关联：`docs/plans/plan-roles-kb-datasource-console-2026-11-11.md`（本 ADR 的 D1/D2/D3/D9/D10/**D11** 出处，事实表 F1–F6 / F14–F21 同件）；上游 `docs/adr/0007-server-asserted-tenant-identity.md`、`docs/adr/0008-auth-mode-selection.md`
- 决策边界：**D2**（改 claims 形状 + 对外契约字段集被在册用例钉住 ⇒ 人批，AI 给证据）。❗ 第 2.6 条选定的承载通道另触 **D1**（跨服务契约的 payload arity 变更 ⇒ 人批、AI 给兼容证据）

## 1. 问题

需求是「不同角色看到的功能不一样」。但仓内的角色位今天是**死的**：`users.is_admin` 只被写入和返回，没有任何端点据它放行（F1）；同时权限引擎（`planner/policy.py` 第 5 条、`skills/registry.py:312-337`）**已经写好了按权限集过滤的逻辑**，却因为 `caller_permissions` 恒为 `None` 而整条跳过（F2）。

所以缺的不是引擎，是**断言源**：服务端没有一个「这个人是什么角色」的可信值。可选的断言源只有三类——body/query 参数、每请求回库查、令牌 claim。前两类分别撞 D20（body 不是断言源）和 F7（身份门只 4/6，knowledge-service 与 exhibition-agent 各跑自己那套 fork、零依赖 agent-runtime，回库通路建不起来）。

❗ **本节漏了一问，评审 #5 指出**：上面三类答的是「agent_server 从哪里知道角色」；**「子服务（nl2sql）从哪里知道」是另一个问题**，本件初版一字未写（方案 §11 已登记）。它不是同一件事的追问，因为 nl2sql 不验用户令牌、它只听内部签名头 ⇒ 不先定住它，“按最顺手读法实现（把 role 放进 body）就自动违反本件第 6.5 条”。现由 **第 2.6 条**（payload 增键 `r`）关这一格。

## 2. 决策

1. **`mint_token` payload 增加 `role` claim，`TokenClaims` 增加 `role` 字段，`verify_token` 解析但不强制存在**（缺 → `None`）。值域 = 内置三角色码 `admin | editor | viewer`，与迁移 017 的 `CHECK` 同源。
2. **claims 只带角色码，不带权限集。** 「这个角色能干什么」由服务端一处常量表（`agent_runtime/authorization.py`）从码算出。
3. **权限映射不入库**（本轮）。`role → features` 是代码常量，改它 = 发版。反面要记住：今天 `admin_roles` / `default_query_role` 的真值来自 `conf/app_config.yaml data_permission:` 块（F16）——那就是“角色写在部署件里”的现有形状，本决策是把它从文件里拿掉，不是从库里拿掉。
4. **缺 `role` claim 的存量令牌按 `viewer` 兜底**（最小权限），并记首次 WARNING；不返回 401。❗ **计数口径按评审 #6 订正（详第 4 节代价 3）**：WARNING 按 `(tenant, user)` 首次记一条、**另走可聚合计数**——只记一次会使条数封顶 1，R-1 的「持续超一个 TTL」触发条件永不可评。**已拍（2026-11-11 P1）：viewer 兜底**。
5. **`/auth/me` 返回 `role` + `features[]`**，前端只渲染不判定；`_sanitize_identity` 同批剔除 `role/features/permissions`，使 LLM 可填参数面无法自报角色。
6. ❗**（本件新增，补评审 #5 指出的真空白）role 进子服务的承载 = 内部签名头的 v1 payload 增键 `r`**。`X-Internal-Tenant` 的 payload 今天已是 `{"t","u","ts"}` JSON，验签侧用 `.get()` 取值（事实 F17）⇒ **加键是向后兼容的扩展方向**（旧验签方忽略新键；签名覆盖整个 payload ⇒ 旧钥签不出新头）。三条约束同时成立才算本条完成：**(a) 解释只一份**——`role → features` 只住在 `agent_runtime/authorization.py`，子服务（nl2sql 属 application 层）是 **import 它调 `has_feature`**，不得自写 `if role == "admin"`（lint 禁字面比较）；**(b) 无断言值即脱敏**——头里没有 `r`（旧调用方 / `API_KEY`）⇒ nl2sql **无条件脱敏**，fail-closed；**(c) 不用的服务要写明不读**——KS 的 fork 调**同一个** `verify_internal_header` 且只取 tenant ⇒ 不改代码也不受伤，但它「带而不用」必须写进方案 §7，否则将来有人在 KS 自行解释 `r`，就是第 6.5 条要报的形状。❗ **第二/三轮补（(d) 签发点唯一，方案 D11 第三轮升级点 1 同步）+ 第四轮射程订正**：`r` 键的**签发实现只住在 agent-core**（`build_internal_headers(...)`），**装配点两个应用各一个**（agent_server 与 federation 各一个 `post_remote(...)`）——❗ 原写「只住在 agent_server 的出站单入口」窄了：方案 F20 复取后有 **2 处发送方在 federation**（`agent/async_subagents.py:171`、`tools/knowledge_tools.py:145`），只收敛 agent_server 会使配套 lint 在 federation 报红或被迫白名单豁免（= 本条被绕开，第 6.8 条）。**发送方清单 = 9 处**（❗ 原写「五处（nl2sql ×3、kefu ×1、federation ×1）」错：HMAC 已签 **3** + 静态 Bearer **2**（KS，不是 HMAC）+ 裸无凭据 **4**（nl2sql ×2 / kefu / **exhibition**），详方案 F20）全部改经它；**逐发送方各拼一行头是放弃项（第 3 节④）**。今天主路径**四处裸无凭据** ⇒ **只改验签侧不改签发侧，admin 经 web 问数永远被脱敏**（方案 N-1）。❗ **第四轮新增两个必做项（方案 F21）**：① 新增 `build_internal_headers` **必须同步 `agent_runtime/identity.py:261` 那层委托包装**（它不是第二实现，注释自陈原语单一在 agent-core；但 `knowledge_tools.py:145` 经它签，不同步则该路径拿不到 `role` 且不报错）；② `knowledge_tools.py:140-147` 的 `except ImportError: pass` 是**静默不签**（比 federation warn-once 更弱），收编时必须改具名失败或 warn-once。配套门禁 = lint 禁 applications 下裸 `httpx.AsyncClient(`/`client.post(` 出站（扫描面须盖全 9 处）。❗ **第六轮（方案 H1/P10）：本条 lint 的扫描边界未定，照写会大量误报**——applications 下 `AsyncClient(` 实有 **33 处**（22 处测试 + 生产面约 5 处非子服务出站：warehouse/search/skill_loader/evaluation），而子服务出站与其他出站**语法上不可区分** ⇒ **必须先拍方案 P10 三条边界规则**（排除 tests/evaluation、非子服务白名单、按 URL 环境变量名识别子服务出站），不拍则本条 lint 不得开工；替代选项 = 暂不建该 lint，改由 R4 E2E 变体 + 代码评审承担（同 R7 缓建先例，带恢复触发）。**第 2.6 条 (a)(b)(c) 不受影响**（它们不依赖这条 lint），仅 (d) 的「强制门禁」那一层待拍。❗ **拍板（2026-11-11 P10=甲）：窄门禁**——该 lint 不钉 httpx 语法（applications 下 `AsyncClient(` 实有 33 处、子服务与外部 API 语法不可区分），改钉**签发符号调用点**（`build_internal_headers(`/`sign_internal_header(` 只准出现在两个装配点文件 + agent-core 本体）；盲区「新出站不签」由 R4 E2E + 本条第 6.8 触发 8 承担。

## 3. 放弃什么（逐条，不是装饰）

| 放弃 | 为什么放弃 |
|---|---|
| claims 带 `permissions[]` | 改一个权限点就要重签所有令牌 ⇒ 与 N3「不做吊销面」叠起来会把「改权限」变成全量重登事件；且权限集进令牌等于把它变成对外可见、可被下游各自缓存的第二真相 |
| 每请求回库查角色 | 建不起来（F7）；且会在 SSE 主链路加一次同步 DB 依赖 |
| body/query 传 role | 直接撞 D20，且把 F9 那类「客户端自报身份」的 fail-open 面重新打开 |
| 角色表 + `role_permissions` 入库 + 自定义角色界面 | 需求原话用三个内置码即闭合（F1 现状零消费者）。触发条件 = 第一个真实租户要求「和别家不一样的角色」。迁库是**纯 expand**：本 ADR 的 claims 形状（只带码）在迁库前后不变，消费点不变 ⇒ 延后不返工 |
| 缺 role 直接 401 | enforce 默认关（N5/ADR-0008 U1 现状 C）下，这会把「升级后旧令牌全失效」做成生产事故 |
| ❗ body 透传 `role` 或透传“可否脱敏”布尔（评审 #5 候选 ii） | 撞 D20（body 不是断言源），且把判定权从断言源搬进应用层；布尔仍需一个载体，问题没消失只是搬家 |
| ❗ 转发/重签 JWT 到子服务（nl2sql 自己验 RS256 拿 role） | 技术上可行（`identity_middleware.py:147-156` 对形如 JWT 的 Bearer 直接 `verify_token`），**但今天 agent_server→子服务传的是静态凭据不是 JWT**（`capabilities.py:259/:284`）⇒ 改它 = 改转发凭据形状 = **撞 ADR-0008 U3（未决项）**，比加一个 payload 键重一个量级。若 U3 日后定为“ExecutionContext 迁 JWT”，本条应重开（已写进第 6.6 条） |
| ❗ claims 里另加 `features[]` 以便子服务免查映射表 | 就是第一条放弃项的变相版；两处真相（码与集）一旦不同步，`role` 与 `features` 谁赢无法回答 |
| ❗ **逐发送方各补一行签头（第二/三轮 N-1）** | 「每处各自实现」反模式——federation 的 `_internal_tenant_header`（`async_subagents.py:56-91`）已是活标本；`as_remote_skill` 不拥有 HTTP 出口（`skills/remote.py:14-27`）⇒ 新服务每接一个就再抄一份 warn-once/每请求现签逻辑。治本形状见第 2.6 条 (d)：agent-core 单一实现 + 出站单入口 + lint 禁裸 httpx 出站（三层齐备，照 P2 统一异常处理先例） |

## 4. 后果（含必须如实登记的代价）

**正面**：F3 nl2sql 里 `default_query_role` 那句「未接身份门前的最小权限默认」注释第一次有了兑现路径；F5「刷新即失」被 `/auth/me` 带回角色而关闭。

❗ **本件初版确实写过一句「F2 那格『引擎在、声明面空』被填上」，现按评审 #2 删掉**：本 ADR 交的是**端点级** feature 门，不是 skill 级权限过滤（`caller_permissions` 的生产接线在两个应用的装配层，不在本轮射程，事实 F19）。“引擎在、声明面空”那一格**仍然开着**，本轮的处置是把它**机检登记为不接线**（方案 N7 + 反证 R2 新形状），而不是声称它被填了。把这两件事混为一谈就是本 ADR 最可能被读错的一格。

**代价，四条，都要写进界面或文档，不许只留在这份 ADR 里**：

1. **改某个人的角色 = 他下次登录才生效**（最长一个令牌 TTL，F6 上限 3600s）。本轮**不做吊销面**，界面须明写这句（N3 + 风险 R-3）。
2. **claims 是不可逆面**：`role` 一旦签出，下游验签方（federation、kefu、nl2sql、KS 的 fork）都会看到它。加字段容易，改语义或删字段就是跨服务变更 ⇒ 本 ADR 是那条变更的唯一登记点，后续任何 claims 形状改动须引用并修订本件。
3. **兜底 `viewer` 会掩盖配置错误**（D9 与 F9 同族）。缓解 = WARNING 条数可观测 + 风险 R-1 的复审触发条件；**不缓解到「看不见了」**。❗ 按评审 #6 订正口径：WARNING 按 `(tenant, user)` **首次**记一条、**另走可聚合计数**——只记一次会使条数封顶 1，“持续超一个 TTL”这个触发条件就永不可评。**本条的代价不是“日志多点”，是“必须有一个可聚合量”，否则代价三不可验证。**
4. ❗**新增（代价，评审 #29 + 本件第 2.6 条）**：**内部签名头的 payload 形状从此是第二个不可逆面**。与代价 2 同类但不同件：claims 面只有 agent_server 会签，而内部签名头是**三方共用一把尺**（`verify_internal_header` 住在 agent-core，agent_server/federation/nl2sql 走共享中间件、KS 走自己的 fork 但**调同一个函数**）。⇒ 以后再往 payload 加键，仍沿本件登记（旧验签方忽略新键 = 安全方向；**改已有键的语义 = 不可逆**）；且本件必须同批回答「新签发方×旧验签方」与「旧签发方×新验签方」两格行为（方案反证 R9），只验一个等于没验。**登记点：本件与方案 §9 R-9。**

## 5. 验证（判据，不是意图）

- 反证 **R1**（旧无 role 令牌照常验签通过 → 得 `viewer` 集；断言项 = **兜底计数 ≥ 1 且能力集 = viewer**，不断言“恰好一条 WARNING”）
- ❗ 反证 **R2**（**按评审 #2 改写**）：不再是“给 skill 声明 `permissions` 并分两次调”——那三个形状已被在册用例钉住（`packages/agent-runtime/tests/test_policy.py:106` 等），且本轮无接线项。新形状 = **机检登记不接线**：lint 断言本轮不得出现 `permissions=` 声明，违者红并报具名理由。**它封的是“接上权限引擎”这句话被读成已具备**，不是封引擎行为。
- ❗ **新增 R9**（第 2.6 条承载的兼容自证）：旧形状头（无 `r`）→ nl2sql **无条件脱敏**（行为翻转可断言）；带 `r` 的头 → KS 侧照旧只读 tenant、**不报错也不 401**。两个方向都验才算过。❗ **第三轮补**：R9 之外，方案 R4 加 **E2E 变体**——经真 `/query` 链路断言 admin 不掩码；直调 `execute_sql` 的反证放不过「签发侧未改」的传输断（N-1 空转齿）。
- ❗ **新增 R10**（未断言调用方档位）：只带 `API_KEY` 的请求打各写面端点 → 行为按 P8 结果可断言；**唯一不许的是“未定义”**。❗ **P8 已拍（2026-11-11）：(a) viewer 兜底** ⇒ 具体断言定为「只带 API_KEY 调写面（如 `POST /sql/train`）→ 403；调 `chat.run` → 放行」（与 D9 同一条「无断言→最小权限」规则，不新造第二条口径）
- 反证 **R3**（viewer 调 `POST /sql/train` → 403 且一行不落）
- 契约随动：`tests/governance/test_login_no_secret_leakage.py` **三格**字段集合为**扩**非松（§7 已给理由；本件初版写“两处”是错的，评审 #3 纠正）
- 每条完成陈述按 `docs/operations/evidence-format.md` §1 五字段写

## 6. 复审触发条件

出现任一情形，本件必须复审（不是「可以考虑」）：

1. 要把权限集放进 claims，或要给 claims 加第二个授权类字段；
2. 第一个真实租户要求差异化角色 ⇒ N2 触发，此时**先决条件**是 D5（消费侧按 feature 判）已就位，未就位不许建角色表；
3. enforce 默认值被翻，或 `plan-identity-gate-6of6` 收敛到 6/6 ⇒ 兜底档位（第 2.4 条）需重判；
4. 第一次真实的「需当场剥夺权限」事件 ⇒ N3 吊销面重开；
5. 任何下游服务开始**自行**解释 `role` 字符串（而不是问 `has_feature`）——这一条是本 ADR 最可能失败的形状，见到即报。❗ 第 2.6 条落地后本条的**可机检形式**：字面比较 `role == "admin"`（或同类）出现在 `authorization.py` 之外任何处 ⇒ 报红；包括 KS 那侧（它拿到了 `r` 但不得读）。
6. ❗**新增**：内部签名头 payload **改已有键语义**（`t`/`u`/`ts` 任一改口径），或 ADR-0008 U3 定为“ExecutionContext 迁 JWT” ⇒ 第 2.6 条的通道选择需重判（届时“转发 JWT”从最重候选变为首选，且 claims 面与内部头面应合并为一个断言源，而不是两处各存一份角色）。
7. ❗**新增**：第一个需要**跨 KS/exhibition 生效**的 feature 消费点出现 ⇒ 第 2.6 条的 (c)（带而不用）不再成立，得先回答“零依赖 agent-runtime 的服务如何拿到唯一映射表”（那同时是 F7 身份门 4/6 的老问题）。
8. ❗ **新增（第三轮）**：出站签名出现**第二个实现位**——applications 下裸 `httpx.AsyncClient(`/`client.post(` 出站命中 lint 白名单之外，或 `build_internal_headers` 被绕过 ⇒ 第 2.6 条 (d) 的单入口被绕开，role 断言在主路径**静默失效**（与 F9 同族的静默形状）；见到即报。❗ **第四轮补（事实澄清 + 新触发面）**：经复取，`agent_runtime/identity.py:261` 的同名 `sign_internal_header` 是**合规委托包装**（→ `_core_sign`，注释自陈原语单一在 agent-core），**今天不算第二实现位**；但它构成一个**静默失效面**：新增 `build_internal_headers` 时若不同步该包装，经它的调用方（`knowledge_tools.py:145`）拿不到 `role` 且无任何报错 ⇒ **本条触发面扩为「包装层与 core 实现参数面不同步」**（方案 F21①）。
