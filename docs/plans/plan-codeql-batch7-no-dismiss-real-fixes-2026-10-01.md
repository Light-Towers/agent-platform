# CodeQL Batch 7：取消 dismiss 通道，剩余告警全部真修

> 状态：**B7a 已执行**（#34 / #43 / #44 真闭合；#42 未消除，位移重开为 #47）→ **B7c 已执行并验收通过**（PR #39 合入 `bb46dd3`，主干重扫 **#47 真消失、无新号重开**，main open 3 → 2）；**B7b 已拍板走 principal_id 化**（待另立方案与 PR，本方案不动 `auth.py`）；**B7d 新增**（v3 合流后主干复验发现新告警 **#48**，见 §7）
> 日期：2026-10-01　触发：用户明确「不要用 dismiss 这种简单的处理方式」
> 前置：Batch 1-6 见 `plan-codeql-codescanning-remediation-2026-10-01.md` 与 `plan-codeql-batch6-kernel-sanitizer-models-2026-10-01.md`

## 1. 本批约束

1. **不使用 dismiss**。任何一条都不以「面板关闭 + 理由」收尾。
2. 修不动的**如实报告为未解**，不用假模型、不改命名规避检测器、不做路径级查询排除来伪装成"已解决"。
3. 每条必须有客观依据（当前 open 事实 + 官方 query help 的判定口径），不凭记忆下结论。

## 2. 当前事实（`refs/heads/main`，2026-10-01 取，共 6 条）

| # | rule.id | 位置 | 官方判定口径要点 |
|---|---------|------|------------------|
| 34 | `py/weak-sensitive-data-hashing` | `applications/agent_federation/gateway/gray.py:40` | 查询只在「对敏感数据用弱哈希」时报；**非口令场景推荐 SHA-2** |
| 38 | `py/weak-sensitive-data-hashing` | `packages/agent-core/agent_core/guardrails/auth.py:92` | 把输入归类为 **password**（限定输入空间 → 需慢 KDF）；SHA-2 在非口令场景本是 GOOD |
| 39 | `py/weak-sensitive-data-hashing` | `packages/agent-core/agent_core/guardrails/auth.py:117` | 同上 + 12 hex 截断 |
| 42 | `py/path-injection` | `packages/agent-core/agent_core/guardrails/fs.py:162` | 污点在守卫**之前**抵达 sink |
| 43 | `py/clear-text-logging-sensitive-data` | `packages/agent-core/agent_core/guardrails/fs.py:93` | 日志表达式含被归类为 **secret** 的值 |
| 44 | `py/clear-text-logging-sensitive-data` | `packages/agent-core/agent_core/guardrails/fs.py:103` | 同上 |

补充取证：官方 query help（`py-weak-sensitive-data-hashing`）**未提供** `usedforsecurity=False` 之类的豁免口子；Python 可自定义的 9 种 sink kind 不含 password-hashing 与 clear-text-logging → 这两类**无法用模型包解决**，只能改代码（此结论已在 Batch 6 记录，本批据此行动）。

## 3. B7a：三条真修（本批执行）

### 3.1 #34 灰度分桶哈希：MD5 → SHA-256

- **依据**：官方对「非口令场景」的直接建议就是 SHA-2；且 CodeQL 把 `user_id` 视为可识别信息（query help 明确列举 usernames）。
- **影响面实测**：`_get_gray_pct()` 默认 `"0"`（灰度关闭）；`is_in_gray` 在**产品代码中无调用点**（仅 `tests/unit/test_guards.py`），分桶结果不落库、不持久化 → 换哈希函数导致的人群重排无生产影响。
- **验收**：`test_deterministic` / `test_distribution`（30% 时 2700~3300）必须仍通过——SHA-256 均匀性满足；不新增豁免。
- **回滚**：单行还原。

### 3.2 #43 / #44 路径护栏日志：不落任何路径文本

