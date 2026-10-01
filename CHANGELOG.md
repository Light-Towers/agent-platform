# Changelog

本仓库为 uv workspace monorepo。**唯一受支持的安装/运行入口是根 `uv.lock` + `uv sync`**，子包不再维护独立 `uv.lock`（见 v2 修复 #14）。

## B7d：合流后主干复验发现新告警 #48，按三层齐备真修（2026-10-01，方案 §7）

> 方案：`docs/plans/plan-codeql-batch7-no-dismiss-real-fixes-2026-10-01.md` §7。触发：v3 合流（PR #41）合入后回主干复验，硬指标未达成——open 不是 2 而是 3。

- **事实**：新增 **#48 `actions/missing-workflow-permissions`** @ `.github/workflows/ha-assembly.yml:30-56`，`created_at=2026-10-01T12:55:08Z`（PR CI 期间）、`updated_at=13:01:20Z`（主干重扫复现）。引入源：`70f2b83` 经 merge 第二父进来，即 **v3 侧提交新增该 workflow**（`git diff --name-status b67546d 889d417 -- .github/workflows/` = `A`）。#38/#39 无位移（仍 `auth.py:92` col=47 / `:117`）。
- **不采的捷径**：只给被点名的 job 补一行权限（散点式）；dismiss；在 default setup 里按路径排除 `actions/*` 查询；把权限写成 `write-all` 求个「不报」。
- **单一实现（对齐既有约定，不新发明）**：审计 4 个根 workflow，`agent-platform-ci.yml`/`eval-llm.yml`/`ha.yml` 均已有顶层 `permissions: contents: read`，**`ha-assembly.yml` 是唯一漏接者**（顶层与 job 级均无）。已按同形状补齐；`contents: read` 是它实际所需最小面（只用 `actions/checkout` + `docker compose` + `curl`，不上传 artifact、不写仓库）。
- **强制门禁（新增 P11）**：`scripts/lint_architecture.py` 扫根 `.github/workflows/*.yml|yaml`，**缺顶层 `permissions:` 块**、取值为 **`write-all`**、或为空块即 exit 1；自研 fail-closed（workflow 目录不存在也不得静默放行）。只认顶层块的理由：顶层声明由构造保证覆盖全部 job，job 级声明易漏。
- **治理用例**：`tests/governance/test_workflow_permissions_governance.py` 17 条——正反例（缺块/仅 job 级/`write-all`/空块/注释伪装）、当前树零违规、临时根探针验扫描面、目录缺失 fail-closed，及一条**回归锁**：把任一真实 workflow 的顶层 `permissions` 块剥掉必须立刻判违规（排除「门禁只是恰好没命中」的假通过）。
- **登记位**：`ARCHITECTURE.md` 新增 **§4.1 强制门禁登记表**（P2/P4-2/P5/P6+P6-2/P7/P8/P9/P10/P11 × 锁住的告警形状 × 治理用例）。这是补合流方案 §8-3 的欠账——当时承诺「在 `ARCHITECTURE.md` 登记」但只落在 CHANGELOG，P9/P10 一直无登记位。
- **本地验证**：`lint_architecture` exit 0（9 组：P4-2/P2/P5/P6+P6-2/P7/P8/P9/P10/P11）· 新用例 17 passed · `tests/governance` 全 session **242 passed** · `ruff check` 无告警。门禁有效性反喂取证：将 `git show HEAD:` 的**修复前原文**送进 P11 → 判「缺顶层 permissions 块」，修复后同一函数 → `None`。
- **账面自纠（顺带查到，与本告警无因果）**：`plan-v3-identity-merge` §9.2 与 PR #41 描述均写着「仓内无 `uv lock --check` 门禁」——**错**：`make ci` 末行就是 `uv lock --check`（Makefile:71），而 CI 直接复用 `make ci`（`agent-platform-ci.yml:65`）。「不破 CI」的结论仍成立，但依据换成实证：本机 `uv lock --check` exit 0，且 PR #41 的 `ci` ×2 job（含 `--check`）已 pass。残留风险已登记：CI 的 uv 版本由 `setup-uv@v7` 决定且不钉，将来两端 marker 规范化不一致时 `--check` 可报「lock 已过期」而红；根治是在 workflow 钉 uv 版本（独立决策，未在本批做）。教训：**否定式断言（“仓内无 X”）必须 grep 过才能写**。

## v3 身份层合流 main（B7b principal_id 化的前置）（2026-10-01，PR #41 已合入 `a660e76`）

> 方案：`docs/plans/plan-v3-identity-merge-2026-10-01.md`（§9 为执行记录）。触发：用户在 B7b 落地上拍板「先合流 v3 身份层，再做 principal_id 化」——`#38`/`#39` 的病根（单一静态 `API_KEY`、无 key→主体映射）与 v3 上已 Accepted 的 ADR-0007 同一条；直接在 main 再造 principal 注册表就会形成**第三套身份机制**，违反「横切关注点单一实现」。

- **合流粒度**：`git merge origin/v3` 一次全量（v3 ahead 47 / main ahead 49，merge-base `2a5e633`），**不 cherry-pick、不用 `-X ours/theirs` 压冲突**；47 个 commit 的作者与关联完整保留。
- **带入的内容**（main 此前全无）：`agent_runtime/identity.py`（RS256 签/验 + 网关→子服务 HMAC 内部头 + JWKS 轮转 + 启动守卫）、`identity_middleware.py`（纯 ASGI）、联邦 `api/identity_bridge.py`（`X-Tenant-JWT`）、ks `utils/tenant_identity.py`、内核 `memory/_tenant_gate.py`、ADR-0006/0007、migration `006`–`010`、5 条 governance 红线测试与 HA 租户隔离用例。
- **五处冲突的处置**：`lint_architecture.py` 两侧门禁**全保留**，v3 两条续编为 **P9（禁散点 tool 埋点）/ P10（禁 `from tools.*` 直引绕过 `get_tool()`）**；`agent-runtime/pyproject.toml` 取并集（新 `identity = ["PyJWT[crypto]>=2.9"]` extra）；`CHANGELOG.md` 两条时间线分段并存（append-only，不改写不重排）；`dep-security-accepted-risks` add/add **以 main 为基底**（它是含 09-30 证伪的演进后超集）并并回 v3 独有的一条 `uv tree -i` 排查手法；`uv.lock` 经 `uv lock` 重生成（未手改）。
- **合流新暴露并已真修的第 6 处（非 dismiss、非放宽门禁）**：`check_doc_sync.py` 报 `ARCHITECTURE.md` 两条**悬空引用**（`docs/adr/0005`、`docs/plans/plan-memory-hardening-2026-09-27.md`）——两文件在 `main`/`v3` 均不存在（v3 自身早就不一致），只存在于 `feat/isolation-hardening`@`d4b6faa`。导入其**「提案」版**并逐文件加来源标注：该分支后续 `ff68aee` 声称「T0 已落地」，但主干 `git grep -l -e EpisodicStoreProtocol -e supports_episodic` **0 命中**、`agent_core/memory/` 无 `execution.py`，故**不采信该修订**；真正随合流落地的是 T1（`010_episodic_tenant` + HA 用例）。
- **运行侧（已在 `.env.example` 登记 12 项）**：`DEPLOY_ENFORCE_IDENTITY` **默认 false** ⇒ 零依赖冒烟不受影响（实测：默认档 `agent_server.main:app` 构造成功、中间件栈含 `IdentityMiddleware`；置 true 且无公钥无 `SINGLE_TENANT` → `RuntimeError` 拒启动，开关不是摆设）；本次**不**把默认值改成 fail-closed（独立决策）。
- **新登记技术债（`ARCHITECTURE.md` §2.3/§5）**：`IdentityMiddleware` 仅覆盖 2/6 应用（agent_server + federation 无条件挂载；ks 走自有 `TenantHeaderMiddleware`；exhibition/kefu/nl2sql 入口 grep **0 命中**）——`TENANT_JWT_ENFORCE` 硬切换前必须先补齐装配层 + 新增 lint 不变量，不得靠「每个 app 记得调一次」。
- **本地验证（全绿）**：`ruff` 无告警 · `lint_architecture` exit 0（P4-2/P2/P5/P6+P6-2/P7/P8/P9/P10 全在位）· `check_doc_sync` exit 0 · 9 个 pytest session：根 839 passed/5 skipped、agent-runtime 606（含 27 条 identity）、governance 225、agent-core 300/5、agent_server 44、联邦 163、ks 238/13、shared-schemas 28、kefu 43、exhibition 347/1、nl2sql 18；`tests/ha` 1 passed/26 skipped（本机无 PG，skip 属设计意图，真 PG 结果交 CI）。`uv lock` 除 identity 条目外还归一化了约 30 行 environment marker（本机 uv 0.11.21 与 lock 原生成版差异，无包名/版本变动，已实查确认 CI 不走 `--frozen`）。
- **验收硬指标（实跑结果：未达成，已转入 B7d 真修）**：PR #41 自身 checks **全 pass**（`Analyze (actions)`/`Analyze (python)`/`CodeQL`/`assembly` ×2/`ci` ×2/`ha` ×2），其中 `ha` job 在真实 PostgreSQL 16.15 上 **27 passed in 8.07s**（覆盖本机 26 条 skip，kill -9 双进程接管真跑）——此前唯一未知项已坐实。但合入（13:00:43Z）后主干 `refs/heads/main` 复验为 **open 3 / fixed 43 / dismissed 0**：多出的 **#48 由 v3 侧新增的 workflow 带入**，即「合流未新增任何告警」不成立 → 按本批约束真修，见顶部 **B7d** 节。

## Batch 7c：#47 按官方编码形状重写 `resolve_within`（2026-10-01，分支 `fix/codeql-batch7c-path-shape`，PR #39 已合入 `bb46dd3`）

> 接 Batch 7a：主干重扫发现 #42 只是**位移重开**为 #47（同一语句）。方案：`docs/plans/plan-codeql-batch7-no-dismiss-real-fixes-2026-10-01.md` §3.4。

