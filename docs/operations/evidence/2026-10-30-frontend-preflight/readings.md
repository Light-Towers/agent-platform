# 前端开工前置核查：41 条坐标全命中，方案文面订正 6 处 + 待拍板 2 项（2026-10-30）

**定位：** 证据记录（不是方案）。格式遵循 `docs/operations/evidence-format.md` §1 五字段 + §3 强度分档。
**对象：** `docs/plans/plan-web-frontend-minimal-core-2026-10-29.md` 的开工前置——它写于 rev `896f966e`，
此后本线又落了 14 个提交（B1–B14），所以要回答两件事：① 方案引用的**坐标**还准不准；② 方案里那些
**写成散文的数字**（事件类数、`/health` 字段数）是不是还能从单一实现直读出来。
**读数绑定 rev：** `3868023c`（分支 `feat/nl2sql-ttl-and-006-slim`），跑前 `git status --porcelain` 为空 ⇒ 读数即该树。
**关联：** 方案件本身（本批据本文订正它 6 处）、`docs/operations/testing-playbook.md` §2.7（取阴性姿势）、
`docs/plans/plan-revert-checkpoint-integrity-2026-10-29.md`（PR-3 的前置，6 项待拍板未答）。

---

## 1. 结论摘要（三段：命令 → 读数 → 判定）

| # | 项 | 判定 |
|---|---|---|
| 1 | 方案的 41 条行号坐标 | **全命中（TOTAL-OUT=0，rc=0）** ⇒ 14 批未动过任何被前端引用的后端代码，方案 §1/§9 的技术前提仍然成立 |
| 2 | SSE 事件类数 | 方案写 **13**，实取 **12** ⇒ PR-1 的 TS 联合与 `check-events.mjs` 的期望集必须改；这是本轮唯一的**硬错** |
| 3 | `/health` 字段数 | 方案 §1 只列 **13**（出处写的是 `console.html`），契约实取 **30**（基类 13 ∪ 子类 17）⇒ PR-4「逐字段直读」若照方案那张 13 的表做，会漏 17 盏灯 |
| 4 | CI 触发面 | `.github/workflows/agent-platform-ci.yml` 的两处 `paths:` **都不含 `web/**`** ⇒ 方案 §5「PR-0 必含 CI 的 JS 段」会被路径过滤器**架空**，A5 的非空转反证会"看起来绿"（其实是没跑） |
| 5 | 构建上下文 | `.dockerignore` 只有根锚定的 `node_modules`，**没有 `dist`** ⇒ 多阶段构建会把宿主 `web/node_modules` 拖进上下文，且本机预建的 `web/dist` 可遮蔽 builder 产物 |
| 6 | JS 门禁落点 | workflow L45 明写「CI 直接复用 Makefile 的 `make ci` 单一真相」，而 `make ci = lint test eval`（`Makefile:158`）⇒ 方案只说"CI 加 JS 段"，没定**加在哪**，这是 PR-0 唯一还需要人点的技术选择（§7） |
| 7 | `README.md:643` 一条过期行号 | 它引 `health.py:25-40`，而 `HealthResponse` 在 `:67`（`:25-40` 现是 `DependencyHealth`）⇒ `check_doc_sync.py` 只校路径不校行号，这类错锚不会被门禁抓到（§4 末段），本批顺手改掉 |

## 2. 坐标复验（41 条，逐条给"该行必须含某锚串"）

**读数**（rev `3868023c`，`uv run --no-sync python .tmp-scratch/c-mask/verify_frontend_cites.py`）：
`TOTAL-OUT=0  已校坐标=41  存在性=5`，rc=**0**。脚本落在 `.tmp-scratch/c-mask/`（**本机文件，不入库**；
换机器照本节末尾的清单自建：读工作树指定行、比对锚串子串、不命中即打印实际行）。
完整输出留档 `.tmp-scratch/c-mask/frontend-preflight.out`（同样不入库）。

