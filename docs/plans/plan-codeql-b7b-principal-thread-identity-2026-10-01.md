# B7b 方案：会话身份 principal 化 —— 让 `#38`/`#39` 的 sink 真实消失

> 状态：**上游取证完成（§1）、三项均已拍板（§8，2026-10-01 按推荐值接受）** ⇒ 可开工 B7b-1。本文件**未动任何代码**。
> 日期：2026-10-01　前置：`plan-v3-identity-merge-2026-10-01.md` §5 步骤 6（「合入后回到 B7b：在已断言主体上做 principal_id 化（另出方案）」）
> 关联：`docs/plans/plan-codeql-batch7-no-dismiss-real-fixes-2026-10-01.md` §4 / §4.1（强制前置）、`docs/TODO.md` §8
> 约束继承：用户主线要求「**不要用 dismiss 这种简单的处理方式**」——本方案不引入任何 `false_positive` / `wont_fix` 标记，验收只认 `state=fixed` 且 `dismissed_at=None`。

## 1. 强制前置取证结论

取证方式：`gh api -H "Accept: application/vnd.github.raw"` 直接拉 `github/codeql` 上游源码落盘（`.codeartsdoer/temp/q_*.ql` / `q_*.txt`，temp 目录不入库，§9 给了复现命令），不靠模式猜。SARIF `codeFlows` 通道不可用（`/code-scanning/analyses/{id}` 无 `download_url`；`/code-scanning/sarifs/{id}` 无 `sip` 字段，令牌缺 `security_events` scope），故路径级结论由「规则模型源码 + 全仓 grep + 告警列号比对」三者交叉定案。

### 1.1 规则的分支结构（决定「什么才叫修好」）

`py/weak-sensitive-data-hashing` 的 select 合并了**两个互斥分支**（`WeakSensitiveDataHashingQuery.qll:83-86` `DataFlow::MergePathGraph`），两分支的源/汇条件不同，必须分别核：

| 分支 | 源条件 | 汇条件 | sha256 是否命中汇？ |
|---|---|---|---|
| `NormalHashFunction` | `SensitiveDataSource` 且**分类非 password**（`WeakSensitiveDataHashingCustomizations.qll:27-28` + `:54-58`） | `algorithm.isWeak()`（`:61-73`） | **否**（见下） |
| `ComputationallyExpensiveHashFunction` | `SensitiveDataSource` 且**分类 == password**（`:123-131`） | `(PasswordHashingAlgorithm 且 isWeak()) 或 任意 HashingAlgorithm`（`:137-158`，注释明示两类算法互斥） | **是** |

关键实取（`shared/concepts/codeql/concepts/internal/CryptoAlgorithmNames.qll`）：

```
isStrongHashingAlgorithm:  "SHA2" "SHA224" "SHA256" "SHA384" "SHA512" "SHA3…" "BLAKE2/3" … (:16-35)
isWeakHashingAlgorithm:    "HAVEL128" "MD2" "MD4" "MD5" "PANAMA" "RIPEMD…" "SHA0" "SHA1"   (:40-45)
isStrongPasswordHashing:   "ARGON2" "PBKDF2" "BCRYPT" "SCRYPT"                              (:75-77)
```

⇒ **`hashlib.sha256` 属于 strong `HashingAlgorithm`，`isWeak()` 为 false**：
- 它在 `NormalHashFunction` 分支**根本不是汇** ⇒ `fingerprint` 的形参 `secret`（分类 `secret`，命中 `maybeSecret()`）**不足以单独产生告警**；
- 它只在 `ComputationallyExpensiveHashFunction` 分支成汇 ⇒ **`#38`/`#39` 触发当且仅当：一个 `password` 分类的值流入摘要的「被摘要位」**。
- 旁证：`#38` 的告警文案是 "insecure for **password** hashing, since it is not a computationally expensive hash function" —— 文案本身就指名了 Expensive 分支（我在拿到文案时未用它区分分支，见 §1.3 自纠）。

### 1.2 定案后的四条硬结论

| # | 结论 | 证据 |
|---|---|---|
| 1 | 流是**全局跨过程**的：`module Flow = TaintTracking::Global<Config>`，并带 `isAdditionalFlowStep = sensitiveDataExtraStepForCalls` | `WeakSensitiveDataHashingQuery.qll:33-34` `:41` `:65-66` `:73`；`SensitiveDataSources.qll:168-173` `:336` |
| 2 | 汇是**被摘要的数据**，不是 HMAC 的密钥位：sink = `operation.getAnInput()`。列号实取比对：`#38` col **47-69** 恰为 `secret.encode("utf-8")`（`hmac.new` 第二参＝消息位，同行的 `pepper.encode(…)` col 23-44 **未被报**）；`#39` col **29** 恰为 `(api_key or "").encode("utf-8")` | `WeakSensitiveDataHashingCustomizations.qll:61-73` `:137-158` + `auth.py:92` / `:117` 逐列对齐 |
| 3 | `password` 分类**纯靠名字**判定：`maybePassword()` = `pass(wd\|word\|code\|.?phrase)(?!.*question)` / `(auth(entication\|ori[sz]ation)?).?key` / `oauth` / `api.?(key\|tok)` / `mfa`；`notSensitiveRegexp()` 只看名字里有没有 `hash\|sha\|encode\|path\|url` 等词 | `SensitiveDataHeuristics.qll:76-80` / `:152-156`；源类别 6 个：`SensitiveVariableAssignment` / `SensitiveAttributeAccess` / `SensitiveSubscript` / `SensitiveGetCall` / `SensitiveParameter`（**形参名即源**）/ `GetPassCall`（`SensitiveDataSources.qll:250-333`） |
| 4 | 运维脚本**不是逃逸口**：仓内无 `.github/codeql/` 配置（Glob 实取 0 文件）→ default setup 走 autobuild 全仓扫描，`scripts/` 同样在分析面内 | `.github/codeql/*` 不存在（实测） |