- **机制取证（先实测再动手：不凭记忆，直接拉 `github/codeql` 源码）**：`py/path-injection` 是**带状态**污点追踪（`NotNormalized` → `NormalizedUnchecked`），查询注释原话 “Such checks are ineffective in the `NotNormalized` state”。被识别的规范化**只有** `os.path.normpath`/`abspath`/`realpath`；被识别的 safe-access 守卫**只有** `str.startswith`；而 `Path.resolve()` 不是规范化、它是 `FileSystemAccess` 的 sink。⇒ Batch 6 的「结构不可消除」与 Batch 7a 的「已推翻 Batch 6」两头都错：真因是我们从未走官方编码的 **规范化→前缀守卫→才接触文件系统** 形状，`is_relative_to` 检测器根本不认。
- **修法**：`resolve_within` 改为 `os.path.normpath(os.path.join(root, raw))` 词法定形 → `startswith(root_str)` 且带**分隔符边界**（补上 naive startswith 会误放行 `/data/root_evil` 的真漏洞）→ 才 `Path(norm).resolve()` → 保留解析后复检（挡软链逃逸）。POSIX 反斜杠二次解释改为**纯词法**否决，不再第二次触碰文件系统（顺带消掉同源的潜在 sink）。
- **接受集不变是差分实测出来的，不是推演**：本机用 `posixpath` + `PurePosixPath` 模拟 POSIX 宿主，42 个入参对跑旧/新裁决 → **差异 0**。它当场推翻了我自己先写下的「lone `\` 入参改为拒绝」断言（`posixpath.join` 会自动插入分隔符，两版均放行），该用例已改正并入库。唯一真收紧在 **Windows 宿主的大小写变体绝对入参**（旧：`is_relative_to` 走 `normcase` 不区分大小写→放行；新：`startswith` 区分→拒绝），方向为变严，已用 `skipif(!win32)` 用例固定。
- 新增 6 条回归（base 自身放行/兄弟前缀被拒/`..` 定形后不进 `resolve`/反斜杠否决不新增 `resolve` 调用/lone-`\` 仍放行/Windows 大小写变体拒绝）；本目录 49 passed / 5 skipped（Windows 宿主）。
- **主干重扫验收通过（本批的终态判定）**：PR #39 全 checks pass（含 `CodeQL`，推送前另跑 L3 深度审查 findings 0），合入 `bb46dd3`@11:42:39Z；`refs/heads/main` 的 default-setup 分析（`Analyze (python)` success）于 11:44:14Z 将 **#47 置为 `state=fixed` 且 `dismissed_at=None`（自动闭合）**，且全仓告警最大号仍为 #47、合入后**无任何新建告警** —— 即 **#47 真消失，不是再一次位移重开**。`refs/heads/main` 总账：45 条 CodeQL 告警，`fixed` 43 / `open` 2，**open 仅剩 #38 / #39**（待 B7b principal_id 化）；43/43 闭合全为自动，**全仓零人工 dismiss**。

## Batch 7a：取消 dismiss 通道，剩余告警真修（2026-10-01，分支 `fix/codeql-batch7-real-fixes`，PR #38）

> 触发：用户明确「不要用 dismiss 这种简单的处理方式」。方案：`docs/plans/plan-codeql-batch7-no-dismiss-real-fixes-2026-10-01.md`。

- **`#34`（`gateway/gray.py` 灰度分桶）MD5 → SHA-256**：官方 query help 对非口令场景的直接建议即 SHA-2，且 `user_id` 属可识别信息。影响面实测：`GRAY_PCT` 默认 `0`、`is_in_gray` 在产品代码里**无调用点**、分桶不持久化 → 人群重排无生产影响。
- **`#43`/`#44`（`guardrails/fs.py` 拒绝日志）契约变更：不落任何路径文本**，只留原因 + 数值型结构摘要（`len`/`fragments`/`absolute`）。**演进过程值得记**：首版只去掉 `base`/`resolved`、保留 `input=%r`，PR #38 的 `CodeQL` 检查仍报 2 new alerts（high，注解 `fs.py:99`/`:110`）⇒ 消除法证明被判 secret 的是**入参本身**（路径含凭证派生的 `session_user-<HMAC(api_key)>` 目录名）——**这不是误报**。官方口径仅“Sensitive data should not be logged”，无 masking/哈希豁免。Batch 3 定的「留痕含原文」因此作废，排障改走接入层访问日志或本地复跑；`api/server.py` 依赖旧语义的注释同步修正。
- **`#42`（`resolve_within`）在 `resolve()` 之前加纯词法 containment 守卫**：不再对未验证的越界输入做文件系统解析，且不放宽接受集（`a/../b` 词法判真，符号链接逃逸仍由解析后复检拒掉）。**主干重扫实测：本动作未消除告警** —— #42 旧号 `state=fixed`，但同一语句（`resolved = candidate.resolve()`）在位移后的 `fs.py:187` 重开为 **#47**；因此当时写的「以代码重构推翻 Batch 6『结构不可消除』」**证据不成立，已撤回**（守卫前置作为纵深改进保留，真修见顶部 Batch 7c）。
- **新增 4 条回归**：日志不含部署绝对路径×2、越界输入不进 `resolve`、软链逃逸仍拒（其中两条断言方向随契约修正，新断言比旧的多两项，非收窄凑绿）。
- **本地验证**：`lint_architecture.py` exit 0、`check_doc_sync.py` 0 警告；分 session agent-core 281 passed/3 skipped、根 `tests` 500 passed/17 skipped、联邦 152 passed；`ruff` 无告警。本机无 CodeQL CLI，告警闭合以 PR 检查与主干重扫为准。
- **不以 dismiss 收尾**：`#38`/`#39` 属「把 API Key 摘要成用户标识」的模式问题（取证：`verify_api_key` 走 `secrets.compare_digest` 明文比较，派生值从不参与验证，所以「用于口令哈希」的判定不成立；但「会话标识可由凭证推导」的耦合是真的），需 principal_id 化的架构决策，本批不动代码，三条出路已列在方案 §4 待拍板。

## Batch 6 验收：模型包生效，主干 open 9 → 6（2026-10-01，分支 `docs/codeql-batch6-acceptance`）

> 纯文档（不改产品代码）。PR #36 合入 `main` = `0bc5175` @09:19:03Z，默认分支重扫 09:20:29Z（CodeQL 2.27.1）。

- **闭合 3 条，均为 `state=fixed` 且 `dismissed_at=None`（自动闭合，非人工）**：`#23`（`agent_federation/api/server.py:264` `FileResponse(abs_path)`，barrier 生效）、`#40`（`fs.py:119`）、`#41`（`fs.py:134`）（后两条靠 `barrierGuardModel`）。`#23` 闭合同时反证仓内模型包**确实被 default setup 自动加载**（上一节据此推翻的选型前提得到实测支持）。
- **`#42` 仍 open，且经分析为结构不可消除**：`resolve_within` 必然是 `candidate.resolve()`（`:162`）→ `_ensure_within`（`:167`），**不先 resolve 就无从判断越界**，sink 永远在守卫之前，所以 guard 建模无法覆盖。唯一能“消掉”它的做法是把 `Path.resolve` 返回值全局声明为 barrier，而 `resolve()` 本身不做任何净化、且会屏蔽全仓其他真实路径注入——**否决，转人工 dismiss**。这条边界写进方案 §9.1。**（订正：该判定已于 Batch 7c 推翻——真正的原因是 `Path.resolve()` 不被识别为规范化，必须先 `os.path.normpath` 再用 `str.startswith` 守卫；#42 后来位移重开为 #47 并在 7c 真修。）
- **本会话累计账面**：`refs/heads/main` open 21 → 6。剩下 6 条全部是「代码无需修、只需面板 dismiss 附证据」：`#34`（灰度分桶真误报）、`#38`/`#39`（HMAC/sha256 形状属实不可消除）、`#43`/`#44`（不在可建模 sink kind 清单）、`#42`（上述结构边界）。**即已不存在应当改产品代码而未改的 CodeQL 告警。**
- **仍未做的验收项**：模型包非空转自证（删 barrier 行→重扫必复报 `#23`）。现有旁证（加包前 open / 加包后 fixed，代码未动）不等于反证已做，已记在方案 §6-2。

## Batch 6 执行：仓内 CodeQL 模型包把 kernel guardrails 声明为 path-injection barrier（2026-10-01，分支 `fix/codeql-batch6-model-pack`）

> 零产品代码变更，仅新增 2 个 YAML。**同时推翻本文件下一节的一个选型前提**（已就地标记）。

- **产物**：`.github/codeql/extensions/agent-platform-python/codeql-pack.yml`（`library: true` + 无 dependencies + `extensionTargets: codeql/python-all: "*"` + `dataExtensions`）与 `models/agent_core.guardrails.fs.model.yml`：`barrierModel` 将 `safe_filename`/`safe_join`/`resolve_within` 的返回值声明为 `path-injection` barrier（每个 helper 写两种 `type` 形态匹配不同导入形式），`barrierGuardModel` 将 `Path.is_relative_to`（接收者用 `Argument[this]`）声明为守卫。
- **选型前提纠正**：原计划「必须停用 default setup 并切 advanced setup」错误——官方文档明说仓级模型包放 `.github/codeql/extensions/` **会被自动检测并使用**，两种配置模式均识别。“已发布”限制只适用组织级扩展。结果：**零基础设施变更、零扫描黑窗、不多花 Actions 分钟**，避免了一次多余且有风险的面板切换。
- **写法修正**：原方案写的「声明为 `sanitizer`」与「`PathTraversalError` 声明为 taint-blocking 异常」在 Python 数据扩展中**没有对应谓词**（官方只有 `sourceModel`/`sinkModel`/`summaryModel`/`barrierModel`/`barrierGuardModel`/`typeModel`），改为 barrier + guard 两种可表达的形式。
- **边界说明**：`py/clear-text-logging-sensitive-data`（`#43`/`#44`）**不在可自定义的 sink kind 清单内**（官方列 9 种），因此无 barrier 可写，只能人工 dismiss——原「两个终态二选一」由此变成技术上的单选项。
- **验收分层**：本机已验——两个 YAML `safe_load` 通过、列数与官方谓词签名一致、pack 无依赖、`check_doc_sync.py` 0 警告、`lint_architecture.py` exit 0（P7 未放宽）；**未验**——包是否真被加载、`#23`/`#40`~`#42` 是否闭合（本机无 CodeQL CLI，以 PR 的 CodeQL 作业不报红 + 合入后主干重扫差集为准）。

## CodeQL 合入后默认分支重扫对账：19/21 闭合，另暴露 5 条 kernel 模型缺失告警（2026-10-01，分支 `docs/codeql-post-merge-rescan`）

> 本分支**纯文档**（不改产品代码）。触发：PR #33（`8b6d416`）与 PR #34（`4f8ae4c`）合入 `main` 后自动重扫的结果核对。

- **闭合情况**：`refs/heads/main` open 21 → 9，其中原 21 条有 **19 条 `state=fixed`**（无 dismiss）——C 类 `py/stack-trace-exposure` ×4、D 类 `actions/missing-workflow-permissions` ×3、E 类 `py/incomplete-url-substring-sanitization` ×1 全清，A 类 8 条中 7 条清，B 类 4 个 api-key 站点全清。PR #34 自身 `CodeQL` 检查 pass（doc-sync 改动零告警）。
- **新暴露 5 条（本条重点）**：`#40`/`#41`/`#42` `py/path-injection` 落在新建 kernel `agent_core/guardrails/fs.py` 内部的 `Path(...).resolve()` 调用点（`:119`/`:134`/`:162`），`#43`/`#44` 为新规则类 `py/clear-text-logging-sensitive-data`（同文件 `:93`/`:103` 两处拒绝日志回带入参原文）；另 `#23`（`FileResponse(abs_path)`）未闭合。**根因同一**：CodeQL 内建模型不认识 `safe_join`/`resolve_within`/`safe_filename` 为 sanitizer，所以污点既能追到调用点 sink，也能追进 sanitizer 内部把其 `resolve()` 当 sink 报。
- **推理越界的纠正**：上游方案曾以「PR 重扫无新增 A/C/E/D 告警」作为反向证据，判定「无需为此补 data-extension」——**不成立**。`refs/pull/33/head` 与 `refs/heads/main` 是两套告警集合，跨过程的 kernel 内部 sink 只在默认分支模式下暴露。教训：**证据的作用域不能超出产生它的分析模式**；所以下结论必须回到最终作用域（默认分支）复验。已在原文处加纠正标记。
- **预测命中**：`#38`/`#39`（kernel `guardrails/auth.py:92`/`:117`）如预期从 PR 作用域迁入 `refs/heads/main` 并重新开号——印证 dismiss 是按 ref 生效、不能只在 PR 上做一次。
- **后续方案（已执行，见上一节）**：`docs/plans/plan-codeql-batch6-kernel-sanitizer-models-2026-10-01.md`。选型实查：本仓为 PUBLIC；CodeQL 跑的是 default setup（仓内无 codeql workflow/config），而 ~~default setup 只接受**已发布**的模型包——所以仓内本地 `.model.yml` 必须配 advanced setup 才生效~~ **【此句已于执行时被推翻：仓级包放 `.github/codeql/extensions/` 即自动加载，该限制只适用组织级扩展，见上一节】**。“已切 advanced setup + 仓内模型包”的推荐收敛为“只加仓内模型包”；已否决的「在调用点内联 `is_relative_to` 复检」（与 P7-1 不变量正面冲突且消不掉 kernel 内部告警）维持否决。
- **仍待人工**：`#34`（`gateway/gray.py:40` 灰度分桶，真误报）与 `#38`/`#39` 的 dismiss 需 `security_events` scope（实测本机令牌仍不含）；部署需配 `AGENT_PLATFORM_SECURITY_PEPPER` 并先 dry-run `scripts/migrate_thread_identity.py`。

## doc-sync 门禁补齐「文件引用」校验 + 修复存量路径漂移（2026-10-01，分支 `fix/doc-sync-file-ref-gate`）

> 方案：`docs/plans/plan-doc-sync-file-ref-gate-2026-10-01.md`。背景：PR #33（CodeQL 收敛）收尾排查时发现 `ARCHITECTURE.md` 一条文件引用指向不存在的路径而 CI 全绿；与 CodeQL 主题无关，故拆独立分支。

- **① 存量漂移修复**：`ARCHITECTURE.md` 「历史命名残留」条目中 `docs/architecture-boundary-app-vs-agent-federation.md` → `docs/architecture/architecture-boundary-app-vs-agent-federation.md`（原路径不存在；`origin/main` 同样如此）。
- **② 强制门禁**：`scripts/check_doc_sync.py` 的 `check_architecture_paths()` 原先只对以 `/` 结尾的**目录**引用调存在性校验，带扩展名的文件引用直接落空；`check_agents_md_paths()` 只匹配表格首列。现新增 `is_doc_file_ref()` 谓词 + `check_doc_file_refs()`（由 `main()` 统一装配），对 `AGENTS.md` / `ARCHITECTURE.md` / `README.md` 三份现状文档逐行取反引号片段，命中「顶层前缀 + 已知扩展名 + 无通配/占位/空格」即复用既有 `check_path_exists()` 报错。判定面刻意保守：宁漏报不误报（误报会把门禁变成噪音并诱导关掉它）。
- **CHANGELOG 故意不校**：一次性探测 4 份顶层文档得 117 个文件引用、25 个不存在，其中 24 个在 `CHANGELOG.md`（历史条目所指文件后来被移动/重命名）。append-only 历史快照按既有约定不回改，纳入校验即上线一片红；故范围排除，并在单测里钉住该排除（防后人“顺手”加回来）。
- **防静默失效**：新增 `tests/governance/test_doc_sync_file_refs.py`（17 例）——真实树 0 违规 + 人为插入不存在的引用必报错（非空洞性）+ 通配/占位/模块路径/外链/目录引用不误报 + CHANGELOG 排除断言。门禁谓词若被改坏，检测面会归零而 CI 仍绿，本套用例即拦这一手。
- **实测证据**：修前 `uv run python scripts/check_doc_sync.py` 退出码 1 且恰好报出上述 1 处（零误报）；修后退出码 0、0 警告。`uv run pytest tests/governance -q` 115 passed · `ruff check` 通过 · `scripts/lint_architecture.py` 全项通过。
- **附带纠正（不属本分支代码改动）**：曾误登记「根 `AGENTS.md` 引用了不存在的 `docs/operations/testing-playbook.md`」——实测该引用只在 `feat/isolation-hardening` 的 AGENTS.md（该分支持有该文件），主干命中 0，属把会话上下文缓存的另一分支文件当成本分支事实。纠正记录在 PR #33 分支 `4acd366`。