**口径**：锚串取自方案文字的关键词（不是我从代码里挑的），所以命中=「该坐标仍指向方案所述的那个东西」；
不命中会打印实际行内容，由人判是坐标漂了还是方案说错了。首轮我把 4 个锚串写错（例：在
`test_console_router.py:130` 找断言文本，而 130 行是 `def`，断言在 133）——**那是探针的错，不是方案的错**，
订正锚串后 0 out；这个自纠写在这里，免得后人拿首轮那份 9 OUT 的读数当"方案有 9 处错"。

命中的关键坐标（完整 41 条在脚本里，这里只列判断依赖的）：

| 方案出处 | 坐标 | 实取 |
|---|---|---|
| §9.1 恒等性断言 | `applications/agent_server/tests/test_console_router.py:130-133` | 130 = `def test_console_router_exposes_only_the_shell_path`，133 = `assert paths == {("/console.html", ("GET",))}` ⇒ **dist 绝不能挂 console_router** 这条仍然成立 |
| §9.2 dev 代理免 CORS 改动 | `applications/agent_server/main.py:708` | `(get_settings().cors_allow_origins or "http://127.0.0.1:5173")` ⇒ 默认放行 Vite 端口，未变 |
| §11.5 `checkpoint_id` 必填 | `applications/agent_server/schemas.py:188` | `checkpoint_id: str = Field(min_length=1)` ✓ |
| §11.6 B 层 uuid4 | `packages/agent-runtime/agent_runtime/revert.py:77` | `new_checkpoint = {**tpl.checkpoint, "id": str(uuid.uuid4())}` ✓ |
| §0 参照物形状 | `applications/agent_server/static/console.html:223` / `:260` | `switch (payload.type \|\| name)` 与 default 报「未处理的事件类型」✓，case 数 9 ✓ |
| §9.3 镜像 | `Dockerfile:1` | `FROM python:3.11-slim`，**FROM 计数 = 1** ⇒ 确为单阶段，多阶段改造未做过 |

**一条必须记的坐标歧义**：方案 §11.5/§11.6 写的是**裸文件名** `schemas.py:188`、`revert.py:77`。
仓内 `git ls-files | Select-String 'schemas\.py$'` = **两个** `schemas.py`
（`applications/agent_server/schemas.py`、`packages/agent-runtime/agent_runtime/schemas.py`），
`revert.py` 在 `packages/agent-runtime/agent_runtime/` 而**不在** `applications/agent_server/api/`（那里叫 `session_router.py`）。
⇒ 内容逐条对得上，但坐标不唯一可解析。本批已在方案里补全路径。

## 3. 事件类数：12，不是 13

**读数**（同一脚本，AST/正则从三个出口源直取）：

```
planner_types n=8  ['answer','error','evidence','memory','replan','route','status','suspended']
StreamEventType literal n=8  与 planner 分支等值=True
router_direct n=8  ['admission','answer','cache_hit','coordination','done','error','evidence','route']
_node_event  n=3  ['answer','evidence','route']
UNION n=12
console_cases n=9   console 未覆盖 = ['admission','coordination','done']
```

**判定**：并集 = **12** 类。方案的表（§1）把 `error` 同时列在「planner 路径」和「router 直接发」两行 ⇒
8 + 5 − 1 = 12；而 §7 PR-1 行与 §9.3 的 `src/api/events.ts` / `scripts/check-events.mjs` 两处都写「**13 类**」。
方案的 §1 表本身没错，错的是从表里"数行数"得来的那个数被抄进了两处工单文面。

**新查到的一个更硬的权威点**：`packages/agent-runtime/agent_runtime/planner/protocol.py:44`
`StreamEventType = Literal[...]` 与 `serialize_stream_event` 的 8 个分支**逐字等值**（实取 `True`）。
方案 §1 只说权威在 `serialize_stream_event` + `_node_event`，漏了这个 Literal。它带一条真实风险：
`serialize_stream_event` 对未定义 type **返回 None 并静默忽略**（`:792` docstring 自陈），所以
「Literal 加了一项而分支没加」这件事在运行期**不会有任何症状**——事件直接消失。