- **根因（首轮假设，已被下面实测推翻一半）**：`_reject` 打 `base=%s`（`root`，来自调用方经 env/配置解析出的部署目录）、`_ensure_within` 打 `resolved=%r`（同样以 `root` 为前缀）。当时认为 CodeQL 把 env/配置派生值归为 secret。
- **真修（经实测修正两次，以下为本批终态）**：日志**不再落任何路径文本**，只留「拒绝原因 + 不携带原文内容的数值型结构摘要」（`len` / `fragments` / `absolute`）。
- **实测过程（重要，此为证据而非推测）**：第一版只去掉 `base=%s` 与 `resolved=%r`、保留 `input=%r`。PR #38 的 `CodeQL` 检查报 **2 new alerts (high)**，注解位置为 `fs.py:99` / `fs.py:110`（即同两处 logger 位移后的新行号）。两处语句此时只剩「字面量 reason + 入参」⇒ **被判 secret 的是入参本身**。消除法结论与 Batch 6 方案 §5 的先前假设一致：路径里经 `resolve_thread_id(thread_id, api_key)` 带入凭证派生的会话目录名 `session_user-<HMAC(api_key)>`，故**这不是误报**。
- **官方口径**：`py/clear-text-logging-sensitive-data` 的 Recommendation 只有一句“Sensitive data should not be logged”，**未提供** masking / 哈希摘要之类的豁免→ 采取“不打”而不是赌“打了但不可逆”。
- **契约变更与代价（如实记录）**：Batch 3 定的「留痕含原文」就此改为「不落路径文本」。排障路径改为：从接入层访问日志取完整 URL（`?path=` 本就在其中），或用同一入参本地复跑。结构摘要仍足以区分拒绝形态与量级。`applications/agent_federation/api/server.py` 中依赖旧语义的注释同步修正。
- **测试断言方向反转的说明**：两条日志回归用例由「断言原文在内」改为「断言原文不在内 + 断言 reason 与 `len=` 在内」——依据是上述官方口径与实测，**不是为凑绿而收窄**（新断言比旧断言多两项）。
- **契约审计（首轮前）**：全仓 `*.md` 与 `packages/agent-core/tests/test_guardrails_fs.py` 均未断言这两行日志文案（已 grep 确认），因此改动不打破外部可见契约。
- **额外收益**：不再把用户可控文本原样拼进日志，同时降低 `log-injection` 面（该 kind 属可建模清单，但我们选择不用模型糊弄）。
- **回滚**：`_reject` / `_ensure_within` 的日志参数还原为 `%r` 原文形式（并可删 `_input_shape`）。

### 3.3 #42 `resolve_within`：解析前加词法包含守卫（**执行结果：未消除，位移重开为 #47**）

- **原判断**：`:160` 拼出 candidate → `:162` `resolve()`（sink）→ `:166` 才做 containment，守卫必然晚于 sink；把 containment 提到 `resolve()` 之前即可让 sink 落入守卫之后。
- **真修动作**：在 `resolve()` 前加纯词法 `candidate.is_relative_to(root)` 判定，解析后仍复检一次。
- **实测结论（2026-10-01 主干重扫，`a660220`）**：#42 `state=fixed`，但同规则在 `fs.py:187` 新开 **#47**。`git show 903c744^` 与面板行/列号比对确认：#42 的 `:162` 与 #47 的 `:187`（col 20 均指向接收者 `candidate`）是**同一语句** `resolved = candidate.resolve()`。即本动作**只是把行号挪了，没有消除告警**。
- **撤回的话**：据此，「本改动推翻了 Batch 6 对 #42『结构不可消除』的判定」这一说法**证据不成立，撤回**。词法前置本身是真实的纵深改进（不再对未验证入参做文件系统遍历），作为 B7c 的一部分**保留**，但它不是消除告警的手段。
- **保留的副作用说明**：`PathTraversalError` 的原因字符串对"明显越界"输入可能由 `路径无法解析`（原经由 resolve OSError 分支）变为 `路径越出基准目录`；异常消息不回带路径，对外 403 文案固定不回显原文（`tests/test_file_endpoints.py` 覆盖），对外契约不变。