## CodeQL 告警收口 Batch 1~5：workflow 最小权限 + 密钥指纹 DUP-1 + 路径注入 + 堆栈回显 三层收敛（2026-10-01）

> 方案：`docs/plans/plan-codeql-codescanning-remediation-2026-10-01.md`（已批准）；散点根因复盘：`docs/plans/plan-duplicate-logic-inventory-2026-10-01.md`。
> 背景：Code Scanning 21 条 open（14 high / 7 medium），其中 `py/weak-sensitive-data-hashing` 的根不是“哈希选错”而是“同一 `sha256(api_key)` 派生被抄 4 遍且截断语义分裂”。

- **Batch 1（D 类、3 medium）**：`.github/workflows/{agent-platform-ci,eval-llm,ha}.yml` 加顶层 `permissions: contents: read`（三个 workflow 全程只读仓库；`upload-artifact` 走独立 artifacts 服务不需额外 scope），收口 `actions/missing-workflow-permissions`。
- **Batch 2 ① 单一实现（kernel）**：`agent_core.guardrails.auth` 新增 `fingerprint(secret, *, length=None)` = `HMAC-SHA256(AGENT_PLATFORM_SECURITY_PEPPER, secret)`，截断有 **32 hex（128bit）下限**（低于即 `ValueError`，使 48bit 弱身份在本 API 上不可能再被写出）；`derive_thread_id(api_key)` 统一会话身份格式（`user-` + 32 hex）；`legacy_thread_id` 仅作迁移映射用（保留旧格式可复算）。未配 pepper 仍可运行，启动告警一次。
- **Batch 2 ② 站点收敛（消除 4× 重复，含 DUP-3）**：`guardrails/auth.resolve_client_key`（限流桶）、`llm/registry._hash_api_key`（LLM 客户端缓存键）、`agent_server/api/auth.resolve_thread_id`、`agent_federation/api/auth.resolve_thread_id` 均改指 kernel 实现；两个 app 的 `dev-default-thread` 字面量上收为 kernel `DEV_THREAD_ID`。`gateway/gray.py` 的 `md5(user_id)` 灰度分桶经实读定性为 **唯一真误报**（非密钥、非隔离），**不改码**，走 GitHub dismiss 附证据。
- **Batch 2 ③ 强制门禁（P6，三层补齐）**：`scripts/lint_architecture.py` 新增不变量——同一行出现弱哈希调用 + `api_key/secret/password/access_key/private_key` 语义标识即失败（全仓扫描，白名单仅 kernel 单一实现文件）；`hmac.new(secret, msg, hashlib.sha256)` 不命中（无紧跟 `(`）而 HMAC 恰是鼓励写法；`md5(user_id)` 不含密钥语义名，无需为其开白名单。自测：临时埋入违规探针 → 退码 1（并由 `tests/governance/test_thread_identity_migration.py` 以临时根目录固定此行为）。
- **派生变更的兼容路径（实施风险项）**：会话身份值改变会使旧 `updated/session_user-<legacy>/` 目录与 checkpointer `thread_id` 行对不上。新增 `scripts/migrate_thread_identity.py`：默认 dry-run，`--apply` 才改名，碰撞拒绝覆盖并计入 skipped；DB 部分**只打印 SQL 不代执行**（本仓 CI 无 PG，拒绝把未实跑验证的破坏性写操作固化进脚本，已在脚本 docstring 定为边界）。
- **登记**：新 env `AGENT_PLATFORM_SECURITY_PEPPER` 入 `.env.example` 与 `packages/agent-core/README.md` 环境变量清单；根 `tests/conftest.py` 将该变量加入 `_CLEARED_VARS`（否则本机 shell 设过 pepper 时指纹与测试期望不一致）。
- **测试**：新增 `packages/agent-core/tests/test_guardrails_fingerprint.py`（稳定性/区分度/pepper 依赖/长度下限/HMAC 等价/限流桶走同一实现）与 `tests/governance/test_thread_identity_migration.py`（P6 反例与正例 + 全仓零违规 + 迁移改名/碰撞/dry-run）；`tests/governance/test_auth.py` 与 `applications/agent_federation/tests/test_auth.py` 按新契约改写（断言与 kernel 单一实现一致 **且** 不再等于旧 `sha256(...)[:12]`，摘要宽度 12→32），断言未收窄。
- **Batch 3 ① 单一实现（kernel）**：新增 `agent_core.guardrails.fs`：`safe_join(base, *parts)`（拼接语义：绝对片段 / `..` / NUL / 空片段一律拒绝，拼接后仍做 resolve 包含判定，故也挡符号链接逃逸）、`resolve_within(base, user_path)`（解析语义：兼容 `/api/files` 把绝对路径原样传回的现有契约，但结果必须位于 base 内）、`safe_filename(name)`（basename + 字符白名单，`.`/`..`/空归 `_`）；`PathTraversalError` 继承 `ValueError`（宿主旧 `except ValueError` 仍兜得住），且**异常消息不带入参原文**（越界线索只进服务端日志），避免被 `detail=str(e)` 类写法带进出站响应。
- **Batch 3 ② 站点收敛**：`agent_federation/api/server.py` 三个文件端点（`/api/upload`、`/api/download`、`/api/files`）删除本地 `_sanitize_filename` 与两处手写 `resolve() + is_relative_to`，全部改调 kernel helper；同时把 `:284` `detail=f"路径无效: {e}"`、`:300` `detail=str(e)` 改为固定文案 + `logger.exception`（C 类堆栈回显的同源站点顺带消除）；`/api/download` 存在性判定由 `exists()` 收紧为 `is_file()`（不再把目录当文件回传）。
- **Batch 3 ③ 强制门禁（P7，三层补齐）**：`scripts/lint_architecture.py` 新增 P7-1（白名单外禁手写 `.is_relative_to(`，包含判定只允许 kernel 一处）+ P7-2（`applications/**` 下路径含 `/api/` 的模块，若有 `FileResponse(` / `.rglob(` / `.glob(` 出口却未调 `safe_join`/`resolve_within` 即失败）；白名单：kernel `guardrails/fs.py` 与 ks 两个静态页面 router（路径来自 `PROJECT_ROOT` 常量、无请求输入，已注理由）。
- **对外契约审计（不为统一而静默破坏兼容）**：`path` 入参在本仓 grep 仅命中定义处（无仓内消费者），前端为外部消费者且习惯把列表返回的**绝对路径原样回传**，故 `resolve_within` 保留对绝对入口的宽容（只要求落在 base 内），未收紧为“仅相对”；越界仍 403、缺失仍 404，仅“畸形入参（空/NUL）”由 400 归入 403。
- **Batch 3 测试**：新增 `packages/agent-core/tests/test_guardrails_fs.py`（拼接/解析/净化三入口的正反例 + 异常消息不泄漏 + 符号链接逃逸，Windows 无特权建软链故 2 例 skip）、`tests/governance/test_path_io_governance.py`（P7 反例/正例 + 当前树零违规 + 临时根埋探针验判定面）与 `applications/agent_federation/tests/test_file_endpoints.py`（直接调用 handler 断言 403/404/固定文案/上传落点净化）。
- **Batch 3 跨平台补修（CI 的 Linux runner 拉出的真缺陷）**：上述单测在 Windows 本地全绿，但 PR #33 的 CI 失败 4 条——`safe_join` 对 `C:\Windows\win.ini` / `\\server\share\x` DID NOT RAISE、`resolve_within` 对 `C:\Windows\win.ini` DID NOT RAISE、`safe_filename("..\\..\\windows\\win.ini")` 未去目录。根因是实现直接依赖 `pathlib` 的**宿主语义**（`Path.is_absolute()` / `Path.parts` / `Path().name` 在 POSIX 下均不将 `\` 视为分隔符），而服务入参可能来自 Windows 客户端。修法：**改实现、不动断言**——新增 `_ANY_SEP_RE`/`_ABS_FORM_RE`/`_WINDOWS_ABS_RE`/`_split_fragments`/`_is_foreign_absolute`，绝对与 `..` 判定同时覆盖两套分隔符；`resolve_within` 在 POSIX 宿主对含 `\` 的入参再作一次“反斜杠也是分隔符”的 containment（否则 `..\evil` 会被当作单个合法文件名而绕过穿越检查）；`safe_filename` 的 basename 改按分隔符切分取末段。保留 Windows 宿主对 `C:\...` 绝对入口的宽容（否则破坏 `/api/files` 回传契约）；测试面**拓宽** 4 例并注明不得改为 `skipif` 只跑一边。证据层级诚实：Windows 本地根 session **753 passed** / agent-core **278 passed** / 联邦 **152 passed** / governance **161 passed**，**POSIX 本机不可验证**（无 docker、WSL 未装分发），以此前失败的 CI 复验为准。
- **Batch 4 ① 单一实现（kernel）**：`agent_core.guardrails.errors` 新增 `mask_exception_for_client(exc, *, logger=None, context="", message=SANITIZED_5XX_MSG)`——自行 catch 的出口取固定文案的**脱敏边界点**。为何必需：`install_error_handlers` 只兜得住「未捕获异常 → 500 信封」，而 SSE 帧（状态码 200 已发）与手写 `JSONResponse` 它兜不住；`exc` **不参与返回值**（任何从异常消息派生的字段都会重开泄漏面），日志行内部用 f-string 而非 `%s` 惰性格式化，以同时兼容 std logging 与 loguru。
- **Batch 4 ② 站点收敛（6 处）**：exhibition `skill_loader/app.py` 3 处（CodeQL 所标的 3 条：chat 兜底 500 / invoke httpx 502 / health 探活 502）+ `skill_loader/agent.py` 工具 502 body（CodeQL 未标，但经 `/api/chat` 的 `tool_calls[].result_summary` 回传客户端，属同源）+ agent_server `api/query_router.py` 的 SSE `error` 帧 + knowledge-service `api/query_router.py` 与 `query_process/agent/nodes/node_answer_output.py` 两处 SSE `ERROR` 帧。保留项及理由：health 增加 `error_type=type(e).__name__`（类名不含消息，运维定位必需）；`/api/invoke` 保留 `url`（`/api/config` 已暴露同一 `WAREHOUSE_BASE_URL`，不属新增泄漏面）。
- **Batch 4 ③ 强制门禁（P8，三层补齐）**：`scripts/lint_architecture.py` 新增不变量——`applications/**` 下含 HTTP/SSE 出口标记（路由装饰器 / `JSONResponse(` / `HTTPException(` / `push_to_session(` / `sse_pack(` / `_sse(` 等）的模块，行内含异常消息级插值（`str(e)` / f-string `{e}` / `traceback.*`）即失败。放行四类：注释行、`logger.*` 行（异常全貌的合规去向）、仅类名写法（先剔 `type(x).__name__` 再判消息，故 `类名: 消息` 混写仍命中）、4xx 客户端错误回显（D-2=A：不动各 app 现有 4xx `{detail}` 信封，输入校验详情面向调用方自身输入）；白名单**故意置空并有单测钉住**（本不变量不允许静默例外）。**对 HEAD 版本回放**：命中 6 条与修复前站点逐条对应（规则非空转的直接证据）。
- **Batch 4 测试**：新增 kernel 6 例（`test_guardrails_errors.py` 固定文案/不泄漏/message 覆盖/日志仍写入/无 logger/`exc=None`）、`tests/governance/test_exception_echo_governance.py`（P8 正反例 + 当前树零违规 + 临时根埋探针）、`applications/exhibition-agent/tests/test_skill_loader_error_sanitization.py`（4 个出口 handler 直调，断言固定文案且内网主机/路径不出现在响应体）与 `tests/api/test_query_error_sanitization.py`（ASGITransport 驱 `/query`，断言 error 帧为固定文案且无 `NoneType`/`astream`，同时断言服务端日志仍在）。ks 两处站点**无行为级回归**：该仓 unit 套件 conftest 明文“刻意不依赖重型依赖”，导入 router/main_graph 会破其设计，改由 P8 结构门禁 + kernel 单测覆盖。
- **登记为范围外（P8 判定面之外，需先做通道分离再决策）**：nl2sql `agent/nodes/execute_sql.py:31` 的 `state["error"] = str(exc)` 会经 `SqlQueryResponse.error` 出到客户端，但**同一字段又是 `correct_sql` 节点的 LLM 纠错输入**——直接脱敏会削弱纠错回路；同类还有 federation `tools/*` 的 LLM 观察字符串与 `monitor.report_error(detail=str(e))` 审计遥测、agent_server `planners/graph.py` / `sql/pipeline.py` 的 StreamEvent error payload、exhibition `foundation/production_readiness_gate.py`。均非 HTTP 出口行内拼接，属“内部详情与对外文案未分道”的独立议题。
- **Batch 5（E 类、1 high）——把 dismiss 升级为根因消除**：`packages/agent-runtime/tests/test_skills_remote_dag.py:22` 原为 `assert "example.com" in result`，形状形似「URL 子串白名单校验」而为误报（该处实为 `as_remote_skill` 透传契约断言）。先按方案核实**生产面有无同款弱判断**：`packages/` 与 `applications/` 的非测试代码对「字面量含 `.com/.cn/localhost/://` 与 `in <url 类变量>`」两面均 **0 命中**（唯一相近的 `dsn.startswith("sqlite:///")` 是前缀而非子串判定），因此无可上收的单一实现。处置选择：不留在 GitHub 人工 dismiss（避免永久人工动作与注释债），改为**更强的等值断言** `result == "content from http://example.com"` 并补 `isinstance(result, str)`，零覆盖损失（改动方向是收紧，不触碰「不为消警放宽断言」红线）。
- **Batch 5 门禁决策（显式承认它是「三层齐备」的例外）**：不开 P9。理由：`lint_architecture.py` 只走 stdlib 正则、无类型推断，无法区分弱校验形态（子串包含）与**正确形态** `host in ALLOWED_HOSTS`（集合成员），而后者正是应被鼓动的写法；且生产面命中为 0，无存量需守。该维度继续交给 CodeQL 自身规则。同类形状 `test_model_router.py:230`（邮箱脱敏断言，CodeQL 未标）仅登记不改码。
- **核生产时的两条附带观察（不构成 E 类，登记为硬化候选）**：`agent_server/sql/pipeline.py:48` 的 `sqlite3.connect(f"file:{unquote(path)}?mode=ro", uri=True)` 若 `path` 解码后含 `?`，`mode=ro` 会落入首个参数的值而静默失效（只读双保险退化为一层；当前 `path` 源自服务端配置非请求入参，不列为可利用漏洞）；同文件 `:65` 的 `sqlite:///` 前缀判定属可接受写法。
- **未动项**：代码面五批已收完（A/B/C/D/E 均已修或定性），**open 告警归零需 GitHub 重扫确认**（本机无 CodeQL CLI）；仍需人工：`gateway/gray.py:40` 与 kernel #38/#39 的 dismiss（附证据）、部署时配 `AGENT_PLATFORM_SECURITY_PEPPER` 并先 dry-run 执行 `scripts/migrate_thread_identity.py`。原列为人工候选的「若 A/C 仍报则补 CodeQL data-extension 将 `safe_join`/`resolve_within`/`mask_exception_for_client` 声明为 sanitizer」已经 PR 重扫的反向证据排除（无新增 A/C/E/D 告警），无需补。
- **提交与交付状态**：Batch 1~5 已拆为 7 个 commit（`e488c96` 为此前的 Batch 1，本会话新增 `7bf3311` docs 方案 / `ba1b968` Batch 2 / `a586859` Batch 3 / `7cc9e1d` Batch 4 / `88f56c8` Batch 5 / `b845805` docs 收口）并 push 至 `fix/codeql-remediation-batch-1-5`，开为 **PR #33**（base `main`）。拆分取舍：`lint_architecture.py` 单文件承载 P6/P7/P8，因此**门禁层与其治理测试集中在 Batch 4 commit**（否则中间 commit 的树 `make ci` 会因引用尚未入库的 `fs.py` 而变红）。
- **PR #33 重扫结果与二次处置**：合入前 GitHub 已对本 PR 跑了一轮 CodeQL（PR 模式）。**无新增** `py/path-injection` / `py/stack-trace-exposure` / `py/incomplete-url-substring-sanitization` / `actions/missing-workflow-permissions`（A/C/E/D 的修改面在 CodeQL 眼里已无新问题，旧告警仍 open 只因默认分支未重扫）；新增仅 2 条 `py/weak-sensitive-data-hashing`，均落在 kernel 定义处：`guardrails/auth.py:78` 的 `hmac.new(pepper, secret, sha256)` 定为**误报**（输入是高熵 API Key、产物只做查表标识且每请求计算，换 scrypt/pbkdf2 只有延迟成本；**不改变量名躲检测器**），`:99` 的 `legacy_thread_id`（48bit 截断）形状**属实但不可消除**（需复算升级前旧会话身份）。两者均已写下可复核证据，但 **dismiss 未能脚本化**（`gh api` 对告警状态写入端点实测 HTTP 404，`PUT`/`PATCH` 两种动词与 `refs/heads/main` 告警均同，而 `GET` 正常 200；后经 `gh api -i` 响应头对比确证为令牌缺 `security_events` scope（GitHub 对 scope 不足统一回 404 而非 403）），仍需在 Security 面板手工执行（或先 `gh auth refresh -s security_events` 再走 API）；建议文案已同步入库（模块 docstring + 方案「PR #33 实测重扫结果」节）。
- **二次重扫（`c8e512e`+`45373dd`）无新增告警**：`ci`（push/PR 两事件）、`ha`、`Analyze (python|actions)` 均 pass；PR ref 上 open 仍只有 #38/#39 两条，**编号未因 kernel docstring 导致的行号漂移（78→92、99→117）而变动**——CodeQL 分组跟住了纯注释变更，本轮定调无需重开。CodeQL 检查仍 fail 的唯一剩余原因就是这两条未 dismiss（定性已同步回帖到 PR 上的两条 annotation，当前权限下能做的替代动作）。
- **新增 P6-2 门禁（约定 → 不变量）**：`legacy_thread_id` 的调用面原先只靠 docstring 约束（kernel 在 P6 白名单内，lint 拦不住新增调用点），现由 `scripts/lint_architecture.py` P6-2 锁死：除 kernel 定义处与 `scripts/migrate_thread_identity.py` 外出现调用即 CI 失败；补 4 个治理用例（单行正反例 + 当前树零违规 + 临时根埋探针验扫描面）。