⇒ `check-events.mjs` 的期望集**不得写死数字**（13 也好 12 也好）：按仓内既有纪律
「条数以脚本为准，别在散文里抄数」（`AGENTS.md` AI 开发范式·变异那节的原话），期望集应当从三个出口源
**派生**，并加一条断言 `StreamEventType ⊆ serialize_stream_event 分支集`（这一条正是 §2.2
「未识别事件不得静默吞掉」在后端自己的那半，前端管不到它）。派生式写法顺带解决另一件事：
§10.4 明说「各家对未识别事件的处理**未取证**」，所以本仓这条判据只能建在自己的源码上，本来就不该有外部常数。

## 4. `/health` 字段数：30，不是 13

**读数**：`health base n=13 sub n=17 union n=30`（AST 取 `AnnAssign` 字段名）。
权威源两处：`packages/shared-schemas/shared_schemas/health.py:67` `class HealthResponse(BaseModel)`（13 个）
∪ `applications/agent_server/schemas.py:121` `class HealthResponse(BaseHealthResponse)`（17 个）。

方案 §1 那张「`/health` 字段集」列了 13 个，出处写的是 **`console.html` `loadLights()`** —— 这是参照物，不是契约。
差的 17 个里至少这些是有判断价值的灯：`status` `version` `dependencies` `search` `sql_backend`
`coordination` `admission` **`revert`** `otel` `mcp` `control_plane` `cost_governance`
`cache_backend` `cache_ready` `cache_degraded_reason` `cache_stats`。

**判定**：PR-4 的判据原文是「每盏灯的文本可追溯到字段值」，那就必须按契约的 30 个字段做，
`console.html` 只用来对文案与灯语义。本批已在方案 §1 补上真源坐标与 30 这个数字。

**顺带查到 README 的一条过期坐标**：`README.md:643` 写
「`HealthResponse` 已 `class HealthResponse(BaseHealthResponse)` 对齐联邦契约
（`packages/shared-schemas/shared_schemas/health.py:25-40`）」——该文件 `:25-40` 是
`DependencyHealth` 的区间，`HealthResponse` 实际在 **`:67`**。`check_doc_sync.py` 只校**路径存在性**、
不校行号，所以这类错锚不会被门禁抓到（方案 §11.4 记的同族）。本批顺手改 README 这一处。

## 5. CI 触发面：`web/**` 不在路径过滤器里（本轮最有价值的一条）

**读数**（`git grep -n -E "^  [a-z0-9_-]+:|^    runs-on:|^on:|^name:" -- .github/workflows/agent-platform-ci.yml`）：
单 job `ci:`（`:52`，`runs-on: ubuntu-latest`），触发块两处 `paths:`（push `:7-22` / pull_request `:24-39`），
列表内容 = `packages/**` `applications/**` `tests/**` `eval/**` `docs/**` `scripts/ha_real_kill_verify.py`
`scripts/check_doc_sync.py` `pyproject.toml` `uv.lock` `Makefile` `docker-compose*.yml` `Dockerfile`
`.env.example` `.github/workflows/agent-platform-ci.yml`。

**判定**：**没有 `web/**`**。⇒ 新目录一旦落地，只改前端的提交/PR **根本不触发 CI**：
方案 §5 那条「PR-0 必含 CI 的 JS 段，否则前端代码漂移无人拦截」即使照做也会被这里架空，
而 §4 A5 那条非空转反证（「故意引入一个前端漂移，看 CI 的 JS 段是否报红」）会拿到一个**假绿**——
不是"门禁没抓到"，是"门禁没跑"。这两种红/绿在账面上长得一模一样，正是
`testing-playbook.md` §2.7 第 ③ 条（取阴性必须单独跑并看 rc）要防的形状。

⇒ PR-0 的文件清单必须加一行：两处 `paths:` 都补 `web/**`（`pnpm-lock.yaml` 在 `web/` 下，被同一条覆盖）。

## 6. `.dockerignore`：根锚定语义 + 无 `dist` 条目

