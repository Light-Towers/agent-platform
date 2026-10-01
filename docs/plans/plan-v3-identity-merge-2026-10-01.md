# v3 身份层合流 main（B7b principal_id 化的前置）

> 状态：**已拍板并在执行中**（§8 三项均按推荐值接受；merge 已在 `integration/v3-into-main` 完成冲突解决与本地实跑，结果记 §9；尚待 PR/CI/CodeQL 验收）
> 日期：2026-10-01　触发：用户在 B7b 落地上拍板「先合流 v3 身份层，再做 principal_id 化」
> 关联：`docs/plans/plan-codeql-batch7-no-dismiss-real-fixes-2026-10-01.md` §4（B7b）、`docs/TODO.md` §8

## 1. 为什么必须先合流

CodeQL 主干 open 只剩 `#38`/`#39`（`packages/agent-core/agent_core/guardrails/auth.py:92`/`:117`，`py/weak-sensitive-data-hashing`）。二者的病根与 v3 上**已 Accepted 的 ADR-0007** 是同一条：

> 「两应用都用**单一静态 `API_KEY`**（无 key→tenant 映射）」——所以身份只能由密钥摘要出来。

若直接在 main 上再造一个 principal 注册表，就与 v3 的 `identity.py` / `identity_middleware.py`（RS256 JWT 验签 + `X-Internal-Tenant`/`X-Internal-User` HMAC + `bind_tenant_context`）并存成**第三套身份机制**，违反 AGENTS.md「横切关注点三层齐备：单一实现 / 全局装配 / 强制门禁」。故 B7b 的真修必须落在**已断言主体**之上。

## 2. 客观事实（全部实测，非推断）

| 项 | 实测值 | 取法 |
|---|---|---|
| 分叉程度 | main ahead **49** / v3 ahead **47**，merge-base = `2a5e633` | `git rev-list --left-right --count main...origin/v3` |
| v3 最后提交 | `26cd2fa`（2026-09-27，PR #22） | `git log -1 origin/v3` |
| 试合冲突面 | **仅 5 个文件**：`CHANGELOG.md`、`docs/plans/dep-security-accepted-risks-2026-09-25.md`（add/add）、`packages/agent-runtime/pyproject.toml`、`scripts/lint_architecture.py`、`uv.lock` | `git merge-tree --write-tree --name-only main origin/v3`（exit=1） |
| `guardrails/auth.py` | **不冲突**——v3 自 fork 后从未改过该文件（`git diff --stat merge-base origin/v3 -- ...guardrails/` 为空），main 单侧演进 `+113/−3` | 同上 |
| v3 独有身份层（main 全无） | `agent_runtime/identity.py`、`identity_middleware.py`、`agent_federation/api/identity_bridge.py`、`knowledge_service/utils/tenant_identity.py`、`agent_core/memory/_tenant_gate.py`、ADR-0006/0007、`migrations/006_tenant_corpus`、`010_episodic_tenant`、5 个 governance 红线测试、`scripts/audit_tenant_access.py` | `git diff --name-only merge-base origin/v3` + `git cat-file -e main:<path>` 逐个核实 |
| v3 侧 lint 新增门禁 | `check_tool_monitor_scatter`、`check_tool_direct_import` | `git diff merge-base origin/v3 -- scripts/lint_architecture.py` |
| main 侧 lint 新增门禁 | `check_bare_secret_hashing`、`check_legacy_identity_calls`、`check_manual_path_containment`、`check_api_layer_path_io`、`check_exception_echo_in_api_responses` | `git diff merge-base main -- scripts/lint_architecture.py` |
| v3 引入的新 env | 合流后 `.env.example` 「租户身份断言」段实际 **12 项**：`DEPLOY_ENFORCE_IDENTITY`、`SINGLE_TENANT`、`TENANT_JWT_PUBLIC_KEYS_FILE`、`TENANT_JWT_PRIVATE_KEY_FILE`、`TENANT_JWT_ISSUER`、`TENANT_JWT_AUDIENCE`、`TENANT_JWT_CLOCK_SKEW`、`TENANT_JWT_MAX_TTL_S`、`TENANT_JWT_ENFORCE`、`INTERNAL_HMAC_KEY_FILE`、`INTERNAL_HEADER_MAX_AGE_S`、`TENANT_HEADER_ENFORCE`（本行初稿写「9 个」与 `INTERNAL_HMAC_KEY` 均为错，已于 §9 按实跑纠正：代码读的是 `INTERNAL_HMAC_KEY_FILE`，委托 agent-core `load_hmac_key`） | `git show origin/v3:packages/agent-runtime/agent_runtime/identity.py` + 合流后读 `.env.example` |
| v3 引入的新依赖 | `agent-runtime` 增 `PyJWT[crypto]` extra（冲突文件即为此） | `git diff --stat merge-base origin/v3 -- packages/agent-runtime/pyproject.toml` |