⇒ **验收口径（本方案的判定基准）**：

> `#38` 只需、且必须让**三条 password 分类输入链**（§3.1）全部不再把凭据送进摘要；三条里任何一条留着，告警就留着。删除 `fingerprint` 本身**不是**消告警的必要条件（它的 `secret` 形参不构成 Expensive 分支的源）——但链拆完后若它无调用者，作为死代码删除。
> `#39` 的源是 `legacy_thread_id(api_key)` 的形参名 ⇒ 只要该函数还在把 `api_key` 送进 `sha256`，告警就在；唯一诚实的出路是**让它不再需要从密钥复算**（§4.5）。

### 1.3 自纠记录（本文件初稿的错误，已就地订正）

初稿 §1 我写下「只改调用方**不够**：形参 `secret` 自身即源，所以即使所有调用方都传非敏感值，只要该函数还在把 `secret` 送进摘要，告警就在」。这条**错**，且错因正是本批反复立的红线没执行到底：

- 我看到 `SensitiveParameter` 存在（形参名即源）**就直接推结论**，漏了两步取证：① 该分支要求的分类是 `password` 而非任意敏感分类；② `NormalHashFunction` 分支的汇有 `algorithm.isWeak()` 前置，而 `SHA256` 在 `isStrongHashingAlgorithm` 名单里。
- 更该自查的是：**告警文案已经写明 "password hashing"**，这个信息在我手上却没被用来区分分支。
- 影响面：初稿据此推出「必须删 `fingerprint` 才能消 `#38`」，把方案推向"以删除换绿灯"；实际必要条件是**拆三条链**。若照初稿执行，会出现「删了函数但别处仍有 `api_key` 被摘要 ⇒ 告警照报」或反向的「为消警而删有用的实现」两种浪费。

教训入库：**规则源码取证必须读到「源条件 ∧ 汇条件」两侧的最终合取**，任何一侧没核完就不能写结论；告警 message 的措辞是分支指纹，必须优先用来收敛假设。

## 2. 目标与非目标

**目标**
1. 三条「凭据 → 摘要」链（§3.1）全部拆除，使 `#38` 的 password 分类输入归零；`fingerprint()` / `legacy_thread_id()` 拆完后若无调用者则作为死代码删除 ⇒ `#38`/`#39` 以 `state=fixed` 自动闭合。
2. 会话身份改为**服务端断言的主体标识**，与 ADR-0007（服务端断言租户身份）同向；客户端不可指定/猜测他人会话（保留现有的防劫持语义）。
3. 拆掉「用户身份摘要」与「上游 provider 密钥摘要」共用一个函数的**分类错**（Batch 7 §4.1 结论 1 的第③条）。

**非目标**
- 不改 JWT/HMAC 令牌格式、不改 `X-Internal-Tenant` 契约（属身份层，已合流）。
- **不换 scrypt/pbkdf2/bcrypt**。§1.1 取证后要把代价说准：换慢哈希**确实能让告警消失**（`SCRYPT` 属 `isStrongPasswordHashingAlgorithm`，两个分支的汇条件都不再命中），所以这**不是**"看不见"而是"按规则字面要求办"。不选的理由是工程判断：本仓输入是**每部署一把高熵随机密钥**、产物只做查表标识、且**在中间件热路径上每请求算一次**——慢哈希的前提（低熵口令抗离线暴破）不成立，代价却是纯延迟 + 全部既有会话摘要漂移；`auth.py:19-22` 的定调与此一致。
- 不做「迁移历史数据」以外的数据库变更；不新建表除非 §8-Q1 选到需要映射存储的分支。

## 3. 影响面（全部 `git grep` / 实读取证，非推演）

### 3.1 三条 password 分类输入链

| 链 | 源为何是 password 分类 | 生产站点 | 语义 |
|---|---|---|---|
| ① 会话身份 | `derive_thread_id(api_key)` 形参名命中 `api.?(key\|tok)` → `SensitiveParameter` | `applications/agent_server/api/auth.py:32`、`applications/agent_federation/api/auth.py:32`（**全仓仅此 2 个生产调用点**，穷尽 grep 47 命中，其余为测试 / `scripts/migrate_thread_identity.py:49` / 文档） | 调用方凭据当身份熵源 |
| ② 限流桶 | `headers.get("x-api-key")`（`auth.py` 内）命中 `SensitiveGetCall`：`get` + 字面量 `x-api-key` | 消费者 `packages/agent-core/agent_core/guardrails/web.py:146`（中间件唯一消费点）；knowledge-service 经 `utils/security_guard_utils.py` re-export | 每密钥一个桶（`auth.py:149` 的 `key:{fingerprint(provided)}`）——**已于 B7b-2 拆除**，现为「断言主体 → IP」 |
| ③ LLM 客户端缓存键 | `_hash_api_key(api_key)` 与 `get_llm_client(..., api_key=...)` 形参名 | `packages/agent-core/agent_core/llm/registry.py:46` → 进入 `cache_key`（`registry.py:107`） | **上游 provider 密钥**，属基础设施秘密，与调用方身份无关 |