**读数**：`(Get-Content .dockerignore).Count` = **17 行**，其中非空非注释条目 = **16 条**，
`Select-String 'dist'` 命中 **0 条**。与前端相关的两条是 `node_modules`（**不带 `**/`**）与 `**/__pycache__`（带）。
同文件里两种写法并存本身就是语义的自证：`.dockerignore` 的模式按**相对上下文根的路径**匹配，
不带斜杠的 `node_modules` 只命中根的 `node_modules`，要命中嵌套必须写 `**/node_modules`
（这正是该文件给 `__pycache__` 加 `**/` 的原因）。

**判定**：PR-0 的多阶段 Dockerfile 若按方案 §9.3 `COPY web/` 取源码，则
① 本机 `web/node_modules`（几十~几百 MB，已被 `.gitignore` 挡在 git 外但**挡不住 docker 上下文**）会整片进上下文；
② `.dockerignore` **没有 `dist`/`web/dist` 条目** ⇒ 本机预建的 `web/dist` 会进上下文，
配合 `COPY --from=builder` 之外的 `COPY web/ .` 就可能让镜像里出现"构建期产物被运行期拷贝遮蔽"的旧资产。
⇒ 加两条：`**/node_modules`、`web/dist`。这与本仓记过的「可变 tag + IfNotPresent ⇒ 静默跑旧代码」同族：症状都是"构建绿了但里面是旧的"。

## 7. JS 门禁落点：两条形状，只有一条不与 workflow 自己的注释打架

**读数**：`Makefile:158` `ci: lint test eval` + `uv lock --check`；workflow `:82` `run: make ci`；
workflow `:45` 注释「CI 直接复用 Makefile 的 `make ci` 单一真相，避免手写命令与本地漂移」；
workflow `:87` 已有旁路先例 `run: make test-cache-contract`（独立目标 + 独立 step + 独立 env）。

**两条候选**：
- **形状一**：JS 段并进 `make ci`（`ci: lint test eval ci-web`）。忠于 L45 那句话，但改了 `make ci` 的依赖面——
  没装 Node 的机器（126 宿主明确无 Node，方案 §6 实取）从此跑不动 `make ci`，而 `AGENTS.md` 又有一条
  「Windows 本机无 make，用等价命令」的约定，等于把 Node 变成 Python 门禁的前置。
- **形状二（推荐）**：新增 `make ci-web` 目标（`pnpm install --frozen-lockfile` / lint / typecheck /
  check-events / build），workflow 加**一步** `run: make ci-web`，与 `test-cache-contract` 同形态。
  命令仍在 Makefile 里（不违 L45 的"单一真相"），Python-only 环境不受影响。

**判定**：这是 D1（可逆、中影响），本文只登记不代拍。方案 §9.3 原文只写「CI workflow + JS 段」，没落到形状，
本批把两条候选与推荐写进方案，等一句答复。

## 8. 环境与资产在位读数

| 项 | 命令 | 读数 |
|---|---|---|
| 工具链 | `node --version` / `npm --version` / `pnpm --version` / `corepack --version` | `v24.12.0` / `11.6.2` / `10.33.0` / `0.34.5` ⇒ 与方案 §6 记的**逐字相同**，本机构建路径可用 |
| 命令可达性 | PowerShell `Get-Command node,npm,pnpm,yarn` | 前三者在位（node/npm 由 nvm 分发，pnpm 为全局安装；Source 列含盘符，按「本机路径对后人只造噪声」的既定口径不落进本文），`yarn = NOT_FOUND`（方案未用 yarn，无影响） |
| 已有前端资产 | `git ls-files \| Select-String 'package\.json$\|pnpm-lock\|\.vue$\|vite\.config\|tsconfig'` | **0 行** ⇒ 仓内确无被跟踪的 JS/TS 工程 |
| `web/` 目录 | `Test-Path web` | `NOT_EXIST` |
| StaticFiles | `git grep -n -I "StaticFiles" -- "*.py"` | **0 行**（`Measure-Object -Line`）⇒ 方案 §9.1「全仓零 StaticFiles 用法，本批是第一次」成立 |
| 前端方案三件套入库态 | `git ls-files --error-unmatch` × 3 | 全部命中 ⇒ 方案 §11.4 的「同批必 add」债已清，无悬空路径 |
| 14 批的代码影响面 | `git diff --name-only 896f966e..HEAD` | 30 个文件：28 个文档 + `deploy/k8s/15-valkey.yaml` + `scripts/lint_public_mirror.py`（纯注释）+ `tests/governance/test_cache_single_track_governance.py`（+1/−1 遮蔽）⇒ **未触碰任何前端引用的后端实现**，这就是 §2 全命中的原因 |