## 隔离域加固：tenant 边界 / workspace 归属 / memories 双 scope（2026-09-27，分支 `feat/isolation-hardening`，`f072bc2..28877fc`）

> 归属说明：以下两节（09-27 隔离域加固、09-25 租户隔离收紧）原为 `v3` 分支历史条目，随 2026-10-01 `integration/v3-into-main` 合流**首次进入 `main` 时间线**。按 append-only 约定，不重写、不重排任何已有条目，仅加本行归属标记。

> 方案：`docs/adr/0006-isolation-dimension-contract.md`（已采纳）+ `docs/plans/plan-isolation-hardening-2026-09-27.md`（T9–T13）；episodic/procedural 部分依 `docs/plans/plan-memory-hardening-2026-09-27.md` T1。核心：`tenant_id` 为唯一安全边界（服务端解析、漏传 fail-fast 沿用 `_tenant_gate`），`workspace_id`/`user_id` 为归属维不单独承担隔离。

- **T9 corpus 补 tenant_id（`f072bc2`，W1）**：migration `006_tenant_corpus` 为 `chunks`/`sql_ddl`/`sql_docs`/`sql_examples` 加 `tenant_id`（`DEFAULT 'default'`）+ `(tenant_id, workspace_id)` 复合索引；`rag/store.py`、`sql/schema_store.py` 读写 SQL 成对带 tenant 谓词、消除「空 workspace = 全库召回」旁路；写入口（`/import`、`/sql/train`）收服务端租户（不收表单值）。
- **T10 workspaces 归属表（`28feae4`，W2/D4 方案 A）**：migration `007_workspaces` + 新模块 `agent_runtime/workspace_registry.py`；**复合 PK `(tenant_id, id)` 按租户命名空间化**（`workspace_id` 当前为客户端扁平串且共享 `'default'`，不能用全局唯一 `id` PK，否则跨租户撞名）；`resolve_workspace(tenant_id, workspace_id)->bool` 首次引用自动注册、越权 `assert_workspace_access` 抛 `WorkspaceTenantMismatch`；migration `009_workspaces_backfill` 幂等补注册现网 `(default, workspace_id)`。`import/sql/query_router` 使用前统一 `resolve_workspace`（读路径 best-effort）。
- **T11 knowledge-service 租户强制化（`0163fc6`，W4）**：`utils/tenant_utils.resolve_server_tenant()`——空 tenant → 服务端注入 `KNOWLEDGE_DEFAULT_TENANT_ID` + 审计（**选注入而非 422**：避免同步打断多个历史不传 tenant 的存量链路，同时关掉「空→不过滤=全库」真旁路）；删 `mongo_history_utils` 的 `if tenant_id else None` 回退；调用方审计：联邦 `tools/knowledge_tools.py::knowledge_retrieve` 改为下传请求链路租户（`api.context.get_tenant_context`），非 server 环境降级注入。
- **T12 隔离维度契约测试（`9c27c82`，W5）**：`tests/governance/test_isolation_dimension_contract.py`——迁移回放最终 schema 断言每张业务表含 `tenant_id`（系统/待判定表显式白名单+理由，人为建无 tenant 业务表→红）；AST 断言 `workspace_id =` 谓词必与 `tenant_id` 成对（已知误报源：docstring/日志，按“含表名 token + SQL 动词”过滤）。
- **T13 memories 双 scope（`e5566bf`，W3/用户拍板“画像层必须存在”）**：migration `008_memories_dual_scope`（`workspace_id`/`scope` 列 + 两索引 + user_id←workspace_id 回填）；内核 `typed.py` **新增** `remember_typed_scoped`/`recall_user_profile`（既有 5 动词签名不变、ADR-0004 向后兼容），workspace/user 两路各自 top-k 后按同一 `type_weight×importance×decay` 融合（不改评分公式，融合置于门面 `memory_backend.recall_typed`）；`MEMORY_DUAL_SCOPE` 渐进开关默认关=零变更，读路径双列兼容滚动升级窗口。
- **T1 episodic/procedural 补租户（`28877fc`，G1 / plan-memory-hardening T1）**：migration `010_episodic_tenant` 为 `episodic_memories`/`procedural_memories` 补 `tenant_id` + 复合索引，**procedural PK 命名空间化 `(tenant_id, name, version)`**（技能名由 `task_summary` 派生易跨租户撞名，仅加 WHERE 不改 PK 会写覆盖=假隔离）；`EpisodicStore`/`ProceduralStore` 及 InMemory/Pg 实现、`memory_sink`/`memory_decay`/`memory_seed`/`memory_types` 全链路带 `tenant_id`（`_tenant_gate` 必填 fail-fast）；**写路径租户源缺口修复**：`TrajectoryRecord` 加 `tenant_id`，`_persist_trajectory` 从 `plan.tenant_id` 填充；recall 路径 `MemoryRecallRequest.tenant_id` 下传并映射为 `MemoryRecallResult`。
- **迁移编号 006–010**：均 up/down 成对、`IF [NOT] EXISTS` 幂等、SQL 英文注释、LF 行尾；agent-core 零宿主依赖保持（`typed.py` 仅 stdlib；`workspace_registry`/执行记忆 store 落 agent-runtime，红线 1 无反向 import）。
- **未决 / 边界（诚实标注）**：① corpus/memories/episodic 存量 `DEFAULT 'default'` 回填为**目标库部署前置**——应用前须抽样确认无真实多租户混入（混则停工建归属映射，见 plan §8.2/§8.4），开发机无目标 PG 未执行；② agent_server→knowledge-service 真实多租户 tenant 下传、`/query` 服务端租户断言属跨服务契约变更，需另立 ADR（现注入策略下安全不 422）；③ HA 真实 PG 用例（`tests/ha/test_tenant_isolation_real_pg.py`：corpus/workspaces/dual-scope/episodic/procedural 跨租户）需 Linux CI `requires_pg` 跑，本机 skip。

> 验证（本机可跑，全绿）：根 438 / agent-core 219 / agent-runtime 580 / agent_server 44 / federation 142 / knowledge-service 235 / kefu 43 / nl2sql 18 / exhibition 343 / shared-schemas 28；`ruff check .` 0；`lint_architecture` + `check_doc_sync` 通过。唯一失败 `test_circuit_breaker_middleware_degrades` 为 v3 既有、与本工作无关。


## 租户隔离收紧 + HA 门禁语义 + CI 收窄（2026-09-25，`7e442c4..b77be4e`）

> 方案：`docs/plans/plan-p0-ha-tenant-fixes-2026-09-25.md`。外部审计（36 commits, c6b60a55）P0/P1 修复。评审修复（W-2）续见本节末。