### 3.4 B7c：#47 按官方编码形状重写 `resolve_within` 的校验顺序

先取回**机制证据**（不凭记忆：以下均从 `github/codeql` main 分支源码直接拉取）：

- `PathInjectionQuery.qll`：该查询是**带状态**的污点追踪（`TaintTracking::GlobalWithState<PathInjectionConfig>`，状态 `NotNormalized` / `NormalizedUnchecked`），注释原话 *“Such checks are ineffective in the `NotNormalized` state”* —— **只做前缀包含判定不够，必须先经过被识别的规范化**。
- `Stdlib.qll` 中 `Path::PathNormalization::Range` 的实现**只有三个**：`os.path.normpath` / `os.path.abspath` / `os.path.realpath`。`pathlib.Path.resolve()` **不在其中**，而它本身是 `FileSystemAccess` 的 path 参数 sink（`PathInjectionCustomizations.qll` 的 `FileSystemAccessAsSink`）—— 这才是 `:187` 一直被报的根因，也是 Batch 6「结构不可消除」错觉的来源。
- `Stdlib.qll` 中 `Path::SafeAccessCheck::Range` 的默认实现**只有一个形状**：`str.startswith`（`checks(调用接收者, branch=true)`）。我们的 `Path.is_relative_to` 检测器完全不认。
- 扩展点不可用：`PathInjectionCustomizations.qll` 开放 `PathNormalization::Range` / `SafeAccessCheck::Range` / MaD `barrierNode(this, "path-injection")`，但 default setup 下只能交**模型包**（MaD），而模型只能作用于**调用点**的返回值/入参，**消不掉 helper 函数体内部**的 sink。⇒ 本条只能改代码，与 §2 的结论一致。

⇒ 官方编码的安全形状是：**`os.path.normpath` 词法规范化 → `startswith` 前缀守卫 → 之后才允许接触文件系统**。我们此前从未走过这个形状（直接 `Path(raw)` → `resolve()`）。

**修法**（`resolve_within`，四步）：
1. `norm = os.path.normpath(os.path.join(str(root), raw))`：纯词法，不访问文件系统（官方文档明确 normpath 不触碰 FS）；相对/绝对入口均由 `os.path.join` 统一成绝对形式。
2. `if norm.startswith(root_str) and (norm == root_str or norm.startswith(root_str + os.sep))`：`startswith` 是被识别的 `SafeAccessCheck`；第二个合取项补**分隔符边界**，排除 `/data/root_evil` 被当成 `/data/root` 子路径的兄弟前缀误判（naive startswith 的真漏洞）。
3. 通过 ①② 后才 `Path(norm).resolve()`，随后**保留** `_ensure_within` 解析后复检（挡符号链接逃逸）。
4. POSIX 反斜杠二次解释改为**纯词法**否决（不再 `root.joinpath(...).resolve()`）：主解释已做过解析后复检，反斜杠解释的职责只是挡「宿主语义误读」，无需第二次触碰文件系统——顺带消掉该处同源的潜在 sink。