### 3.2 thread_id 的持久化面（迁移必须覆盖）
- **文件系统**：`applications/agent_federation/api/server.py:242` 写 `updated/session_{safe_filename(thread_id)}`；`agent/main_agent.py:558/563` 读 `output/session_{workspace_id}` 与 `updated/session_{workspace_id}`（`main_agent.py:552` 注明「workspace_id: 工作空间/thread_id 标识」）。
- **checkpointer**：`checkpoint_cleaner.py` 按 `(tenant_id, thread_id, checkpoint_ns)` 分组保留最新；LangGraph 三张表 `checkpoints` / `checkpoint_writes` / `checkpoint_blobs`（`migrate_thread_identity.py:44`）。
- **推送/监控**：`agent_core/monitor.py:70` 按 thread_id 推 WebSocket；`main_agent.py:577` `set_thread_context(workspace_id)`、`:609` per-thread 互斥锁。
- **仓内无 schema 依赖**：`git grep` 实取 `*.sql` 命中 thread_id **0 处**（列由 LangGraph 建表），故不需自写 DDL。
- 本地 `applications/agent_federation/updated/` 实测为空目录 ⇒ 历史会话数据不入库，迁移属**部署侧动作**，CI 无法代验（须在验收里如实标注）。

### 3.3 身份层现状（决定「principal 从哪来」，含两处硬约束）
- `agent_runtime/identity.py`：`TokenClaims(tenant_id, user_id, jti, exp, iat)`，`user_id = payload.get("user_id") or payload.get("sub")`（`sub` 被 `options={"require": ["exp","iat","sub"]}` 强制，故 JWT 路径下**必非空**）。
- `workspace_registry.py:64/73`：`bind_user_context` / `server_user_id(default)`（两者都缺 → 抛错 fail-fast）。
- **约束 A（实测否定式）**：`server_user_id` **零生产消费者**——全仓 `git grep -n "server_user_id"` 仅命中定义处、`__all__`、ContextVar 名，以及 `docs/plans/plan-tenant-identity-2026-09-27.md:78` 一句设计说明。即「服务端主体 id」这条能力**存在但从未被接线**。
- **约束 B**：`applications/agent_federation/api/identity_bridge.py:16-18` 的 `_apply(tenant, user)` **显式丢弃 user**（注释：「联邦当前仅断言 tenant 进 api.context（user 断言随 A5 运行时身份接入）」）；`agent_server/main.py:507` 以默认 `apply_tenant_context` 挂载（user 会绑定），但 observe 默认模式下「无凭据 → 不绑定」，`SINGLE_TENANT` 分支 `_run(single, None, …)` 也**不带 user**。
- ⇒ 结论：**「有 user 断言」在今天的默认部署里不成立**。方案必须给出主体 id 的分阶段来源策略（§6），否则切 thread_id 会让零依赖冒烟直接抛 `server_user_id()` fail-fast。

### 3.4 现行为的一个必须写破的事实
`resolve_thread_id`（两处 app）在鉴权启用时**忽略客户端 `session_id`**，一律返回 `derive_thread_id(api_key)`；而 `API_KEY` 每部署一把（`agent_server/config.py` 的 `settings.api_key` / federation `api/auth.py:19` 的模块级 `os.getenv("API_KEY","")`）。⇒ **今天所有持同一密钥的客户端共用同一个 thread_id 会话桶**。任何「按主体细化」的选择都是**对外可见的行为变更**（客户端原本被忽略的 `session_id` 可能开始生效、或历史会话归属改变），不得当作无副作用重构。

## 4. 修法（按链拆，每条都给出「sink 为何不再命中」）

### 4.1 链①：thread_id ← 服务端断言租户（Q1 定 (a)），密钥退出身份派生
`derive_thread_id(api_key)` 替换为 `resolve_thread_identity(tenant)`（**已拍板：租户级**）：入参是**已断言的租户字符串**（不是凭据），直接拼 `THREAD_ID_PREFIX + tenant`，**不做任何摘要**（租户 id 本身即可入目录名）。⇒ 链①的 password 源归零。
> 注意（勿踩自己刚立的红线）：**不能靠把形参 `api_key` 改名来消告警**。分类是名字驱动的，改名确实能让规则闭嘴，但被摘要的仍是凭据 ⇒ 纯 gaming。修法必须改变**值的性质**（凭据 → 服务端主体 id），名字变化只是结果。

### 4.2 链②：限流桶 ← 断言主体 / 租户，退回 IP 保持现状（B7b-2 已实施，含实施补记）
`resolve_client_key` 改为「已断言主体优先」：主体在 → `sub:<subject>`；否则走现有 `ip:<host>` 分支（`auth_enabled=False` 时早已如此，见 `packages/agent-core/tests/test_guardrails.py:44-50`）。**删除 `key:{fingerprint(provided)}` 分支**，并去掉 `headers.get("x-api-key")` 结果向摘要的通路。
> 代价要写清：桶粒度从「每密钥」变为「每 IP」（未接主体时）或「每主体」（接入后）。既有测试 `test_resolve_client_key_uses_fingerprint`（`packages/agent-core/tests/test_guardrails_fingerprint.py:116-119`，断言 `key == f"key:{fingerprint('secret')}"`）与 knowledge-service `tests/unit/test_security_guards.py:212-221` 的 `key:` 前缀断言必须**按新契约改写**——这不是放宽断言凑绿：桶键形状本就属内部实现，用例应断言语义「不把密钥明文放进桶键/日志」而非具体摘要值。