- **⚠️ 破坏性行为变更（有意，不可逆）**：召回读谓词从过渡期 `tenant_id = ANY(%s)`（真实租户 + legacy `default` 桶）收紧为精确 `tenant_id = %s`（`7e442c4`）。真实租户升级后**不再读到**多租户上线前的历史记忆（v5 迁移已把历史行归并进 `default` 桶）；该数据仅 `default` 租户可见，或由管理员迁移工具重新归属。**回滚指引**：005 down 仅回滚列默认值、刻意不回滚数据（见该文件注释）——升级前如需保留跨租户历史可见性，须先完成数据归属迁移。配套：治理 fake 收紧为标量契约（泄漏形态直接断言失败）+ 新增真 PG 行为级回归 `tests/ha/test_tenant_isolation_real_pg.py`（legacy default 行对真实租户不可见 / default 租户仍可读 / 跨租户同 workspace 隔离），变异验证：谓词退回 ANY → 治理测试 4 failed。
- **`CapabilityReport.supports_tenant_isolation`**：新增能力声明字段并纳入 `as_dict()`/`/health`（pg-typed=true / vector=false），消除「调用方误以为已获得租户隔离」。
- **HA 门禁语义（skip→fail-not-skip）**：`tests/ha` 在 CI 环境（`CI`/`GITHUB_ACTIONS` 任一为 true）PG 不可用 = **FAIL** 而非 skip，杜绝「15 skipped 但 green」假信号；本地无 PG 保留 skip。普通 `make test` 根 session 以 `-m "not requires_pg"` 排除 HA 测试（归属 agent-platform-ha workflow）；conftest marker 路径判断修复 Windows 反斜杠兼容。
- **CI 收窄**：`ha.yml` 触发移除 `applications/**`（重型 HA 仅由 packages/tests/ha/脚本/配置变更触发）。
- **勘误**：下文 Warning#8 段描述的「过渡期 ANY 历史可读」为当时过渡契约，**已于本次收紧删除**，以本节为准。
- **W-2 补充（同日评审修复）**：内核 typed/store 五动词 + 宿主门面（agent_server longterm/memory_backend、federation semantic_memory）共 27 处 `tenant_id: str = "default"` 隐式缺省全部改为哨兵 `_TENANT_UNSET`（`agent_core/memory/_tenant_gate.py`）——**漏传即 `ValueError`**，不再静默落共享 default 桶。全链生产调用点已核实显式传租户（graph/planner/router/federation ContextVar），爆炸半径仅测试补显式 `tenant_id="default"`（67 处调用点，AST 脚本机械修复）。新增 AST 治理红线 `tests/governance/test_tenant_default_forbidden.py`（默认值形态回潮即 CI 失败；构造期配置类 `mongo_checkpointer`/`vector_backend` 白名单，其 tenant 语义矛盾另立任务）。

## workspace 顶层包名冲突全局治理（eval 消歧义 + P5 门禁，2026-09-25）

> 方案：`docs/plans/plan-workspace-toplevel-eval-disambiguation-2026-09-25.md`。背景：editable 安装以朴素 `.pth` 把成员源码根整体加入 `sys.path`，顶层包名 `eval` 被 agent_federation 与 knowledge-service 双重暴露，解析取决于安装顺序；前次 conftest 局部重绑补丁（c6b60a5）属散点止血，本次按「单一实现 + 全局装配 + 强制门禁」三层收口并撤销该补丁。

- **① 单一实现（ks 架构倒挂修复）**：`compute_config_hash`（含 `_RUNTIME_BASELINE`/`_sha256_hex`）从 `knowledge-service/eval/run_eval.py` 上收至新建 `knowledge_service/conf/config_hash.py`；`main.py` 不再 `from eval.run_eval import`（生产链路反向依赖评测 harness，且 wheel only-include 不含 eval/，打包部署必挂）；评测脚本与生产运行时共指同一实现。函数行为零变更。
- **② 消歧义（全局装配）**：`agent_federation/eval/` → `agent_federation/evaluation/`（`git mv` 保留历史；冲突引用面较小方），同步更新：包内 `from eval.*` 导入、docstring/用法路径、`tests/unit/test_eval_baseline.py`（`agent_federation.evaluation.run_eval`）、`pyproject.toml` ruff per-file-ignores、`.gitignore`（`evaluation/results/`）；live 文档同步（根 README/Makefile 注释/docs/TODO、federation production-action-plan 命令）。历史快照文档（CHANGELOG/AUDIT/PROPOSAL/analysis）不回改。全仓仅剩 ks 一个顶层 `eval` regular package，`.pth` 顺序敏感性消除。
- **撤销散点补丁**：`knowledge-service/tests/unit/conftest.py` 的 importlib 重绑 hack 恢复原样（止血措施随根因修复退场）。
- **③ 强制门禁（P5）**：`scripts/lint_architecture.py` 新增不变量——与 uv workspace members + 根包 wheel packages 同源解析暴露根，扫描源码根下含 `__init__.py` 的直接子目录，跨成员顶层包名重复即 CI 失败；当前树零违规无需白名单，自测：人为制造重名目录→退出码 1。

## 分支评审修复：Planner 租户传播 + SEMANTIC_MEMORY_TYPED 语义收口（2026-09-25，分支 `fix/v3-scheduler-tenant-isolation-20260924`）

> 来源：2026-09-25 对昨日新建分支的 CodeReview（Critical#2/#3、Warning#7）。

- **Critical#2 — Planner 租户传播**：`GraphPlanner`（4 处 Plan + execute 重建 plan_ctx）、`UnifiedPlanner` WORKFLOW 分支（Plan 身份字段 + kwargs 携带 tenant/workspace/user）、`AgenticPlanner`、`deterministic` MCP AgentState、`capabilities._run_general_qa` state 注入全部补齐 `tenant_id`；新增治理红线测试 `tests/governance/test_planner_tenant_propagation.py`（枚举全部 Planner 构造点，防漏传静默落共享桶）。
- **Critical#3 — 内核/federation 透传 tenant**：`agent_core.memory.store.MemoryStore` 协议五动词加 `tenant_id` keyword 参数，`PgMemoryStore` 透传内核 typed；`VectorMemoryStore` 显式声明不支持隔离（接口兼容）。federation `semantic_memory.py` 封装函数 + `main_agent_memory.py` 接线经 `api.context` ContextVar 取租户透传。
- **Warning#7 — 开关语义收口（WS-1）**：`agent_server/memory/longterm.py` 删除 `maybe_consolidate()` 中残留的 `SEMANTIC_MEMORY_TYPED` 栈门控（与读写路径对齐：该开关自 WS-1 起只在内核控制召回加权融合，不控栈选择；记忆总开关为 `SEMANTIC_MEMORY_ENABLED`），消除“读写不受控、巩固受控”分裂；模块/函数 docstring 与过时注释同步收口。测试：`test_maybe_consolidate_noop_when_disabled` 按新语义改写为 `test_maybe_consolidate_not_gated_by_typed_switch`（门禁：开关关闭时有池仍须触发巩固）+ 新增 `test_maybe_consolidate_noop_without_pool`（无池空操作），断言未收窄。
- **Warning#8 — v5 迁移可回滚 + 历史行过渡读**：新增 `005_memory_tenant_enforcement.down.sql`（仅回滚列默认值，刻意不回滚数据并在注释说明不可逆理由）与 `004_memory_tenant_id.down.sql`（对称 DROP，对齐 002/003 惯例）；内核 `agent_core/memory/typed.py` 召回读谓词改为过渡期 `tenant_id = ANY(%s)`（`_read_tenant_scope` 含 legacy `default` 桶，user_id 隔离维度不变），修复升级后带真实租户的请求读不到多租户上线前历史记忆的问题；删除路径（consolidate/forget）仍精确匹配不跨桶，收敛后可收紧。测试：新增 `TestTenantMigrationsRollback`（v4/v5 down 守卫）与 agent-core 读作用域/删除精确性 3 用例。**【2026-09-25 勘误】过渡读契约已收紧删除（读谓词精确 `= %s`，`_read_tenant_scope` 已删除），见顶部「租户隔离收紧」节。**

## MCP SDK 真实接入（2026-09-22）

> `mcp_client.py` 的 MVP 桩（`_invoke_tool` / `_discover_tools` / `_connect_*`）替换为真实 MCP SDK 调用，MCP 工具可经 stdio / SSE transport 真正连接、发现、调用。
> 验证：91 passed（agent-runtime）/ 361 passed 15 skipped（根）/ ruff 0 error。

### 改动

- **`_connect_stdio`**：`StdioServerParameters` + `stdio_client()` async ctx → `ClientSession(read, write)` → `session.initialize()`，返回 `(AsyncExitStack, session)`。
- **`_connect_sse`**：`sse_client(url)` async ctx → `ClientSession` → `initialize()`，同上。
- **`_discover_tools`**：`await session.list_tools()` → `[t.name for t in result.tools]`。
- **`_invoke_tool`**：`await conn.session.call_tool(tool_name, params)` 返回 `CallToolResult`（替换原 mock dict）。
- **`_reduce_result`**：处理 `CallToolResult.content`（`TextContent.text` 提取），`is_error=True` 时 raise `RuntimeError`（`call_tool` 捕获后返回 `McpToolResult(success=False, error="TOOL_RETURNED_ERROR")`）。
- **`close_all`**：`await conn._exit_stack.aclose()` 按 LIFO 关闭 session → transport。
- **`_MCPConnection`**：新增 `_exit_stack: AsyncExitStack | None` 字段。
- **`pyproject.toml`**：`agent-runtime` 新增 `[project.optional-dependencies] mcp = ["mcp>=0.9"]`。

### 测试

- 新增 `test_mcp_client_real.py`（13 例）：`_reduce_result` 处理 `CallToolResult` / `is_error` / 截断 / dict 兼容 / 纯字符串；`_invoke_tool` 真实调用 + SDK 缺失降级；`_discover_tools` 真实 `list_tools`；`close_all` 关闭 `AsyncExitStack`；`call_tool` 集成（`is_error` → 失败 / `TextContent` → evidence）。
- 现有 `test_mcp_skill.py` 8 例全绿（手动注入 `_MCPConnection`，不经 `connect_all`，不受影响）。

## Plan-F 架构收口 + Skill 体系完善（2026-09-21）

> Plan-F 4 个演进方向全量闭合，Skill 注册体系完善，沙箱代码执行落地。
> 验证：534 passed / 15 skipped / eval 15/15 = 100% / ruff 0 error。

### Plan-F 演进方向闭合

- **Plan.notes → 显式字段**（`36a3c0d`）：删除 `Plan.notes` 万能字典，所有字段提升为 Plan 显式字段（session_id/planner_name/constraints/kwargs 等），execution_graph.py 读取路径全部切换。PlannerContext 修复重复 `question` 字段 bug。
- **Dynamic Agent 纳入 Skill 体系**（`e477397`）：`AgenticPlanner.execute()` 加 `runtime.execution()` + `skill_guard("agentic")` 包裹，与 `arun()` 对称。agentic 执行受统一组合治理（步数/深度/循环），`SkillCompositionError` 直接抛出。
- **Workflow Definition → Workflow Skill 编译**（✅ 已实现）：`compile_workflow()` / `load_workflow_yaml()` / `discover_workflows()` 全部就绪，`agent_server/main.py` 启动期自动加载 `workflows/*.y*ml`。
- **SkillRegistry/SkillRuntime 分离**：暂缓（"边界出现再拆"原则，当前仅 timeout + 契约校验两个边界）。

### Skill 注册体系完善

- **MCP 工具自动注册**（`c472d59`）：`register_mcp_skills()` 把 MCPClientManager 发现的每个工具编译为 `SkillKind.REMOTE` Skill，命名 `mcp.{server_id}.{tool_name}`。启动期自动注册，Planner 经统一 `discover()` / `delegate()` 入口。
- **沙箱代码执行**（`7fcf303`）：`SandboxExecutor` 双后端（Docker 优先 subprocess 降级）。Docker 安全措施：`--rm --network=none --read-only --tmpfs /tmp --memory=512m --cpus=1 --security-opt=no-new-privileges --user=nobody`。注册为 `code_execution` Skill。
- **Planner 路由到沙箱**（`bf1f44c`）：启发式路由增加 `code_execution`（优先级最高），`_extract_code` 从用户输入提取代码块（支持 ` ```python ... ``` ` 格式），graph.py 增加代码执行节点。eval golden 15 条（含 3 条 code_execution）。

### Skill 注册体系终态

| 函数 | 类型 | 用途 |
|------|------|------|
| `as_function_skill()` | FUNCTION | 进程内确定性函数 |
| `as_agent_skill()` | AGENT | 本地 subagent（LLM self-reasoning） |
| `as_remote_skill()` | REMOTE | 远程子服务（HTTP / Agent Protocol） |
| `compile_workflow()` | WORKFLOW | YAML 声明式工作流编译 |
| `register_mcp_skills()` | REMOTE | MCP 工具自动注册 |
| `as_sandbox_skill()` | FUNCTION | 沙箱代码执行（Docker/subprocess 隔离） |