## 9. §3「三条错误通道」的作用域边界（不得外推到别的 app）

方案 §3 定案前端只面对三条错误通道（4xx `detail` / 500 信封 / SSE 流内 `error` 帧），出处是
`errors.py:15-16` 的 D-2=A 与 `query_router.py:376-378`。审计件
`docs/plans/plan-frontend-error-contract-audit-2026-10-19.md` §1.1 的表另有两行；本批**不复述审计件结论**，
两处都自己复跑过：

| 形状 | 覆盖面 | 本批复跑读数 |
|---|---|---|
| `{"detail": {"code","message"}}`（**dict detail**） | exhibition-agent 的 401/403/400 | `applications/exhibition-agent/exhibition_agent/server.py` 的 `:144/:146/:148/:150` 四个 `raise HTTPException(..., detail={"code": …, "message": …})` ⇒ 审计件那句成立 |
| `{"status":"unhealthy","pools":[…]}` | nl2sql-service 的 `/ready`（503） | **未复跑**（本批不开 `applications/nl2sql-service/`），此行仍按转述读 |

**判定**：对 `web/` 第一批（只连 `agent_server`）**三通道是对的、够用的**。但它是**按服务**成立的结论，
不是按仓成立的：`web/` 若日后接 exhibition / nl2sql，`describeError` 要加第 4、5 分支，
而这恰是方案 §6「第二批范围」之外的东西 ⇒ 本批只在方案里加一条作用域注记，不动 `describeError` 的设计。

## 10. 未跑与待环境（不得写成"已验证"的部分）

- **PR-0 尚未开工**：本批零产品代码、零 `web/` 文件。A1–A10 十条判据**一条都未取读数**。
- **未装任何 JS 依赖**：`pnpm install` 没跑过，因此 §6 的上下文体积、§7 的 pnpm 脚本可用性都还是**读码结论**，不是实跑结论。
- **未在浏览器实跑**：SSE 端到端、`/history` 真数据、状态灯的真值全部未验（沿用方案 §7 PR-00 那条
  「本机无模型密钥 ⇒ #18 保持开项」的同一条限制）。
- **CI 分支保护未查**：`agent-platform-ci` 是否被设为必需检查、path 过滤改动是否需要在仓库设置侧同步，
  本机无凭据可查 ⇒ 属「待放行」，不进本批结论。
- **PR-3 受外部决策阻塞**：`docs/plans/plan-revert-checkpoint-integrity-2026-10-29.md` 状态仍是
  **Proposed（待拍板）**，其 §7 的 6 项（首项 A1/A3 之争）未答 ⇒ PR-0/PR-1/PR-2/PR-4 不受影响，PR-3 不得开工。
- **126 / 241 侧一律未涉**：本批不构建镜像、不分发、不动线上。

## 11. 一条自纠：`>>` 续行提示符又吃了一条命令

第 9 节那条 grep 我写成 `git grep -n -E "['\"][a-z_]+['\"]:" …`，PowerShell 里的 `\"` 把引号平衡打破，
终端停在 `>>`，**命令根本没执行**（`GetTerminalOutput` 复核：只回显了未完成的命令行）。
我没有把它当"零命中"记进任何结论，改为用 Grep 工具单跑取到 16 条真读数（§4）。
⇒ 这是 `testing-playbook.md` §2.7 第 ③ 条入库后**第一次实踩复发**，说明那条约定的价值不止在 git grep：
**任何**带嵌套引号的命令都可能静默不执行，判据是"预期产物是否生成"，不是"屏幕有没有报错"。