**接受集不变的差分实测**（不是推演）：用 `posixpath` + `PurePosixPath` 在本机模拟 POSIX 宿主，对 42 个入参（含全部现有用例 + 穿越/绝对/UNC/盘符/混合分隔符/NUL/空白/兄弟前缀等边缘）同时跑**旧版（main a660220）**与**新版**裁决：
- `sub/a.txt` / base 内绝对路径 / `a/../b.txt` / `.` / `/data/warehouse`（base 自身）→ 两版均放行。
- `/etc/passwd`、`C:\\...`、`../outside.txt`、`..\\..\\outside.txt`、`sub/../../outside.txt`、`/data/warehouse_evil/x.txt`、空/空白/NUL → 两版均拒。
- **差异 0 / 42**。特别提醒：原先根据直觉写下的「lone `\` 入参改拒」并不成立——`posixpath.join(root, "\\")` 会自动插入分隔符得到 `root + "/\\"`，仍在边界内，两版均放行（已写成回归用例固定）。
- **唯一一处真收紧（仅 Windows 宿主）**：大小写变体的绝对入参。旧路径靠 `Path.is_relative_to`（nt 下 `normcase` 不区分大小写）放行，新路径靠 `startswith` 区分大小写 → 拒绝。方向为变严；该形式不可能由 `/api/files` 列出的结果产生（服务端拼出的串与 `root_str` 同构），全仓 `*.md` 与测试无断言。已用 `skipif(sys.platform != "win32")` 用例固定。
- 符号链接逃逸路径本机无法验证（无 Linux/docker），靠现有 `skipif win32` 用例在 CI 的 Linux runner 上实跑。
- **验收**：`test_guardrails_fs.py` 现有穿越/NUL/绝对/异平台用例全绿；新增：base 自身放行、兄弟前缀被拒、`..` 定形后不得进入 `resolve()`、反斜杠解释越界被拒且不新增 `resolve()` 调用、lone-`\` 仍放行、Windows 大小写变体拒绝。判定以 PR 作用域的 `CodeQL` 检查 + 合入后 `refs/heads/main` 重扫为准（本机无 CodeQL CLI）。
- **回滚**：`resolve_within` 函数体回到 3.3 节描述的形式（`candidate = p if p.is_absolute() else root / p` 三连判定）。

## 4. B7b：两条待拍板（不在本批动代码）

#38 / #39 的核心不是算法选错，而是**「把 API Key 摘要成用户标识」这个模式本身**被 CodeQL 判为口令哈希场景。三条出路：

| 选项 | 内容 | 代价 | 评价 |
|------|------|------|------|
| **B7b-1（推荐）** | **principal_id 化**：认证后使用服务端签发/存储的不透明主体 id 派生 thread id，密钥不再进哈希；#38 与 #39 同时**真消失** | 会话目录命名迁移（可复用 `scripts/migrate_thread_identity.py` 框架）、鉴权中间件需主体映射、联邦各服务契约核对 | 与 ADR-0007「服务端断言租户身份」同向，属真实架构改进 |
| B7b-2 | 先执行历史会话迁移，**迁移完成后删除 `legacy_thread_id`**（消 #39）；#38 继续留 open | 需部署侧动作；#38 不解决 | 诚实但不完整 |
| B7b-3 | default setup 的 query-suite 按路径排除这两个查询 | 会同时屏蔽该文件未来的真实同类问题 | **不推荐**：这是"看不见"而非"修好了" |

不选：改用 scrypt/pbkdf2（把高熵密钥当口令做慢哈希，热路径纯损失，且使摘要与既有会话全部漂移）；改名 `secret`→其它以规避名称启发式（藏而非修）。

## 5. 批次与验收流程

1. 本 PR（B7a）：lint 门禁 + 定向测试 → 合 main → **主干重扫**按 alert number 做集合差。
2. 判定标准：闭合的必须 `state=fixed` 且 `dismissed_at=None`（自动闭合）。
3. 未闭合的：写进 `docs/TODO.md` §8，状态从「待 dismiss」改为「**未解，原因与下一步**」，**不点 dismiss**。
4. B7b **已拍板：principal_id 化**（认证后使用服务端签发/存储的不透明主体 id 派生 thread id，密钥不再进哈希）。另立方案与 PR，涉及会话目录迁移 + 主体映射存储 + 联邦契约核对；本方案不动 `auth.py`。

## 6. 本批验证记录

- PR #38 首轮（仅去 base 的版本）：`Analyze (python)` / `Analyze (actions)` / `ci` / `ha` 均 pass，`CodeQL` 检查 fail——**2 new alerts (high)**，注解 `fs.py:99` / `fs.py:110`；`raw_sarif` 不经 REST 暴露（分析详情无该字段），改用消除法定位。本轮未合入。
- PR #38 次轮（不落路径文本 + `_input_shape`）本地实测：`lint_architecture.py` exit 0（P2/P4-2/P5/P6/P7/P8 全过）；`check_doc_sync.py` 0 警告；分 session 实跑 agent-core **281 passed / 3 skipped**、根 `tests` **500 passed / 17 skipped**、联邦 **152 passed**；`ruff check` 无告警。（本机无 CodeQL CLI，告警是否闭合以 PR 检查与主干重扫为准。）
- 已回填：PR #38 次轮（`cab1eda`）**全 checks pass 含 CodeQL** → 合入 `a660220`；`refs/heads/main` 重扫（`/language:python` results=3、rules=43）后 **open 6 → 3**。
- 逐条定性（`state=fixed`、`fixed_at` 有值、`dismissed_at=None`，即**自动闭合，本轮未使用任何 dismiss**）：#34 ✅ 、#43 ✅ 、#44 ✅ ；#42 旧号闭合但同规则位移重开为 **#47 `py/path-injection` @ `fs.py:187`** → 见 §3.3 结论与 §3.4 修法；#38 / #39 仍 open → 走 B7b。
- **B7c 已回填・验收通过**：
  - PR #39（head `0db4ed1`，4 文件 +173/−38）：`Analyze (python)` / `Analyze (actions)` / `CodeQL` / `ci` ×2 / `ha` ×2 **全 pass**；推送前跑了 L3 深度安全审查，findings 0。合入为 merge commit `bb46dd3`（2026-10-01T11:42:39Z）。
  - 主干重扫：`refs/heads/main` 上的 default-setup 分析（`dynamic/github-code-scanning/codeql`，run #42）`Analyze (python)` / `Analyze (actions)` 均 completed/success；分析完成时刻 11:44:14Z 晚于合入时刻，确认是针对 merge commit 的重扫而非旧结果。
  - **#47 真消失（不是位移重开）**：`state=fixed`、`fixed_at=2026-10-01T11:44:14Z`、`dismissed_at=None`；同时全仓告警最大号仍为 **#47**，合入时刻之后**无任何新建告警**（号段 1..47，缺号 45/46）→ 同一 sink 未在新行号重开。
  - `refs/heads/main` CodeQL 告警总账：**45 条，`fixed` 43 / `open` 2**，open 仅剩 **#38 / #39**（`py/weak-sensitive-data-hashing` @ `guardrails/auth.py:92`/`:117`）→ 待 B7b。**43/43 闭合均为自动（`dismissed_at=None`），全仓零人工 dismiss。**
  - 取证脚本：`.codeartsdoer/temp/verify_main_rescan.py`、`.codeartsdoer/temp/verify_no_new_alert.py`（告警按 `ref=refs/heads/main` 过滤；`state` 三段 open/closed/dismissed 并集去重）。

## 7. B7d：合流后主干复验发现的新告警 #48（本批执行）

### 7.1 事实（`.codeartsdoer/temp/verify_main_rescan_v3.py` 实取，非推演）

v3 身份层合流（PR #41，merge commit `889d417` → `a660e76`，2026-10-01T13:00:43Z）后回主干复验：

| 项 | 实测值 |
|---|---|
| 主干 `ref=refs/heads/main` 告警分布 | **open 3 / fixed 43 / dismissed 0**（预期 open 2） |
| 新增号 | **#48** `actions/missing-workflow-permissions`，`created_at=2026-10-01T12:55:08Z`（PR CI 期间）、`updated_at=13:01:20Z`（主干重扫复现） |
| 位置 | `.github/workflows/ha-assembly.yml:30-56`（job `assembly` 体） |
| 引入源 | `70f2b83`（经 merge 第二父进来，即 **v3 侧提交**新增该 workflow），`git diff --name-status b67546d 889d417 -- .github/workflows/` = `A .github/workflows/ha-assembly.yml` |
| #38/#39 位移核对 | 无位移：`auth.py:92` col=47 / `:117`，仍 open |
| 合入时刻之后新建告警 | 0（#48 创建于合入之前，属本 PR 自身带出） |

⇒ 合流**确实新增了 1 条告警**，方案 §5-5 的硬指标未达成，按同一约束处置：**真修，不 dismiss**。

### 7.2 目标与全局口径

只把被点名的那一行补上权限块即可让 #48 归零，但那是散点式做法（AGENTS.md「横切关注点三层齐备」）。故按三层落地：

| 层 | 内容 |
|---|---|
| **单一实现（约定）** | 仓库既有约定即为「顶层 `permissions: contents: read`」——审计 4 个根 workflow：`agent-platform-ci.yml:49` / `eval-llm.yml:23` / `ha.yml:35` 三处已在位，**`ha-assembly.yml` 是唯一漏接者**（顶层与 job 级均无）。修法为对齐既有约定，不新发明。 |
| **全局装配** | workflow 是声明式的，无装配点；由下一条的 lint 不变量承担「构造保证不漏接」。 |
| **强制门禁** | 新增 **P11**：`scripts/lint_architecture.py` 扫 `.github/workflows/*.{yml,yaml}`，**缺顶层 `permissions:` 块**或取值为 **`write-all`** 即 CI 失败。白名单为空（无存量豁免）。 |

**P11 判据口径（为何只要顶层）**：GitHub 对未声明 `permissions` 的 job 会回落到组织/仓库默认（常为读写），job 级声明容易漏且不可核；顶层声明由构造保证覆盖该 workflow 全部 job。确需某 job 提升权限时，在 job 级单独声明即可，顶层块仍不得省略。

**实现约束**：沿用 `lint_architecture.py` 既有性质——**只走 stdlib**（`re`/`sys`/`tomllib`），不因本门禁引入 PyYAML（venv 里虽因 `agent_federation`/`nl2sql-service` 声明而存在，但脚本需能在无依赖环境直跑）。YAML 语法本身的校验不属本门禁职责（已由 GitHub 侧与一次本地 `yaml.safe_load` 取证完成：4 个根 workflow 均解析通过且顶层 `permissions={'contents': 'read'}`）。

### 7.3 影响面与运行侧风险

- `ha-assembly.yml` 实际用量：仅 `actions/checkout@v4` + `docker compose` 本地构建/起服务 + `curl` 打 `/health`，**不上传 artifact、不发 PR 评论、不写仓库** ⇒ `contents: read` 是它所需最小面，收敛不会让它跑不动。
- 存量佐证：该 workflow 在 PR #41 的 `assembly` ×2 job 已 pass，而当时 token 权限比 `contents: read` 更宽——收窄后所需能力是它的子集。
- 无数据迁移、无对外契约变更、不改任何默认值。

### 7.4 验收标准（合入后回主干复验）

1. **#48 `state=fixed`**、`fixed_at` 有值、`dismissed_at=None`（自动闭合）。
2. 主干 `ref=refs/heads/main` **open 回到 2**，且仅剩 #38/#39，位置不变。
3. 全仓最大告警号仍为 **48**（修复本身不得引入新号），合入时刻之后新建告警 = 0。
4. `lint_architecture.py` exit 0 且 P11 在位；P11 治理用例含**正反例 + 当前树零违规 + 临时根探针验扫描面**（与 P6/P6-2 同构）。
5. 三层齐备第③层不得缺席：若只改 workflow 不加 P11，本批不算完成。

**不选**：dismiss（含 `wont_fix`／`allowlist`）；在 default setup 里按路径排除 `actions/*` 查询（看不见而非修好了）；把权限写成 `write-all` 求个「不报」。