> **实施补记（2026-10-02，B7b-2）**——四点比初稿更硬，登记以免后人按初稿字面理解：
> 1. **签名直接删掉 `headers`/`auth_enabled` 两个形参**（不只是「不再读它们」）：新签名 `resolve_client_key(client_host, subject=None)`。凭据在**类型层面**就进不来，而 CodeQL 的链②入口恰是 `headers.get("x-api-key")` 这一句——留着形参就是留着缺口。守门：`test_resolve_client_key_signature_cannot_receive_credential`（`inspect.signature` 断言参数集恰为 `{client_host, subject}`）。
> 2. **主体不能由 kernel 自取**（红线 1：`agent-core` 不得 import `agent-runtime`，而 `server_tenant_id()` 在 runtime 的 `workspace_registry.py`）⇒ 改为**中间件构造参数注入** `subject_provider: Callable[[], Optional[str]]`（与既有 `error_response` 注入同构），kernel 只消费回调。
> 3. **接线面只 1/3，且这是取证结果不是偷懒**：三个宿主里只有 **knowledge-service 在中间件时刻拿得到断言主体**——它先 `add_middleware(SecurityGuardsMiddleware)` 后 `add_middleware(TenantHeaderMiddleware)`，而 Starlette **后添加者更外层** ⇒ 租户已绑定（已接线 `subject_provider=current_asserted_tenant`）。`agent_federation` 的 `mount_identity_middleware`（`api/server.py:143`）在 guards（`:148`）**之前**添加 ⇒ guards 更外层、执行时主体尚未绑定；`agent_server` 根本不用 `SecurityGuardsMiddleware`。⇒ 两处的限流桶**今日实为 IP 兜底**，属诚实中间态；把联邦的接线序对调会让身份 401 抢在 API-Key 401 之前（行为变更，无现有用例覆盖），列入 B7b-4 一并处理，不在本 PR 偷改。
> 4. **`subject_provider` 抛错不得把请求变成 500**：kernel 兜 `ValueError` 退 IP 并告警一次。因 `server_tenant_id()` 的 fail-fast 语义正是抛 `ValueError`（`agent_core/memory/_tenant_gate.py:21`），宿主若直接传它，限流桶这个辅助信息不该有杀伤主链路的能力（用例 `test_middleware_subject_provider_raising_falls_back_to_ip`）。
>
> **代价的实测新形状**（比初稿写得更具体）：旧实现下**同一把部署级密钥的所有客户端共用一个桶**，一个客户端打满配额会连带 429 同密钥的其他客户端；改为 IP 后各客户端独立（用例 `test_middleware_rate_limit_buckets_are_per_ip_not_per_credential` 锁住）。反面：**单客户端换 IP（拨号/代理/IPv6 前缀变化）即可重置配额**——旧实现下换 IP 无效（桶按密钥），新实现下有效。这是限流**强度**的实质下降，不属「无副作用重构」；缓解手段是已有的全局窗口 `_global`（`rate_limit_global`，默认 500/60s）与接入后的主体桶。【已拍板（2026-10-02）：**不恢复「每密钥配额」语义**，保持现状（断言主体优先 / IP 兜底），依靠已有全局窗口 + ks 已接入的主体桶】——若将来运维反馈确实需要，再按「服务端可验证的密钥 id（非凭据摘要）」另开子项，**不得**回到凭据派生值。
>
> **新增语义门禁（三层齐备的第三层）**：`test_only_session_identity_still_digests_credentials`（AST）——`guardrails/auth.py` 内调用 `fingerprint` 的函数集合必恰为 `{derive_thread_id}`。链② 拆后它从「两元素」变「单元素」，B7b-4 拆完链①后应改为 `== set()`（注释已写，“拆完就删用例”不是选项）。

### 4.3 链③：LLM 缓存键 ← 首次注入时分配的**不透明 slot id**（B7b-1 已实施，含一处方案自订正）
`get_llm_client` 的 `api_key` 不再进 `cache_key`：首次遇到某把凭据时分配进程内不透明 slot（`_SLOTS: dict[slot_id, api_key]`，同值幂等复用），`cache_key` 用 `slot_id`；`prov.build(api_key=api_key)` **仍直接用调用方传入的凭据**，不从 slot 表读回（读回会在超限重置窗口拿到 `None`，使真实 provider 误报「api_key 不能为空」）。⇒ 链③的 password 源不再流入任何摘要。