## Runtime 治理路线图全量闭环（2026-08-21）

> `docs/operations/runtime-governance-roadmap.md` P0~P5 全区段落地；`docs/tech-debt-hardcoded-logic.md` TD-1~TD-14 全部闭环。
> 验证：ruff 0 error / 架构 lint 通过 / 根 tests **541 passed**（原 import 失败目录已修复）/ 联邦 unit **92 passed** / kefu **8 passed** / eval **12/12 = 100%**。

### 计量闭环（P2）

- **P2-1 tokens/cost 聚合器**：`ExecutionContext` 新增 `tokens_used / cost_used / max_tokens / max_cost` + `record_usage()`（超限抛 `SkillCompositionError`）；`PlannerRuntime` 透传配置。
- **P2-2 llm client 计量点**：`FallbackChatModel` / `LangChainFallbackModel` 抽取 `usage_metadata`（含 `response_metadata` 兜底）→ `on_usage` 回调；`PlannerRuntime` 装配期接线到当前 `ExecutionContext`（contextvars 按 task 隔离，边界外静默丢弃）；invoke/ainvoke/stream/astream 四路径外发；`status` 事件带累计 tokens/cost。

### Trajectory（P3）

- **P3-1 持久化**：新增 `agent_runtime/trajectory/`（TrajectoryRecord/TrajectoryStep + `TrajectoryStore` 契约 + `InMemoryTrajectoryStore`/`PgTrajectoryStore`）；`execute_plan` 末尾 `_persist_trajectory`；宿主装配期 pool 非 None 时注入 PG 实现。
- **P3-2 Replay**：`trajectory/replay.py`——`replay_trajectory` 复用 `execute_plan` 真实执行链，报告五类 divergence（order / extra_call / missing_call / result_change / error_change）。

### 分布式 / 治理（P4）

- **P4-1 可插拔 session lease**：`LeaseBackend` 协议 + `InMemoryLeaseBackend`（默认快路径）+ `PgAdvisoryLeaseBackend`（`session_leases` 表单飞授权 + TTL 过期 + 双写本地镜像）；`Coordinator(lease_backend=, lease_ttl=)` 注入式。
- **P4-2 架构约束 lint**：`scripts/lint_architecture.py` 检测白名单外 `registry.execute()` 直调，串入 `make lint`。
- **P4-3 coalesce 诚实改名**：策略枚举仅保留 queue/reject。

### 语义循环检测（P5）

- **P5-1 TrajectoryFingerprint**：`_fingerprint`（skill + 归一化 kwargs，键序无关）重复指纹抛 `SkillCompositionError`；`enable_loop_fingerprint` 默认关闭防误伤合法重放。

### 技术债收尾（TD）

- **TD-1** kefu 意图路由验证：确认真实复用 `agent_core.intent`（回归测试锁定）；**TD-3/TD-4** 由 WS-6 隐式解决；**TD-5** 阈值参数化（`ITEM_CONFIRM_HIGH/MID_THRESHOLD`）；**TD-7** 路由特征词外置 `route_hints.json`；**TD-8** longterm prompt 泛化；**TD-9** eval 超参统一读 yaml；**TD-10** admission 状态常量 `ADMISSION_*`（含 SQL 语法修复）。

### 其他（同日提交）

- **§20 Workflow DSL**：YAML 声明式 Workflow 编译为 Skill + Workflows 目录自动发现注册。
- **UnifiedPlanner**：graph/workflow 统一分发；**PG durability**：admission/checkpoint/ownership/idempotency PG 后端套件。

## Agent 核心架构优化八工作流全量落地（2026-08-20）

> 实施计划：8 个工作流（WS-1 ~ WS-8），按 P0 → P1 → P2 推进。
> 原则：**不推倒重来，先接线、再收敛、最后清理**；每个 WS 独立可交付。
> 验证：ruff 0 error / 根 tests **484 passed** / 联邦 unit **89 passed** / kefu **8 passed** / eval **12/12 = 100%**。

### WS-1（P0）记忆子系统统一门面

- **`packages/agent-core/agent_core/memory/store.py` 新建**：`MemoryStore` Protocol（五动词 `recall / remember / consolidate / forget / probe`）+ `CapabilityReport` dataclass（宿主 `/health` 可直接序列化）。
- **`PgMemoryStore`**：包装 `typed` 模块（宿主 psycopg 池，遵守 ADR-0003 单一连接源），embedder 构造注入，支持全部五动词，**pg 为唯一权威后端**。
- **`VectorMemoryStore`**：包装 `MemoryBackend`（Milvus / PgVector），仅 recall / remember；consolidate / forget 返回 0 / False（向量后端无类型列）。
- **`semantic.py` 门面降级为薄适配器**：`SEMANTIC_MEMORY_ENABLED` 单总开关控制，`SEMANTIC_MEMORY_TYPED` 保留但只影响加权策略（**WS-1 起默认开**，不再决定走哪条栈）。
- 宿主接线：`applications/agent_server/memory/memory_backend.py` 改经门面；`lru_cache` 后端工厂补 `reset_backend_cache()`。
- **测试**：扩展 `packages/agent-core/tests/test_typed_memory.py`、`tests/test_memory_backend.py`；新增 probe 测试（无依赖环境返回 enabled=False + reason，绝不抛异常）。

### WS-2（P0）Context Pipeline 接线：snapshot 消费 + compact 归一

- **snapshot 消费闭环**：`applications/agent_server/planners/graph.py` 消费 `execute_plan` 产出的 `StreamEvent(type="status", payload={"snapshot": ...})`——多轮时将 `task`/`execution` 段注入下一轮 prompt 头部，并按现有 thread 持久化机制落 checkpoint。
- **compact 归一**：`agent_server/agent/graph.py`、`planners/deterministic.py` 改经 `agent_runtime.context.compact`；旧 `agent_server/agent/compact.py` 标记弃用。
- **`ConversationContext.compacted` 回填**：`deterministic.plan` 压缩分支 `notes["compacted"] = True`，`execution_graph.execute_plan` 检测后回填 `ctx.conversation.compacted`，保持三层契约一致。
- **测试**：`tests/test_compact.py` 迁移扩展；新增 snapshot 注入回归 + compacted 回填测试（`test_execute_plan_compacted_flag_backfilled` / `_default_false`）；eval 12/12 不回退。

### WS-3（P1）可靠性原语收敛

- **`resilience.CircuitBreaker` 并发安全**：内部加 `threading.Lock` 保护 `allow()/record_*`，half_open 探测计数不再竞态；新增 `_half_open_inflight` 限制并发探测数（`max_half_open_probe`）。
- **统一状态常量**：内核暴露 `STATE_CLOSED / STATE_OPEN / STATE_HALF_OPEN`（`agent_runtime.circuit_breaker` 的 `"half-open"` 兼容别名保留一版）。
- **`llm/fallback.py` 降级状态机收敛**：`FallbackChatModel` 删除内嵌失败计数，改为**组合** `CircuitBreaker`（threshold→failure_threshold，cooldown→reset_timeout），可复位。
- **流式降级语义修正**：`stream/astream` 仅在「未产出任何 chunk」时才允许切备模型重放；已产出 chunk 后主模型失败 → 向上抛异常，docstring 明确契约。
- **测试**：扩展 `packages/agent-core/tests/test_resilience.py`（并发 allow/record 竞争用例）、`tests/test_llm_fallback.py`（中途流式失败 + breaker 组合用例）。

### WS-4（P1）可观测性统一事件出口

- **`packages/agent-core/agent_core/events.py` 新建**：`EventSink` Protocol + `EventBus`（多 sink 扇出、逐 sink 异常隔离、失败计数）。
- **四 sink 注册**：`CallbackSink`（回调订阅）、`WebSocketSink`（WS 推送）、`LegacyStreamSink`（旧 builtins.runtime 通道，首次命中触发 DeprecationWarning）、`OTelSpanSink`（OTel span 事件出口，懒导入 opentelemetry，无活跃 span 时静默 no-op）。
- **`monitor.py` 改造**：`ToolMonitor._emit` 改走 `EventBus` 扇出；`ToolMonitor()` 单例语义保留兼容，新 API 支持 `ToolMonitor(bus=...)` 构造注入。
- **测试**：`packages/agent-core/tests/test_events.py` 扩展多 sink 扇出 + 异常隔离 + OTelSpanSink（no-op / fake span 写入）用例；federation/kefu 既有 monitor 测试全绿。

### WS-5（P1）KernelConfig 与环境变量治理

- **`packages/agent-core/agent_core/config.py` 新建**：`KernelConfig` dataclass + 类型化 env 解析助手（`env_bool / env_int / env_float / env_str`，非法值警告并回退默认）；`env_database_url`（新名 `AGENT_PLATFORM_DATABASE_URL` 优先，旧名 `DEEPAGENTS_DATABASE_URL` 兼容 + DeprecationWarning）。
- **散点 `os.getenv` 全量迁移**：`memory/typed.py`、`memory/semantic.py`（5 处：VECTOR_BACKEND / MILVUS_URI / MILVUS_TOKEN / SEMANTIC_MEMORY_COLLECTION / TENANT_ID）改经 `env_str`/`env_bool`。
- **环境变量清单表**落入 `packages/agent-core/README.md`（变量名 / 默认值 / 所属模块 / 用途），后续新增 env 必须登记。
- **测试**：新增 config 解析单测；grep 确认无新代码直读旧变量名。

### WS-6（P2）意图 L1 分类器数据化与异步契约

- **`packages/agent-core/agent_core/intent/classifier.py`**：`_load_prototypes()` 加 `@lru_cache(maxsize=1)`（保留测试用 `cache_clear` 出口）；chitchat 关键词短链（`_CHITCHAT_STRONG` / `_CHITCHAT_WEAK`）外置到 `data/prototypes.json` 的 `chitchat_shortcuts` 段，代码只留读取逻辑 + 数据缺失兜底。
- **新增 `classify_l1_async(query)`**：`asyncio.to_thread(classify_l1, ...)` 包装，docstring 声明 `classify_l1` 为阻塞调用。
- 核查 `agent_federation/planners/agentic.py` 与 kefu 调用点，统一改走 async 入口。
- **测试**：`packages/agent-core/tests/test_intent.py`、`test_intent_l2.py` 全绿 + 数据外置后等价性用例。

### WS-7（P2）Tool/Skill 执行策略合并

- **`packages/agent-runtime/agent_runtime/skills/middleware.py`** 新增 `GuardMiddleware`：超时（`asyncio.wait_for`，async-native）+ 失败降级返回空结果，语义对齐 `guarded_invoke`；新代码应优先挂本中间件而非再包 `wrap_tool`。
- **`agent_core.tools.guarded`** 与 **`ToolRegistry`** 标记为维护模式：docstring 声明新代码用 SkillRegistry + middleware；zhanggui-zhiku 的 fanout 调用点迁移列入后续专项。
- **`guarded_invoke`** 内 8 线程池保留（同步工具仍需），补"超时后线程不可取消、仅放弃等待"显式文档。
- **测试**：`tests/test_graph_planner.py` 风格新增 GuardMiddleware 超时/降级用例。

### WS-8（P2）LLM 客户端缓存治理

- **`packages/agent-core/agent_core/llm/registry.py`**：`_CLIENT_CACHE` 改为上限 64 的 LRU（`OrderedDict`，零依赖）；cache key 中 `api_key` 替换为 `sha256(api_key)` 摘要，密钥不再常驻缓存键。
- **`packages/agent-core/agent_core/llm/protocols.py` 新建**：`ChatModel` Protocol（`invoke / ainvoke / stream / astream`），`FallbackChatModel` 的 primary/fallback 类型标注改用它。
- **`fallback_lc.py`** 不动（组合结构已正确）。
- **测试**：新增 LRU 淘汰与 key 哈希单测；`tests/test_llm_fallback.py` 全绿。

### 完成审计补漏（实施后逐项核对 spec 发现并修复）

| 遗漏项 | 工作流 | 修复 |
|---|---|---|
| `OTelSpanSink` 未实现 | WS-4 | `events.py` 新增类，懒导入 opentelemetry，无活跃 span 时静默 no-op |
| `semantic.py` 散点 `os.getenv` 未迁经配置层 | WS-5 | 5 处改经 `env_str`；新增 `env_str` 助手函数到 `config.py` |
| `ConversationContext.compacted` 回填未接线 | WS-2 | `deterministic.plan` 压缩分支标记 `notes["compacted"]`；`execute_plan` 回填 `ctx.conversation.compacted` |
| `SEMANTIC_MEMORY_TYPED` 默认值应改开 | WS-1 | `config.py` / `typed.py` 默认从 `False` 改 `True`；修复 `test_longterm_h` 中被旧默认值掩盖的 patch 错位 |

## 架构审核落地（2026-08-19 晚）—— Planner/Skill/Runtime 收口