**结论**：合流成本远低于 47 commit 的表面规模——文本冲突 5 处，其中 3 处机械（CHANGELOG 双段并存、同名文档 add/add 需逐条并表、`uv.lock` 重新生成），仅 `lint_architecture.py` 与 `agent-runtime/pyproject.toml` 需真实语义和解。（初稿曾写 add/add「取 v3 版」，实跑判定为错：main 版是演进后的超集，已按 §9 纠正。）

## 3. 合流范围（一次 merge 全量，不 cherry-pick）

v3 的 47 个 commit 是**互相咬合的四条线**：ADR-0006 隔离域（W1-W5/T9-T13）、ADR-0007 身份层（A1-A6）、tool 埋点收口（observe_tool/ToolObservedMiddleware + 批 3 门禁）、HA/依赖/memory 修复。身份层断言出的 `tenant_id` 正是隔离域 store 的边界输入，**只摘身份层会拿到一个没有消费方的半成品**。故取单次 `git merge origin/v3`（保留 47 commit 原始作者与关联，避免 cherry-pick 造成的重复解冲突与后续二次分叉）。

- 分支：`integration/v3-into-main`（base = `main` @ `d838aa3`），走 PR，靠 CI/CodeQL 逐轮暴露问题，主干在合入前零风险。
- **不得**用 `-X ours`/`-X theirs` 之类全局策略压冲突；每个 hunk 手工和解并在 PR 描述里记取舍理由。

## 4. 五个冲突的处置口径

| 文件 | 处置 |
|---|---|
| `CHANGELOG.md` | 两条时间线分段并存（main 侧 Batch 1-7c 在前，v3 侧 ADR-0006/0007 线补在其后），不改写任何历史条目 |
| `docs/plans/dep-security-accepted-risks-2026-09-25.md`（add/add） | 两侧**已实质分叉**（`git diff --numstat main:<该文件> origin/v3:<该文件>` = **21 增 / 32 删**），不是简单重复文件：需人工逐条并表（风险登记表只允许增，不允许静默丢项） |
| `packages/agent-runtime/pyproject.toml` | 取并集：v3 的 `PyJWT[crypto]` extra + main 侧既有依赖收紧声明（anyio/mcp/transformers/weasyprint 下界），合并后 `uv sync --all-packages` 重生成 `uv.lock`，**不手工编辑 lock** |
| `scripts/lint_architecture.py` | 两侧门禁**全部保留**（main 5 条 + v3 2 条），统一编号并在 `ARCHITECTURE.md` 门禁表登记；这是本次唯一有真实语义风险的和解点，需逐函数核对白名单不互相抵消 |
| `uv.lock` | `uv sync --all-packages --extra dev` 重生成后 `git diff --stat` 确认只增 PyJWT 相关 |

## 5. 执行顺序（确认后）

1. `integration/v3-into-main` 上执行 merge，按 §4 解 5 处冲突。
2. `uv sync --all-packages --extra dev` → `uv run --with ruff ruff check .` → `uv run python scripts/lint_architecture.py`（要求全部门禁在位、exit 0；实跑结果与完整编号见 §9）。
3. `uv run python scripts/check_doc_sync.py`（ARCHITECTURE.md 的模块清单需补 identity 层，否则此项会警告）。
4. 分 session 跑测试（对齐 `make test` 的 9-10 个 session；Windows 本机无 make，用等价 `uv run pytest` 逐目录），**重点关注**：v3 带来的 `tests/governance/test_identity_not_in_tool_schema.py`、`test_tenant_default_forbidden.py`、`tests/ha/test_tenant_isolation_real_pg.py`（缺 PG 环境应 skip，不得为凑绿改前置条件）。
5. 开 PR → 等 CI + CodeQL：**验收硬指标是主干 open 仍为 2（`#38`/`#39`）、且合流未新增任何告警**；若新增，按本方案同样流程真修，不 dismiss。
6. 合入后回到 B7b：在已断言主体上做 principal_id 化（另出方案），使 `#38`/`#39` 真消失。

## 6. 运行侧影响（合流即生效，须在 PR 描述与 `.env.example` 写清）

- **启动 fail-fast 默认关**（已实测核实，非推演）：`require_identity_startup_guard()` 仅在 `mode == "insecure"` **且** `DEPLOY_ENFORCE_IDENTITY=true` 时 `raise RuntimeError` 拒起；`DEPLOY_ENFORCE_IDENTITY` 默认 `False`（`env_bool(..., False)`），所以 insecure 模式**只告警不阻断**。⇒ 零依赖冒烟 `DATABASE_URL= uvicorn agent_server.main:app` 合流后应仍可调起，这列为本次一条**显式回归项**（实跑健在断言，不靠读代码默认成立）；也不得在合流 PR 里顺手把默认值改成 fail-closed（那是独立决策）。
- 新增 migrations `006_tenant_corpus` / `010_episodic_tenant`：需要真 PG 才生效，`deploy/k8s` 与 `docker-compose` 的初始化路径需在文档登记。
- `.env.example` 增 §2 表中的 **12 个**身份层变量（含启动 fail-fast 开关 `DEPLOY_ENFORCE_IDENTITY`，默认关）。