> **初稿写下的「代价」判断是错的，实施时被证伪**：原文写「缓存键不含密钥摘要 ⇒ 同 `(provider, model, base_url, …)` 但换了密钥的请求会命中同一客户端实例」。错因：把「键里没有摘要」等同于「键失去密钥区分度」。实际 slot 是**按凭据值幂等分配**的——换密钥必得新 slot ⇒ 必不命中旧客户端，区分度与原摘要方案**等价保留**（已用 `test_changed_api_key_does_not_hit_old_client` 固化，即 §7 验收 4；该用例由「记录一项退化」变成「证明无此退化」）。
> **真实代价是另一件事**：明文凭据驻留 `_SLOTS`。已兜住：`_MAX_SLOTS = 64` 上界，超限**整表重置并同步清客户端缓存**（否则 slot id 复用会让新密钥撞上旧密钥遗留的实例）；且这不是新增暴露面——客户端对象（`ChatOpenAI`）本就长期持有 `api_key` 明文，且正存放在 `_CLIENT_CACHE` 里（`providers.py:82-90` 实取）。
> 仍保留的缓解措施：`register_provider` 同名覆盖时主动 `clear_cache()`（旧 provider 的客户端不能靠「键不同」自然逸出）。
>
> **实施时自引入一条新告警（已修真修，不 dismiss）**：为便于排错把 `slot=%s` 加进了 `logger.debug` 实参，PR CI 的 CodeQL 随即报 **`py/clear-text-logging-sensitive-data` high**（`registry.py:156`，注解原文“`This expression logs sensitive data (password) as clear text`”）。机制：`api_key_slot` 由 `api_key`（password 分类源）经 `_slot_for_api_key` 数据流而来 ⇒ 进了日志 sink。教训：**「不透明」不等于「不可流」——切断一条摘要通路时，同一个派生值不得反手送到另一个 sink（日志）**，否则本批只是把凭据从汇 A 搬到汇 B。修法：日志回到只打 `provider/model/json_mode`（slot 对排错无价值，删它不损失任何信息），并新增 **AST 守门用例** `test_no_credential_value_reaches_logger_calls`（凭据及其派生名不得作为 `logger.*` 实参）；已实测该守门对修复前文件报 `(154,'api_key_slot')`、对修复后为空，即**守门能咬人**。闭环实取：推修复后 PR 的 `CodeQL` check 由 **fail → pass**，check-run `output.summary` 不再含 “New alerts”段（只剩分支告警链接）；该告警始终**只在 PR 面**（仓库 open 列表修前修后都只有 `#38`/`#39`，本规则的存量 `#43`/`#44` 早已 `fixed`）⇒ 主干未背新债。

### 4.4 已排除的三条「看起来能修」
- **改名躲启发式**（`secret`→中性词、`api_key`→`token_ref`）：分类纯由名字决定，改名即可让告警消失，但被摘要的仍是凭据 ⇒ 典型 gaming，**禁止**，并要求 §5 的门禁守住语义而非名字。
- **只删 `fingerprint` 不拆链**：初稿据错误结论提出（§1.3）。删除函数而把 `sha256(api_key)` 抄到调用方，告警跟着走；这是"以删除换绿灯"。
- **换 scrypt/pbkdf2**：能消警（§2 已核机制），但按错误前提付热路径延迟 + 会话全漂移，**不选**（与 `auth.py:19-22` 既有定调一致）。

### 4.5 `#39`：用**枚举**取代**复算**，从而删除 `legacy_thread_id`
`legacy_thread_id(api_key)` 的形参名使其成为 password 源，其值直接进 `hashlib.sha256(...)[:12]` ⇒ `#39` 只要函数存在就在。而它的唯一用途是「算出旧 thread_id 以定位旧数据」——旧 thread_id **本已存在于数据里**：`updated/`、`output/` 下的 `session_*` 目录名，以及 `SELECT DISTINCT thread_id FROM checkpoints WHERE thread_id LIKE 'user-%'`。⇒ 迁移改为**枚举现存标识 + 按 §8-Q1 选定的新主体重挂**，不再从密钥反算；函数与脚本的哈希依赖一并删除。
> 边界（不得夸大）：枚举法在「一把密钥 = 一个部署」的现状下等价成立（§3.4：同密钥共享单桶）。若某部署历史上有过多把密钥，枚举会把它们视作同一主体——列为**部署侧前置核实项**（命令见 §9）。

## 5. P6 / P6-2 门禁的同步调整（横切关注点三层齐备，缺一层即破窗）
- **P6**（`lint_architecture.py:185-221`）现语义 =「白名单外禁对密钥类标识裸用 hashlib」，白名单**恰只有 `guardrails/auth.py`**（`:187-189`）。两个问题必须一并处理：
  1. `fingerprint` 删除后白名单失去依据 ⇒ 白名单清空；
  2. **P6 现正则只抓 `hashlib.<algo>(` 同行共现**（`:185-186`），抓不到 `fingerprint(api_key)` 这类"走 kernel 但仍摘要凭据"的写法，也抓不到改名绕过。⇒ 反转后新增一条**语义不变量**：`derive_thread_id` / `legacy_thread_id` / `_hash_api_key` 三个"凭据→摘要"入口名不得再出现（白名单为空），并用反例单测证明（沿用 `_is_bare_secret_hash_line` 抽出判定的既有做法，见 `tests/governance/test_thread_identity_migration.py`）。