- **PlannerRuntime per-request 隔离（P0）**：`_steps`/`_call_stack` 由实例 mutable state 改为 `contextvars.ContextVar`——异 session 并发互不干扰、同 session 串行共享预算，修复单例注入下「一次执行的预算被并发请求耗尽」的跨请求污染；`max_steps`/`max_skill_depth` 保持不可变配置。
- **配套测试语义修正**：`test_planner_governance.py` / `test_agentic_planner.py` 原「跨多次 arun 累计步数」断言即旧 bug 行为，改为「单次执行内嵌套超限 + 执行结束预算复位」（新增 `test_guard_budget_resets_after_execution`）。
- **SessionCoordinator 语义明确（P0）**：docstring 声明 **process-local 单实例**（`_active/_queues/_conditions` 均 asyncio 进程内状态），多副本下「同 session 串行」不成立；演进方向：分布式 lease / durable execution 持有 ownership（本期不做）。
- **Skill 入参契约真正执行（P1）**：`SkillRegistry.execute()` 新增 `_validate_input()`——`required` 存在性 + `properties` 类型校验，缺 schema 向后兼容、不拒绝注册方注入参数（mcp 的 state/mcp_manager）；传错参数抛明确 `SkillExecutionError` 而非内部 Python exception。新增 3 测试。
- **术语精确化**：`SkillKind.WORKFLOW` 注释与架构文档统一「Static DAG → Workflow（Static/Conditional）」，LangGraph 明确为执行实现。
- **演进方向留档（暂缓重构）**：SkillRegistry/SkillRuntime 分离——写入 `docs/plan-f-single-runtime-multi-planner.md`，按「边界出现再拆」原则执行。`Plan.notes`→显式字段 ✅ 完成、Dynamic Agent 纳入 Skill 体系 ✅ 完成、Workflow Definition→Workflow Skill 编译 ✅ 已实现（2026-09-21）。
- **测试**：根 tests 180 passed（governance 7 + capability registry 16 含契约测试）/ 联邦 unit 89 passed（零回归），ruff 0 error。

## Plan-F 收尾（2026-08-19）—— Capability→Skill 全量 rename

- **命名统一（待用户确认范围：全量重命名）**：将 `agent_runtime/capabilities/` 体系重命名为 `agent_runtime/skills/`，符号 `Capability`→`Skill`、`CapabilityKind`→`SkillKind`、`CapabilityRegistry`→`SkillRegistry`、`CapabilityNotFoundError`→`SkillNotFoundError`、`DuplicateCapabilityError`→`DuplicateSkillError`、`as_function/agent/remote/dag_capability`→`as_function/agent/remote/dag_skill`。
- **保留项（语义不同，不乱改）**：`app/schemas.py` 的 `Capability = Literal[...]`（路由决策选中的能力名）与所有 `decision.capability` / plan payload 的 `capability` key / StreamEvent 的 `capability` payload——它们是「路由决策结果」，非治理 Skill，保持原样。
- 波及 `app/`、`agent_federation/`、`tests/`、`eval/` 共 27 个 `.py`（已排除无关 `dialogue-framework` 巧合命中）；用脚本批量 rename（符号级 + 目录重命名），避免 Unicode 匹配误差。
- **测试**：根 tests **322 passed**（零回归）；`tests/test_capability_registry.py` 13 passed；联邦 unit 87 passed；lint 0 error。

## Plan-F 收尾（2026-08-19）—— WS evidence/memory 桥接闭环

- **`agent_federation/planners/agentic.py`**：`execute()` 现把 `_execute_agent_core` 运行期经全局 `monitor` 发射的运行时事件桥接为 `evidence` StreamEvent（route → evidence* → answer）。新增 `_monitor_event_to_stream_event()`（只读转换，保留 event/message/data 原文）+ `_subscribe_monitor()`（用现有 `monitor.on/off` 临时订阅 `assistant_call`/`tool_start`/`tool_outcome`/`session_created`/`task_result`/`circuit_state_change`/`error`，每个 execute 用自己的闭包+列表，并发安全）。
- **不破坏黑盒契约**：`run_deep_agent` 的 `_execute_agent_core` 内部零改动，monitor 全局 WS 通道（ConnectionManager）不受影响；仅 execute 路径的 StreamEvent 流更丰富（WS 客户端可见子 agent 调用/工具证据/记忆上下文建立）。
- 原 WS 出口统一收尾（第 24 行）标注的「evidence/memory 桥接留作后续」**已闭环**。
- **测试**：扩 `tests/unit/test_agentic_planner.py`（+2 例：execute 桥接 monitor 事件为 evidence；异常路径订阅必注销防回调泄漏）；联邦 unit 87→87（含新增 2 例，原 85 + 新加 execute 桥接共 87）passed。

## Plan-F 收尾（2026-08-19）—— 真实 R1 基线（环境限制，待有 key 环境执行）

- **`agent_federation/eval/run_eval.py`**：`--baseline` 新增前置检查 `_require_real_llm_key_for_baseline()`——`OPENAI_API_KEY` 缺失/占位（test-key/x/sk-test 等）时直接 `sys.exit(2)` 并打印可执行指引，避免在无 key 环境产出垃圾 `fed_latest.jsonl`。
- **当前状态**：开发环境无真实 LLM key，`fed_latest.jsonl` 真实基线**待在有 key 环境执行**——`uv run python -m agent_federation.eval.run_eval --baseline eval/fed_latest.jsonl`；R1 漂移门禁的**比对逻辑本身无 LLM 依赖**，已通过 `tests/unit/test_eval_baseline.py`（4 例）覆盖，可作 CI 门禁。
- **Boundary**：仅加前置护栏，不改 `--compare/--fail-below` 比对语义。

## Plan-F Phase 3 联邦侧收尾（2026-08-19）—— 双轨真正闭环

- **`agent_federation/planners/agentic.py`**：新增 `AgenticPlanner.arun(question, workspace_id, runtime, main_agent=None) -> str`——与 `execute`（供 app SSE 产出 StreamEvent）并存；`async with runtime.skill_guard("agentic")` 包裹 `_execute_agent_core`，将组合治理（max_skill_depth/max_steps）落地联邦主链路；`main_agent` 透传保留动态 agent 选择能力（不进统一协议）。
- **`agent_federation/planners/__init__.py`**：新增 `get_planner_runtime()` 模块级单例（联邦无 FastAPI app.state 注入先例），治理参数取 `FED_MAX_SKILL_DEPTH` / `FED_MAX_STEPS`（默认 4/20，与 PlannerRuntime 默认及 app/config 对齐），`registry=None`（联邦 agentic 不查能力注册表）。
- **`agent_federation/agent/main_agent.py`**：`run_deep_agent` 把 `singleflight(_execute_agent_core, ...)` 改为 `singleflight(AgenticPlanner().arun, ..., get_planner_runtime(), selected_agent)`——保留 singleflight 缓存击穿防护 + 全部副作用链（guard/intent/cache/memory/monitor/remember_episodic/SemanticCache），仅「最终执行」委托给 Planner 协议 + 治理；eval/WS 的 monitor 事件契约零破坏。
- **Boundary**：`deep_agent` subagents 委派机制（`_build_subagents` / `create_deep_agent`）保持不动——Plan-F 目标是「编排收敛」而非「重写委派」，避免破坏现有行为。
- **测试**：扩 `tests/unit/test_agentic_planner.py`（arun 经治理复用 + main_agent 透传 + 步数超限抛 `SkillCompositionError`）；新增 `tests/unit/test_run_deep_agent_planner.py`（run_deep_agent 经 planner.arun 走通 + monitor 上报保留）；联邦 unit 81 passed / 根 tests 322 passed（零回归），lint 0 error。

## Plan-F R1 漂移门禁收尾（2026-08-19）—— 双跑 eval 基线闭环

- **`agent_federation/eval/run_eval.py`**：新增 `--baseline <path>`（本次结果快照为行为基线，只落 `id`/`routed_agents`/`routing_score`/`rubric_rate`，不存 answer 全文）+ `--compare <path>`（逐项对比漂移：exact/jaccard/rubric 退化 + 缺失题，报告漂移率）+ `--fail-below`（漂移率超阈值退出码非零，可作 CI 门禁）；`save_baseline`/`compare_baseline` 抽为独立纯函数。
- 纯数据结构对比，无 LLM 依赖，CI 可守；用法：先 `--baseline` 锁切换后基线 → 后续 `--compare --fail-below 0.05` 守门禁。
- **测试**：新增 `tests/unit/test_eval_baseline.py`（4 例：baseline 快照剥离 + exact/jaccard/rubric 退化 + 缺失题 + clean 无漂移）；联邦 unit 85 passed / 根 tests 322 passed（零回归），lint 0 error。

## Plan-F WS 出口统一收尾（2026-08-19）—— 双轨流式事件同构

- **`agent_runtime/planner/protocol.py`**：新增 `serialize_stream_event(event) -> dict | None`，作为 app(SSE) / 联邦(WS) **共享的单一映射**，消除双轨出口 schema 漂移源。
- **`app/api/routes.py`**：`_stream_event` 委托 `serialize_stream_event`（输出结构不变，消除 app 内硬编码映射副本）。
- **`agent_federation/api/server.py`**：`/ws/{thread_id}` 从 echo/pong 升级为——收 `{"type":"query","text":...}` → `AgenticPlanner.execute` 产 `StreamEvent` → 逐条 `send_json(serialize_stream_event)` → 收尾 `{"type":"done","thread_id","answer"}`；非 query 合法 JSON 回退 pong（保留旧兼容）；`/api/task` 不动。
- **Boundary**：仅统一「事件 schema 出口」，不重写联邦 WS 鉴权/并发/前端协议；evidence/memory 桥接（monitor→StreamEvent）已于同日后续收尾闭环（见上方「WS evidence/memory 桥接闭环」）。
- **测试**：新增 `tests/unit/test_ws_stream.py`（2 例：query 流式收 route+answer+done；非 query 回退 pong，mock execute 免 LLM）；联邦 unit 87 passed / 根 tests 322 passed（零回归），lint 0 error。

## Plan-F 单 Runtime 多 Planner 启动（2026-08-19）

- **方案文档** `docs/plan-f-single-runtime-multi-planner.md`：双轨收敛共识落档——「单 Runtime + 多 Planner」取代 plan-e 的「收敛」表述。含 K1–K5 卡点修正、R0 控制权冲突风险、P1–P5 五个落地契约点、Phase 0–3 路线图。
- **`shared-schemas/shared_schemas/thread.py`**：统一线程状态契约 `ThreadState`（messages 序列化 dict + metadata 编排状态 + version）——双 Planner 共享 checkpoint 的状态兼容基础（契约点 P2）。
- **`agent-runtime/` 新包**（uv workspace 新成员）：运行时中间件层。首个迁移单元 = admission：`app/infra/admission.py` → `agent_runtime/admission.py`，`AdmissionDecision` 类型 → `agent_runtime/schemas.py`；`app/schemas.py` re-export 兼容旧引用，`app/main.py` 改从 `agent_runtime` 引用。
- **验证**：根 tests **261 passed**（排除 wenda/dialogue 既有环境缺失目录）；迁移相关 test_router + test_input_guard_graph 8 passed；`app.main` import ok。
- **Phase 0 完成（同日）**：剩余 8 个运行时模块全部迁入 `agent_runtime.*`——cache / circuit_breaker / coordinator（CoordinationDecision）/ revert（RevertResult）/ mcp_client（McpServerConfig/McpToolResult）/ otel / tracing / db。`app/schemas.py` 对 4 个运行时类型 re-export 兼容；`app/infra/` 9 模块全部删除，仅留空包占位（退役标记）。
  - **配置依赖倒置**：`db.init_pool(database_url, db_pool_max_size)` / `db.ensure_schema(pool, vector_dim)` / `tracing.get_langfuse_callbacks(public_key, secret_key, host)`——agent-runtime 零依赖 `app.config`，参数由 app lifespan / scripts 从 Settings 注入。
  - 调用点全量更新：app 内部 8 文件 + scripts 3 个 + tests 4 个，改从 `agent_runtime.*` 引用。
  - 验证：根 tests **261 passed（零回归）**，`app.main` import ok，lint 0 error。
- 不做（遵循不过度设计）：`db.py` 的 `SCHEMA_TEMPLATE` 已随迁移归位（建表职责属 agent-runtime 初始化）；联邦 3 个 unit error 为 `deepagents` 改名遗留（测试文件仍 import PyPI `deepagents` 包），与本变更无关。

## Plan-F Phase 1 能力层中立化（2026-08-19）