## 7. 回滚策略

单次 merge commit ⇒ 回滚 = `git revert -m 1 <merge>`（保留分支历史，不 reset 主干）。因身份层引入的 DB 列（`006`/`010`）有配套 `.down.sql`，回滚需按 ADR-0006 的 down 脚本顺序执行，PR 描述里必须先写清这一点。

## 8. 待拍板（需确认后我才动手）

1. **合流粒度**：按 §3 一次 merge 全量（推荐，理由：身份层与隔离域咬合），还是先只 merge 身份层相关 commit 分两步？
2. **`ARCHITECTURE.md` 是否在本 PR 内补 identity 层小节**（推荐补，否则 `check_doc_sync.py` 与门禁表登记会与实际不符）。
3. **lint 门禁编号**：合流后 main 侧 P2/P4-2/P5-P8 与 v3 侧两条 tool 门禁的统一编号方案（我倾向按现有 P 序续编，v3 的并入 P9/P10，并在 `ARCHITECTURE.md` 登记）。

## 9. 执行记录（2026-10-01，均为本机实跑输出，非推演）

### 9.1 五处冲突的实际处置（含与 §4 的偏差）

| 文件 | 实际处置 | 与方案的偏差 |
|---|---|---|
| `scripts/lint_architecture.py` | 以 main 为基底，v3 两函数原逻辑保留，续编为 **P9**（`check_tool_monitor_scatter`）/ **P10**（`check_tool_direct_import`）并均在 `main()` 装配 | 无 |
| `packages/agent-runtime/pyproject.toml` | 取并集，保留 v3 的 `identity = ["PyJWT[crypto]>=2.9"]`，main 侧依赖收紧声明全在 | 无 |
| `docs/plans/dep-security-accepted-risks-2026-09-25.md` | **以 main 为基底**（它是含 09-30 证伪与 PyJWT 新告警处置的演进后超集），再把 v3 独有的一条排查手法并回「排查方法备忘」（`uv tree -i <pkg>` 需 `--python 3.12` 规避 deepagents 改名残留） | §4/§2 初稿写「取 v3 版」**错**，已就地纠正：取 v3 会静默丢 main 侧 09-30 的三项取证结论 |
| `CHANGELOG.md` | 两条时间线分段并存（main 侧 Batch 1-7c 在前，v3 侧 09-27/09-25 两节在后），**不改写不重排任何条目**，仅在 v3 段前加一行归属标记说明它本次随合流首次进入 `main` | 无 |
| `uv.lock` | `git checkout --ours` 取 main 基底后 `uv lock` 重生成（**未手改 lock**） | 无 |

### 9.2 `uv lock` 实跑结果（§4 「只增 PyJWT 相关」的如实核对）

- `uv lock` 解析 300 包；`uv lock --check` 通过。`git diff HEAD -- uv.lock` = **40 增 / 36 删**，其中：
  - **预期部分**：`agent-runtime` 新增 `[package.optional-dependencies] identity` + `requires-dist` 条目 + `provides-extras = ["mcp", "identity"]`；
  - **未预期部分**：无包名增删、无 `version = ` 行变动，但 `cuda-bindings`/`nvidia-*`/`beartype`/`requests`/`numpy` 等约 30 行 **environment marker 被归一化**（如 `platform_machine == 'x86_64'` → `platform_machine == 'x86_64' and sys_platform == 'linux'`），这是本机 uv `0.11.21` 与 lock 原始生成版本的语义差异，**非本次需求引入的版本漂移**。
  - 影响判定（实查，非猜测）：CI 用 `astral-sh/setup-uv@v7` 且不钉版本、安装走 `uv sync --all-packages --extra dev`（Makefile:7，**非 `--frozen`**），仓内无 `uv lock --check` 门禁 ⇒ marker 重写不会破 CI。已在 PR 描述中记为已知副作用。
- **§5-2 风险项（PyJWT 是否真可用）已实测回答**：`uv run python -c "import jwt"` → `2.15.1`（`constraint-dependencies` 已抬到 ≥2.14.0）；`uv run pytest packages/agent-runtime/tests -q -k identity` → **27 passed**。原因：PyJWT 经 mcp 2.0.0（`pyjwt[crypto]>=2.10.1`）已是工作区必装包，**无需**把 `agent-runtime[identity]` 额外挂进消费方依赖。