- **P6-2**（`:225-266`，白名单 `:233-236`）：`legacy_thread_id` 删除后**整条规则作废**，其用例 `tests/governance/test_thread_identity_migration.py::test_p6_2_*` 随函数一同退役，不得留悬空断言。
- 门禁是"防未来漂移"，不是"证明本批修好了"——本批的真相由 §7 的主干告警实取担保。
- **B7b-1 实施后的 P6 语义补记（待 B7b-5 一并处理）**：链③ slot 化后 `llm/registry.py` 已不再 import `fingerprint`，于是 `tests/governance/test_thread_identity_migration.py:67` 的用例 docstring「四处散点（kernel auth / llm registry / 两个 app 的 `resolve_thread_id`）必须已收敛」已**过时**（registry 不再属于“收敛到 fingerprint”的散点，而是根本不需要摘要）。该 docstring 随 P6 反转一同订正；断言本身（`check_bare_secret_hashing() == []`）不受影响，已实跑 exit 0。
- **新增候选门禁（待拍板，不在本批擅自扩面）**：日志 sink 侧目前没有仓级 lint（本批的 `py/clear-text-logging-sensitive-data` 回归靠 PR CodeQL 才看到，而非 `lint_architecture.py`）。可选做法：把上述 AST 判定从单模块测试上提为 P12（全仓扫 `logger.*` 实参中的凭据类名 + 白名单）。**代价**：AST 名匹配会漏「先赋值再记」的间接流，属不完整门禁 ⇒ 要么写清局限、要么不做，不得当成已具备全局门禁。

## 6. 分阶段实施（每阶段独立 PR，都可单独回滚）

| 阶段 | 内容 | 对 `#38` 的作用 | 部署前提 | 状态 |
|---|---|---|---|---|
| B7b-1 | 链③ slot 化 + 删 `_hash_api_key`（纯 kernel/registry，无身份依赖） | 去 1/3 链 | 无 | **已实施（2026-10-02，PR #45）**：上注已订正代价判断；另自引入并真修了 1 条 `py/clear-text-logging-sensitive-data`（见 §4.3 末段；PR 的 CodeQL check 已 fail → pass，且该告警未进主干）；用例 5 → 10 → 11（新增 5 + 改写 1 + 日志 AST 守门 1） |
| B7b-2 | 链② 限流桶去密钥 + 改 2 处用例契约 | 去 2/3 链 | 无 | **已实施并已合入（2026-10-02，PR #46 → merge `76589c4`）**：`resolve_client_key` 签名删 `headers`/`auth_enabled`⇒ 凭据类型层面进不来；`SecurityGuardsMiddleware` 新增 `subject_provider` 注入，ks 已接 `current_asserted_tenant`，联邦/agent_server 未接（取证原因见 §4.2 实施补记第 3 条，接线序对调归 B7b-4）。用例：改写 4 处旧契约 + 新增 AST 语义门禁 1 + kernel 新契约 3 + ks 中间件集成 3（详见 §4.2 补记）。**PR 面告警闭环已实取**：check-run `110690703578` → `conclusion=success`、`output.title` = “No new alerts in code changed by this pull request”、`output.summary` 只剩分支告警链接（无 “New alerts” 段）、annotations 空 ⇒ §7.2 要盯的「派生值改投另一个 sink」未发生（与 B7b-1 初版不同）。`ci`/`ha`/`assembly` 均 pass。**主干复验已 PASS**（合入后 `refs/heads/main` 实取，§7.7 逐链判据：链② 具名节点所在通路 1 → 0，`#39` 未受影响，`dismissed` 0 / 最大告警号 48 不增 / 合入后新建 0）⇒ `#38` 进入「只剩链①」的预期中间态。 |
| B7b-3 | ~~联邦 `_apply` 接入 user 断言~~ → **已移出本批关键路径**（Q1 定 (a) 租户级），随 A5 运行时身份接入另批推进 | 不再是前置 | — | 移出关键路径 |
| B7b-4 | 链① thread_id ← `server_tenant_id()`（按 Q2(c) 三态兜底；`resolve_thread_id` 2 处 + 5 个消费点）**+ 联邦 `subject_provider` 接线（需对调 identity/guards 添加序，含 401 优先级影响面，见 §4.2 补记第 3 条）** | **去最后一链 ⇒ `#38` 应闭合** | 需 §6 兼容窗口 | 未开工 |
| B7b-5 | 删 `fingerprint` / `legacy_thread_id` + 枚举式迁移脚本 + P6 反转/P6-2 作废 | 死代码清理；**`#39` 闭合** | 部署侧先跑枚举核实 | 未开工 |

**口径提醒（B7b-2 实测自纠）：“链数” ≠ “SARIF 通路数”**——本表“去 x/3 链”指的是**逻辑链**，不是扫描器报的通路条数。实测：`#38` 单个 sink 上 pre 面 4 条通路（链① 一家就被枚举为 `resolve_thread_id` 两形参 + default `None` + `derive_thread_id` 形参 = 4 个源节点，外加链② 1 条），拆掉整条链② 后 post 面**仍为 4 条**。⇒ **通路条数不能当验收指标**，逐 PR 的中间态判据见 §7.7。

**兼容窗口**：新 thread_id 生效后，旧 `user-<digest>` 数据按 §4.5 枚举重挂；窗口内旧目录**只读不删**（改名失败/碰撞时保留双侧，沿用 `migrate_thread_identity.py:69-70` 的「目标已存在拒绝覆盖」策略）。

**拍板后的路径修正**：Q1=(a) + Q2=(c) 共用了身份层**已在位**的 `server_tenant_id()` / `resolve_startup_tenant_mode()`（不像 `server_user_id()` 那样零消费者），因此 B7b-3 从关键路径移出，本批实际只需 B7b-1/2/4/5 四个 PR。