- **`agent-runtime/agent_runtime/capabilities/` 新包**：`Capability` + `CapabilityRegistry`（注册/发现/统一执行入口，超时边界收敛于 execute）+ 三执行器工厂——`as_function_capability`（进程内 async 函数）/ `as_agent_capability`（subagent dict → lazy `deepagents.create_deep_agent`，与联邦本地 fallback 同路径）/ `as_remote_capability`（远程子服务调用）。
- **`app/capabilities.py`**：装配 search/rag/sql/mcp 四能力为 function 型注册项（惰性单例）；`app/agent/graph.py` 四节点改经 `registry.execute(...)`——能力层中立化首个生产路径验证。
- **测试**：`tests/test_capability_registry.py` 7 例（注册/发现/重复注册/未知能力/超时/三执行器）；根 tests **268 passed**（261 基线 + 7 新增，零回归），lint 0 error。
- 不做（遵循不过度设计）：联邦 `main_agent.py` 委派路径未改（deep_agent subagents 机制属 Phase 2 Planner 协议切换范围）；`Capability.metadata` 仅留扩展位不预填；MCP 能力签名依赖 state+manager 以 kwargs 透传承载，不强行重构为 query 形态。

## Plan-F Phase 1.5 Skill 契约升级（2026-08-19）

- **`agent-runtime/agent_runtime/capabilities/registry.py`**：`CapabilityKind` 增 `WORKFLOW`；`Capability` 增 `input_schema` / `output_schema`（JSON Schema dict，可空）；新增 `to_tool_schema()`（供 Agent 工具描述生成 + 入参契约显式化）。
- **`capabilities/dag.py` 新建**：`as_dag_capability(...)` → kind=WORKFLOW，把确定性 DAG 执行器封装为可注册 Workflow Skill（Static DAG Executor，对应 §4.1）。
- **`app/capabilities.py`**：定义 query/rag/general_qa 四套 JSON Schema 契约；`build_registry(graph=None)` 注入 graph 时注册 `general_qa` Workflow Skill（graph.py **包装非删除**），`get_registry` 惰性单例。
- **测试**：`test_capability_registry.py` 扩至 13 例（schema 契约 + WORKFLOW + general_qa 装配），零回归。

## Plan-F Phase 3 单 Runtime 成型（2026-08-19）

- **`agent_runtime/planner/protocol.py`**：新增 `SkillCompositionError` + `PlannerRuntime.skill_guard`（max_skill_depth=4 / max_steps=20 / 循环检测），仅 agentic 组合路径使用。
- **`app/memory/thread_persist.py` 新建**：`read_thread_messages` / `append_thread`——经 checkpoint aget_tuple/aput 落消息历史（channel_versions 推进 + new_versions 落 blob；空 answer/no checkpointer/thread 间隔离均正确 noop）。
- **`app/api/routes.py`**：`/query` 切 Planner 主路径（`PlannerContext`→`plan`→`execute`→StreamEvent→SSE 映射）+ graph 兜底 + 历史写回 checkpointer；新增 `_stream_event` 统一出口。
- **`app/main.py` / `app/config.py`**：lifespan 装配 `registry` + `planner_runtime`；配置增 `max_skill_depth` / `max_steps`。
- **测试**：新增 `test_planner_governance.py`（6）/ `test_thread_persist.py`（6）；根 tests **全量回归 322 passed（零回归）**，lint 0 error。
- 不做（遵循不过度设计）：WS 出口统一延后（app 现仅 SSE）；`version`/`risk_level`/`policy` 元数据暂缓（单实例无多租户分级诉求）。

## v2 Resilience 收敛（2026-08-19）

- **`agent-core/agent_core/resilience.py` 新增 `retry_async`**：异步指数退避重试原语（`max_attempts` 含首次、退避 `base*factor**(n-1)`、`exceptions` 过滤、可注入 `sleep`、支持同步/异步 `on_retry` 回调），与同步 `retry` 语义对齐。
- **`agent_federation/agent/async_subagents.py`**：`DelegatingSubAgent.ainvoke` 手写重试循环 → 内核 `retry_async`（行为等价：`max_attempts=RETRIES+1`、退避 `base*2**attempt`、成功即 `record_success`+返回、全败计入熔断并走本地 fallback），消除手写指数退避样板。
- **测试**：`test_resilience.py` 新增 8 例；agent-core 全量 146 passed；federation 契约测试 8 passed；行为等价验证 4 场景（首次成功 / 失败 1 次后成功 / 全败走 fallback / 熔断短路）。

> 不做的（遵循不过度设计）：Resilience Policy 三件套组合对象（Retry+Timeout+CB+Fallback）当前无真实「嵌套组合」调用点，待出现第 3 个组合需求再提取；`app/rag/rerank.py` / `zhanggui-zhiku` 的重试带 HTTP status-code 语义（429/5xx 才重试），与内核「按异常类型」语义不同，强行替换属过度设计。

## v2 TB 核销（2026-08-19）

- **TB-11 第一步落地（配置体系盘点）**：`agent_federation/README.md` 环境变量表重写 + `.env.example` 以源码为真相源全量盘点 80+ 开关（含共享内核 `agent_core.memory.*` 11 项）。修正 `SUBAGENT_RETRY_BASE` 默认值偏差（1.0→0.5，与 `async_subagents.py:153` 一致）；移除源码中已不存在的过时 `MYSQL_POOL_RESET_SESSION`；补全缺失开关：`KEFU_SERVICE_URL`/`KEFU_USE_ADAPTER`/熔断 `CB_*`×5/缓存 `KB_VERSION_*`×3/`TENANT_ID`/`RAGFLOW_*`/`EMBEDDING_DIM`/`DEEPAGENTS_DB_POOL_MAX`/`DATABASE_URL`/`EMBEDDING_API_KEY`。
- **审查核销**：优化 H（ADR-0004 阶段 1~3 已下沉内核 `agent_core.memory.typed`，D1~D5 全落地）、TB-9（意图分类收口内核 `agent_core.intent.classify_intent`，`intent_bridge.py` 单一真源）、TB-10（联邦已挂 typed 长期记忆 + 内核 checkpointer 三态）、TB-12（两轨缓存均实现 `BaseSemanticCache` 统计接口）状态已在 `docs/architecture-improvement-plan.md` 登记核销。
- 不做（遵循不过度设计）：agent_federation 配置全量迁移 pydantic-settings 属大 churn 且无真实复用需求，保留为长期项（待出现第 3 个配置消费方）。

## v2 分支修复记录（2026-08-16）

### 安全 / 护栏
- **#1** `app/agent/graph.py`：输入护栏拦截改为短路（`route:"blocked"` → `END`），拦截文案不再被 `synthesize_node` 覆盖；拦截不进记忆，避免原文落库。
- **#2** `app/agent/graph.py`：脱敏文本写回 `state.question`，下游路由/记忆均使用脱敏内容。
- **#4** 新增 `tests/test_input_guard_graph.py`：护栏拦截短路 / 脱敏传播 / guard 关闭透传 3 例回归。

### 工程 / 配置
- **#3** `pyproject.toml`：`ruff.lint.select` 显式固化 `["E4","E7","E9","F","I"]`，避免默认 select 漂移关闭 isort。
- **#7** `deepagents/requirements.txt`：补 `-e ../shared-schemas` 与 `sqlglot>=25.0`（非 uv 用户备选安装）。
- **#9** 核验：`FallbackChatModel` 默认 `failure_threshold=3`，降级阈值正确。
- **#11** `docs/architecture-improvement-plan.md`：「核验维持现状」记录项；原登记优化 A/B 要点2（`_validate_state`/`guard_middleware`）未实施已过时，参见下方「双轨技术债收敛」更正。
- **#14** 删除 `zhanggui-zhiku/uv.lock`，统一到 workspace 根锁。

### 核验维持现状（非缺陷）
- **#5** 路由结构化输出恒绑主模型，但 `decide_route` 已有启发式兜底，不阻塞。
- **#6** fallback `stream` 重播缺陷，app 链路未用 stream，待启用时再修。
- **#8** SQL 守卫 `max_rows`（默认 100）为有意的防护上限，非缺陷。
- **#12** `make type` 为 ruff 别名，非缺陷。
- **#13** `rag_query` 优先走 `AsyncSubAgent`，httpx 仅兜底，影响窄。
- **#15** logger 命名已规范（`__name__` + 顶层 `agent_core`），非缺陷。

### P4 双轨收敛（先前提交）
- P4.1 `shared_schemas` 契约断言（`AsyncSubAgent` 返回 `QueryResponse`）。
- P4.2 SQL 守卫下沉 `agent_core`（`deepagents/tools/sql_guard.py` 委托内核）。
- P4.3 `MemoryBackend` Protocol 抽象（`agent_core.memory`）。

### 技术债 TB 闭环（2026-08-16）
- **TB-4** `agent-core/agent_core/cache/base.py`：新增 `BaseSemanticCache` Protocol + `build_cache_key` 纯函数（sha256 of `intent|rewritten_query|kb_versions|tenant_id|gray_pct`），`deepagents` 复用，消除本地缓存键实现分歧。
- **TB-5** 语义缓存键契约固化（随 TB-4 一并收敛）。
- **TB-6** `deepagents/agent/async_subagents.py`：新增 `_normalize_response` + `_E1_CONTENT_ASSERT`，kefu 契约双向核验（形状 + 内容非空）；`kefu-service` 显式 `fallback=False`。
- **TB-8** `eval/run_eval.py`：加 `--require-llm`（环境不可达 SKIP 退出码 2）、默认 `--fail-below 0.8`；`Makefile` 评测改直接路径 `eval/run_eval.py`（避开 deepagents 同名模块冲突）。
- **TB-7** `docker-compose.yml`：为 `agent-platform` 补 healthcheck（TB-7 端到端冒烟可判定就绪）；`Makefile` 增 `compose-smoke`（需 Docker）；`scripts/smoke_memory.py` 提供无 Docker 的等价内存模式预热冒烟；说明见 `docs/tb7-smoke.md`。
- **TB-1** `dialogue-framework/shared/llm/core_adapter.py`：新增 `LLMCoreClient`，把 agent_core `BaseLLMProvider`（工厂协议）桥接为 DF `BaseChatClient`（运行时协议）；`BaseChatClient` 标记 `@runtime_checkable`，docstring 明确两者互补不合并。`langchain_client.py` 标注其 `FallbackChatModel` 即内核协议实现。
- **TB-2** `dialogue-framework/core/tracker_memory.py`：新增 `TrackerConversationMemory`，实现 agent_core `ConversationMemory` 协议（save/get_recent/clear/update），把 user/assistant 消息落进 `Tracker.events`；`Tracker.to_conversation_memory()` 桥接挂载。`dialogue-framework/tests/test_tb_bridge.py` 覆盖两协议桥接（3 passed）。

> 红线：dialogue-framework 不合并 / 删除，仅做协议对齐桥接（TB-1/TB-2 均满足，未改动 DF 自有数据结构与对外接口）。
> 至此 TB-1~TB-8 全部闭环。

### 双轨技术债收敛（2026-08-16 后续，commit 2bd215c + a6108c7）
- **优化 A 要点2** `app/agent/state.py` + `graph.py`：`AgentState.route` 由裸 `str` 枚举化为 `Literal["search","rag","sql","direct","mcp","blocked"]`（与 `graph.py` 条件分支键一一对应，非法路由值由 Pydantic 即时拦截）；新增 `_validate_state()` 入口校验（非空 `question`），在 `route_node` 调用。`tests/test_agent_state.py` 增 3 例。
- **优化 B 要点2** `deepagents/gateway/guard_middleware.py`（新增）+ `deepagents/agent/main_agent.py`：新增 `GuardMiddleware(AgentMiddleware)`，在 `before_agent` 钩子对入口 user 文本做 PII 脱敏改写 + injection 拦截；`_build_middleware()` 按 `GUARD_ENABLED` 开关注入（带失败降级），deepagents 视图 agent 默认经输入护栏。`deepagents/tests/unit/test_guard_middleware.py` 增 5 例。
- **TB-4 key 闭环** `app/infra/cache.py`：`_cache_write` 的 `cache_key` 由明文 `question.strip().lower()` 改为内核 `build_cache_key(intent="", rewritten_query=...)`，与 deepagents 共用同一 hash 逻辑（lookup 端纯向量命中，不受影响）。
- **U-1 收敛** `app/schemas.py`：普查确认无生产客户端仍发旧名 `question`/`thread_id`（deepagents `run-all.py` 调 adapter `/query` 已用标准名 `query`），**彻底移除** `AliasChoices` 双写兼容，入站契约收敛为纯标准名 `query`/`session_id`；清理未使用 `AliasChoices` import。`tests/test_api_smoke.py`、`agent-core/tests/test_guardrails.py` 示例字段名同步改 `query`。内部 `AgentState.question` 为 graph state 字段，与入站契约无关，保持不动。
- **文档一致性** `docs/architecture-improvement-plan.md`：§6.1 TB-1/TB-2 标注为「已落地（桥接）」；§6.2 U-1 标注「已闭环」；优化 A/B 标题回升「✅ 已落地」；#11 勘误回填。

## eval golden 已增至 15 条（2026-09-22）

> eval golden 集已增至 **15 条**（原 12 条）。上方历史条目中的 "eval 12/12" 为当时事实记录，按历史保留不改。


