# v3 身份层合流 main（B7b principal_id 化的前置）

> 状态：**待拍板**（本文件只做方案，未动代码；确认后按 §5 顺序执行）
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
| v3 引入的新 env | `TENANT_JWT_PUBLIC_KEYS_FILE`、`TENANT_JWT_PRIVATE_KEY_FILE`、`TENANT_JWT_ISSUER`、`TENANT_JWT_AUDIENCE`、`TENANT_JWT_MAX_TTL_S`、`TENANT_JWT_CLOCK_SKEW`、`INTERNAL_HMAC_KEY`、`INTERNAL_HEADER_MAX_AGE_S`、`SINGLE_TENANT` | `git show origin/v3:packages/agent-runtime/agent_runtime/identity.py` |
| v3 引入的新依赖 | `agent-runtime` 增 `PyJWT[crypto]` extra（冲突文件即为此） | `git diff --stat merge-base origin/v3 -- packages/agent-runtime/pyproject.toml` |

**结论**：合流成本远低于 47 commit 的表面规模——文本冲突 5 处，其中 3 处机械（CHANGELOG 双段并存、同名文档 add/add 取 v3 版并核对差异、`uv.lock` 重新生成），仅 `lint_architecture.py` 与 `agent-runtime/pyproject.toml` 需真实语义和解。

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
2. `uv sync --all-packages --extra dev` → `uv run --with ruff ruff check .` → `uv run python scripts/lint_architecture.py`（要求 7 条门禁全在位、exit 0）。
3. `uv run python scripts/check_doc_sync.py`（ARCHITECTURE.md 的模块清单需补 identity 层，否则此项会警告）。
4. 分 session 跑测试（对齐 `make test` 的 9-10 个 session；Windows 本机无 make，用等价 `uv run pytest` 逐目录），**重点关注**：v3 带来的 `tests/governance/test_identity_not_in_tool_schema.py`、`test_tenant_default_forbidden.py`、`tests/ha/test_tenant_isolation_real_pg.py`（缺 PG 环境应 skip，不得为凑绿改前置条件）。
5. 开 PR → 等 CI + CodeQL：**验收硬指标是主干 open 仍为 2（`#38`/`#39`）、且合流未新增任何告警**；若新增，按本方案同样流程真修，不 dismiss。
6. 合入后回到 B7b：在已断言主体上做 principal_id 化（另出方案），使 `#38`/`#39` 真消失。

## 6. 运行侧影响（合流即生效，须在 PR 描述与 `.env.example` 写清）

- **启动 fail-fast 默认关**（已实测核实，非推演）：`require_identity_startup_guard()` 仅在 `mode == "insecure"` **且** `DEPLOY_ENFORCE_IDENTITY=true` 时 `raise RuntimeError` 拒起；`DEPLOY_ENFORCE_IDENTITY` 默认 `False`（`env_bool(..., False)`），所以 insecure 模式**只告警不阻断**。⇒ 零依赖冒烟 `DATABASE_URL= uvicorn agent_server.main:app` 合流后应仍可调起，这列为本次一条**显式回归项**（实跑健在断言，不靠读代码默认成立）；也不得在合流 PR 里顺手把默认值改成 fail-closed（那是独立决策）。
- 新增 migrations `006_tenant_corpus` / `010_episodic_tenant`：需要真 PG 才生效，`deploy/k8s` 与 `docker-compose` 的初始化路径需在文档登记。
- `.env.example` 增 §2 表中的 9 个身份层变量，外加 `DEPLOY_ENFORCE_IDENTITY`（启动 fail-fast 开关，默认关）。

## 7. 回滚策略

单次 merge commit ⇒ 回滚 = `git revert -m 1 <merge>`（保留分支历史，不 reset 主干）。因身份层引入的 DB 列（`006`/`010`）有配套 `.down.sql`，回滚需按 ADR-0006 的 down 脚本顺序执行，PR 描述里必须先写清这一点。

## 8. 待拍板（需确认后我才动手）

1. **合流粒度**：按 §3 一次 merge 全量（推荐，理由：身份层与隔离域咬合），还是先只 merge 身份层相关 commit 分两步？
2. **`ARCHITECTURE.md` 是否在本 PR 内补 identity 层小节**（推荐补，否则 `check_doc_sync.py` 与门禁表登记会与实际不符）。
3. **lint 门禁编号**：合流后 main 侧 P2/P4-2/P5-P8 与 v3 侧两条 tool 门禁的统一编号方案（我倾向按现有 P 序续编，v3 的并入 P9/P10，并在 `ARCHITECTURE.md` 登记）。