## 7. 验收标准（硬指标，全部可实跑，不接受"应该没问题"）
1. **主干口径**（严禁用 PR 绿代替主干绿）：合入后在 `ref=refs/heads/main` 实取 `#38`/`#39` = `state=fixed` 且 `fixed_at` 有值、`dismissed_at/dismissed_by/dismissal_reasons` 全 `None`；`state=dismissed` **恒为 0**。复用 `verify_main_b7d.py` 的判据骨架（含 fail-closed 的 [G] 段：主干 `ci` run 未见即判 PENDING）。
2. **无新建/位移重开**：`created_at > 合入时刻` 的新告警数为 0；同规则在 `auth.py` **或任何其它文件**重新出现即判**未修**（`#47` 位移重开是既有教训；本批尤其要盯“链②挪到别处继续 `sha256(api_key)`”）。本条不只看主干：`py/clear-text-logging-sensitive-data` 先以 **PR 面告警**出现（仓库 open 列表仍只有 #38/#39），若等合入后才在主干看到就晚了一步 ⇒ **每个 B7b 子 PR 必查 `gh pr checks` + check-run annotations**（取法：`gh api repos/…/check-runs/<id>` 读 `output.summary`，`…/annotations` 读具体行）。
3. **行为回归**：会话防劫持语义仍在（客户端不可指定他人会话）——新用例断言「鉴权启用 + 伪造 `session_id` 时返回主体派生值」，替换现有基于摘要的断言。
4. **缓存正确性**：新增用例覆盖「密钥变更 → slot 更替 → 不命中旧客户端」（§4.3 取舍的守门用例）。
5. **门禁**：`scripts/lint_architecture.py` exit 0（P6 反转后白名单为空仍全仓零违规 + 反例单测红）；`check_doc_sync.py` 0 警告；`make test` 9 session 对齐 CI；`eval/run_eval.py --fail-below 0.8` 保持 100%。
6. **账面同步**：`packages/agent-core/README.md:12/:42`（`derive_thread_id`、`AGENT_PLATFORM_SECURITY_PEPPER` 说明）、`ARCHITECTURE.md` 模块清单、`docs/TODO.md` §8、`CHANGELOG.md`，以及 Batch 7 方案 §4 的定调（该文档现仍写「`fingerprint` 行→误报」，且 §4.1 的「只改调用方不够」推论需按本文件 §1.3 订正）。
7. **逐 PR 中间态判据（B7b-2 实测定型，适用于链①未拆完的所有子 PR）**：拆哪条链，就断言「**该链特有的具名节点集合**在 `#38` 的全部 codeFlows 上从 >0 变 0」，而**不是**断言通路数下降（§6 口径提醒）。具名节点清单：链① `def derive_thread_id` / `fingerprint(api_key`；链② `x-api-key` / `extract_api_key_from_headers` / `key:{fingerprint`；链③ `_hash_api_key` / `cache_key`。**必双向断言**：同时要求 pre 面该集合 > 0，否则判据本身不咬人（拿不到“真的拆了”的证据）。复验脚本：`.codeartsdoer/temp/verify_main_b7b2.py`（含取法与全部判据，可改 SHA 给 B7b-4 复用）。

## 8. 拍板结果（2026-10-01 三项均按推荐值接受；2026-10-02 补一项 Q4）

| # | 问题 | 选项与代价（保留原始权衡记录） | **决定** |
|---|---|---|---|
| **Q1** | thread_id 主体粒度 | (a) **租户级**：行为最接近今天（今天≈单桶），会话不分裂，`server_tenant_id()` 已有软兜底；隔离度弱于 (b)。(b) **用户级**：隔离最好，但**今天共用一把 key 的客户端会分裂成多个会话**，历史数据归属需人工判定。(c) **有 user 用 user、否则 tenant**：兼顾，但同一部署内会话归属随部署配置漂移（运维易困惑） | **(a) 租户级**起步（B7b-4 不改变现有会话可见行为），(b) 随 A5 运行时身份接入另批推进 |
| **Q2** | 无主体断言时的兜底（约束 A/B 的现实） | (a) 退回 `DEV_THREAD_ID`（开发模式现状，`auth.py:48`）——生产若忘配身份会**静默共用单一会话**（fail-open，危险）。(b) `raise`（fail-fast）——生产安全但破坏「零依赖冒烟 `DATABASE_URL= uvicorn agent_server.main:app`」（AGENTS.md 承诺的运行方式）。(c) 复用身份层现有三态：`jwt`/`single` 正常派生，`insecure` 下按 `DEPLOY_ENFORCE_IDENTITY` 决定拒答 or DEV 兜底，并**启动告警一次**（与 `require_identity_startup_guard` 同构） | **(c)**：与 ADR-0007 启动守卫同构，既不破坏冒烟，又不静默 fail-open |
| **Q3** | 链③（LLM provider 密钥）是否纳入本批 | 不纳入则 `#38` 剩一源、**不闭合**（§1.2 结论）；纳入则 §4.3 的缓存命中取舍必须接受 | **纳入**，并补 §7 验收用例 4 作为守门 |
| **Q4**（2026-10-02，B7b-2 后提） | 是否恢复「每密钥配额」语义（链② 拆除后的代价面） | 恢复则需服务端可验证的密钥 id（新能力，要 key→主体映射）；不恢复则限流强度下降（换 IP 可重置配额） | **不恢复，保持现状**（断言主体优先 / IP 兜底 + 已有全局窗口）。将来若运维确需，另开子项且**不得**回到凭据派生值 |