### 9.3 合流新暴露的第 6 个问题（不在 §4 清单内）：文档悬空引用

`check_doc_sync.py` 首跑 **exit 1**，报两处：`ARCHITECTURE.md:92` 引用的 `docs/adr/0005-execution-memory-kernel-contract.md` 与 `docs/plans/plan-memory-hardening-2026-09-27.md`。**取证链**：

1. 两文件在 `main`、`origin/v3` 两个树里**都不存在**（`git ls-tree -r` 无命中），但 `ARCHITECTURE.md` §5 的引用随 v3 带入——即 **v3 自身早就不一致**，只是其 lint/doc-sync 在分叉点上未暴露。
2. 全 ref 搜索：`git log --all --diff-filter=A` 定位到 `d4b6faa`（2026-09-27）——它们只在 `feat/isolation-hardening` / `test/rag-route-ablation-eval` 上，**该分支未入 v3**。
3. 该分支后续 `ff68aee` 把 ADR-0005 改为「已采纳」并声称 **T0 已落地**（`agent_core/memory/execution.py` 下沉 `EpisodicStoreProtocol`/`ProceduralStoreProtocol`、`CapabilityReport.supports_episodic`）。主干实测：**T0 产物不存在**——`git grep -l -e EpisodicStoreProtocol -e supports_episodic -- packages tests scripts` 返回空，`agent_core/memory/` 无 `execution.py`。

**处置（不采信不可证的说法）**：从 `d4b6faa` 导入两份文档的**「提案（Proposed）」版**（字节级导出，无 BOM），并在两份文件头各加一段来源标注：声明它们仍为提案态、列出 `ff68aee` 声称已落地的 T0 产物在主干 grep 0 命中的具体命令，同时逐项核对已真正随合流落地的是 **T1**（migration `006`–`010` 含 `010_episodic_tenant`、`tests/ha/test_tenant_isolation_real_pg.py`）而非 T0。修后 `check_doc_sync.py` **exit 0（0 警告）**。

> 经验归入：引用存在性不等于内容存在性；doc-sync 门禁的价值正在这里——它拦住了「分叉分支自带悬空引用」这类仅靠人工阅读不会发现的债。

### 9.4 本地实跑汇总（全绿，对应 §5-2/3/4/6）

| 项 | 命令 | 结果 |
|---|---|---|
| ruff | `uv run --with ruff ruff check .` | All checks passed |
| 不变量 lint | `uv run python scripts/lint_architecture.py` | exit 0，**P4-2 / P2 / P5 / P6（含 P6-2）/ P7 / P8 / P9 / P10 全在位** |
| 文档同步 | `uv run python scripts/check_doc_sync.py` | exit 0（§9.3 修复后） |
| 根 session | `uv run pytest -q -m "not requires_pg"` | 839 passed / 5 skipped / 27 deselected |
| agent-runtime | `uv run pytest packages/agent-runtime/tests -q` | 606 passed（含 27 条 identity） |
| governance | `uv run pytest tests/governance -q` | 225 passed |
| agent-core | `uv run pytest packages/agent-core/tests -q` | 300 passed / 5 skipped |
| agent_server / federation | 分目录 | 44 passed / 163 passed |
| knowledge-service / shared-schemas | 分目录 | 238 passed / 13 skipped · 28 passed |
| kefu / exhibition / nl2sql | 分目录 | 43 passed · 347 passed / 1 skipped · 18 passed |
| HA（本机无 PG） | `uv run pytest tests/ha -q` | 1 passed / 26 skipped（**skip 属设计意图**；CI 环境下缺 PG 为 FAIL，本 PR 的真实答案交给 CI） |
| §6 显式回归：零依赖冒烟 | 自写脚本双向验证 | 默认档：`agent_server.main:app` 构造成功，中间件栈 `[IdentityMiddleware, CORSMiddleware]`，`require_identity_startup_guard()` 不 raise；`DEPLOY_ENFORCE_IDENTITY=true` 且无公钥/无 `SINGLE_TENANT` → `RuntimeError`（拒启动文案引 ADR-0007 §4.1）。⇒ 默认关不阻断零依赖冒烟，且开关**不是摆设** |

### 9.5 尚待完成

- §5-5：PR → CI（含 `ha` workflow 真 PG）+ CodeQL；**硬指标：主干 open 仍为 2（`#38`/`#39`）且零新增告警**。
- §6 第二条：migrations `006`–`010` 在 `deploy/k8s` 与 `docker-compose` 初始化路径的登记（本 PR 未做，已归入待办）。
- 新登记的技术债：`IdentityMiddleware` 仅覆盖 2/6 应用（已写入 `ARCHITECTURE.md` §5），`TENANT_JWT_ENFORCE` 硬切换前需先补齐装配层 + 新增 lint 不变量。