⇒ 开工顺序按 §6 表（B7b-1 先做链③：纯 kernel、无身份依赖、可单独回滚）。Q1 选 (a) 使 **B7b-3（联邦接入 user）不再是 B7b-4 的阻塞项**，可从关键路径移出、并入 A5 那一批；本批只需 `server_tenant_id()` 一条路径可用（它已在位，不像 `server_user_id()` 那样零消费者）。

## 9. 证据与复现命令

```bash
# 规则模型源码（落盘 .codeartsdoer/temp/，temp 不入库，故留命令）
gh api repos/github/codeql/contents/python/ql/src/Security/CWE-327/WeakSensitiveDataHashing.ql -H "Accept: application/vnd.github.raw"
gh api repos/github/codeql/contents/python/ql/lib/semmle/python/security/dataflow/WeakSensitiveDataHashingQuery.qll -H "Accept: application/vnd.github.raw"
gh api repos/github/codeql/contents/python/ql/lib/semmle/python/security/dataflow/WeakSensitiveDataHashingCustomizations.qll -H "Accept: application/vnd.github.raw"
gh api repos/github/codeql/contents/python/ql/lib/semmle/python/dataflow/new/SensitiveDataSources.qll -H "Accept: application/vnd.github.raw"
gh api repos/github/codeql/contents/shared/concepts/codeql/concepts/internal/SensitiveDataHeuristics.qll -H "Accept: application/vnd.github.raw"
gh api repos/github/codeql/contents/shared/concepts/codeql/concepts/internal/CryptoAlgorithmNames.qll -H "Accept: application/vnd.github.raw"   # §1.1 的决定性文件

# 告警三态与主干复验
python .codeartsdoer/temp/verify_main_b7d.py --once

# 通路（codeFlows）明细——alerts REST 不给，必须从单条 analysis 取内嵌 SARIF（B7b-2 实测定型）
#   同一 commit 有 python / actions 两条 analysis，只取 results_count>0 的那条
gh api "repos/Light-Towers/agent-platform/code-scanning/analyses?tool=CodeQL&per_page=40"
gh api repos/Light-Towers/agent-platform/code-scanning/analyses/<ID> -H "Accept: application/sarif+json"
#   ↑ 带该 Accept 头时**返回体本身就是 SARIF**（顶层 runs[]）；不带则只给 644B 元数据（无 sarif 字段）
#   SARIF 行号相对该 analysis 的 commit，跳 commit 比较必须 `git show <sha>:<path>` 回源

# 部署侧前置核实（B7b-5 开工前必须实跑，确认 §4.5 枚举假设成立）
ls applications/agent_federation/updated/ applications/agent_federation/output/
psql "$DATABASE_URL" -c "SELECT DISTINCT thread_id FROM checkpoints WHERE thread_id LIKE 'user-%';"
```

> **该取证至今未跑通（2026-10-02 登记）**：部署侧 `root@192.168.100.126` 的 TCP 22 可达，但连接在 **banner 交换前**被关闭（`kex_exchange_identification: Connection closed by remote host`）—— 发生在任何认证之前，与本地密钥/`authorized_keys` 无关，属服务端侧限制（fail2ban / `hosts.deny` / `MaxStartups` 一类）；跨约 25 分钟含 220s 与 8min 冷却共 4 次同签名后停止硬连。本机也无可用的替代路径：主 `docker-compose.yml` 不发布 5432，HA compose 只绑 `127.0.0.1:${HA_PG_PORT:-5433}`，且本机无 docker 无 `.env`。⇒ **B7b-4 开工前必须拿到这两条命令的真实输出**（存量 `user-*` 为零 ⇒ 无需迁移窗口；非零 ⇒ 按 §4.5 枚举重挂并保留只读兼容窗口），不得以推定代替数据。

> **实施后记（2026-10-02，B7b-4/B7b-5 已开工并落地）**：上述「开工前必须实跑」的前置**至今仍未拿到输出**（本批开工前再试 1 次，同签名 `Connection closed by 192.168.100.126 port 22`；本机亦无 `kubectl` / `~/.kube/config`）。**本批的缓解不是补到数据，而是换策略**：把迁移改为枚举式，其正确性不依赖存量数量（存量为零 ⇒ 脚本空转），因此不再拿它当开工闸门。仍成立的未取证项（**不得表述为「迁移已验证」**）：① 存量是否非零；② 该部署历史上是否存在过多个密钥（枚举法会把同一部署的历史多把密钥视作同一主体）。两项已转为运维交接项入 `docs/TODO.md` §8（含 dry-run 先行与「兼容窗口内旧目录只读不删」）。另：本方案正文里的行号（如 `auth.py:92`/`:117`）已因后续加 docstring 位移，实施时一律重 grep 定位；新格式定为 `tenant-<id>`（而非本方案原写的 `user-` 保留前缀），理由与代价见 `CHANGELOG.md` 本批段。

**本方案的取证记录**（否定式/数量断言均逐条 grep 实取）：`derive_thread_id` 生产调用点 = **2**；`server_user_id` 生产消费者 = **0**；`.github/codeql/` 配置文件 = **0** 个；`*.sql` 中 thread_id 列 = **0** 处；`updated/` 目录当前为空。
