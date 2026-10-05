# 方案：PR #55（Dependabot minor-and-patch 组）处置 —— 关票 + 自建 lock-only/白名单抬下界 PR

> 状态：**已批准（甲档）；S1-S6 已执行且门禁全绿**；S7（推分支 + 开 PR）执行中；S8（关 #55 + 删 head 分支）待单独批准
> 分支：`chore/deps-pr55-lock-only-2026-10-04`（从 `main` `0f85eba`）
> 上游处置口径：`CHANGELOG.md`「取证链二批」§3（L146-152）与 §3（L70-75）、`docs/TODO.md` §8（L191）「已拍板、尚未执行」
> 相关口径来源：`docs/plans/plan-observability-global-remediation-2026-09-29.md` §3.3 R2/L-4

## 1. 背景与目标

### 1.1 现状（2026-10-04 实取）

| 项 | 读数 |
|----|------|
| PR | [#55](https://github.com/Light-Towers/agent-platform/pull/55) `chore(deps): bump the minor-and-patch group across 1 directory with 13 updates`，OPEN，无 review / 无 comment |
| 规模 | 10 文件（9 个 `pyproject.toml` + `uv.lock`），+675/−623；`uv.lock` 内 **45 个包**解析版本变化（含新增 2、移除 `greenlet`） |
| CI | `ci` ×2 **fail**（31s / 39s，失败 step = `CI gate`）、`assembly`/`ha` pass、`CodeQL` skipping ⇒ `mergeStateStatus=UNSTABLE` |
| 可改性 | `maintainerCanModify: false`、`isCrossRepository: false` ⇒ **不能就地改这条 dependabot 分支** |
| 时效 | 基线落后 `main` **47 个提交**；期间 `main` 未改 `pyproject.toml`/`uv.lock`（本地 `git merge origin/pr55` 无冲突） |

### 1.2 红的根因（本方案独立复现，非沿用旧结论）

`make lint` 的第二道 `scripts/lint_architecture.py` 的 **L-4**（OTel/langfuse extras 多处声明下界必须一致）拦下：

```
'opentelemetry-api' 下界不一致（pyproject.toml[otel]: >=1.45.0
  vs packages/agent-core/pyproject.toml[tracing]: >=1.24）——归一到方案敲定版本，防组合解析回溯
```

复现方式（只读、可丢弃分支）：`git switch -c verify/pr55 main` → `git merge origin/pr55`（无冲突）→ `uv run --no-sync python scripts/lint_architecture.py` **exit 1**，报错行与 CI 逐字相同；同一脚本在 `main` 上 **exit 0**，其余 13 条架构不变量全过、`ruff check .` 全过。

**关键后果**：lint 是 `CI gate` 的前置步骤，**后面 10 个 pytest session 从未在这套依赖组合上跑过** ⇒ 45 个包升级的真实风险面至今为零读数（这也是本方案把「实跑 10 session」列为验收项的原因）。

### 1.3 目标与拍板

1. **不动已敲定口径**：OTel 三处 `>=1.24`、langfuse 三处 `>=4.0.0` 保持不变（L-4 契约）。
2. **收进「只升锁文件版本」的收益**：45 个包的版本升级本身不改任何声明下界 ⇒ 不改变对外安装兼容面。
3. **声明下界的抬升范围显式拍板**（见 §6；本次拍板 = **甲档**）。
4. **全门禁实跑绿**（§7），并在主干留下可复核的替代 PR。

**关键语义（决定了本方案的全部取舍）**：**声明下界 ≠ 实际安装版本**。`>=0.3` 在全新解析时同样取满足约束的**最新**版（`langchain-core` 1.6.5）。因此「保持旧下界」不会让任何人装回旧版；下界真正起作用的唯一场景是**环境里另有约束把版本往下压**（那时低下界允许被压到 1.6 以下，高下界不允许）。⇒ 本次 45 个包的升级面在甲/乙/丙三档下**逐包相同**，差异只在声明的宽窄。

**非目标（不搭车，另行决策）**：
- 不新增 Dependabot alerts 门禁（`docs/TODO.md` §8 遗留项 ④，属独立方案）。
- 不把 OTel 三处下界抬到 `>=1.45.0`（见 §6 否决记录）。
- 不改 `applications/*/requirements.txt` 这套**第二声明源**（见 §4.3 残余局限）。

## 2. 规则

- **R1（L-4 契约包禁单方面抬下界，硬）**：`opentelemetry-api` / `opentelemetry-sdk` / `opentelemetry-exporter-otlp` / `langfuse` 的声明下界由 `plan-observability §3.3` 统筹，**dependabot 不得单方面抬**；要抬必须先改方案口径 + 同批改齐全部声明位。**本处不是政策选择而是门禁必然**：不改它 L-4 就红。
- **R2（跨版本线抬升需显式拍板）**：`major` 发生变化的下界抬升（`0.x` 按 `0.minor` 算）不随机器人默认接受，须显式拍板 —— 本次拍板结果见 §6。
- **R3（只升 lock 不改契约）**：让 `uv.lock` 里的解析版本前进、`pyproject.toml` 声明下界不动，**不改变对外安装兼容面** ⇒ 默认允许，且是本方案的主体。

## 3. 逐条判定（18 处声明下界改动 / 10 个包，位置数合计 18 已用 `gh pr diff` 逐条核对 ✓）

| 包 | PR 的抬法 | 位置 | 判定 | 理由 |
|----|----------|------|------|------|
| `opentelemetry-api` | `>=1.24 → >=1.45.0` | 根 `[otel]` ×1 | **回退** | R1；已敲定口径为三处归一 `>=1.24`，抬它 = 改方案口径，且**零收益**（锁文件本来就解析 1.45.0） |
| `langchain-core` | `>=0.3 → >=1.6.5` | 根 ×1 | **接受**（甲档拍板） | 跨线（`0.3`→`1.6`）；按 §6 记录接受，残余风险见 §4.3 |
| `langchain-openai` | `>=0.3 → >=1.6.6` | 根 ×1 | **接受**（甲档拍板） | 同上 |
| `sqlglot` | `>=25.0 → >=30.20.0` | 根 ×1 + `agent-core` ×1 | **接受**（甲档拍板） | 同上（`25`→`30`） |
| `pydantic` | `>=2.7 / 2.13 / 2.13.0 → >=2.13.5` | 根 / federation / exhibition / kefu / nl2sql / agent-runtime / shared-schemas ×7 | **抬** | 同 major 线；本仓已有 4 处 `>=2.13`，抬升实为**归一**（消除 `2.7`/`2.13`/`2.13.0` 三档漂移），与 L-4 同范式；workspace 包全为 `editable`、不发布，消费面 = 本仓 |
| `langgraph` | `>=1.2.10,<2 → >=1.2.12,<2` | 根 ×1 + knowledge-service ×1 | **抬** | 同 `1.x` 线、patch 步进、带 `<2` 上限 |
| `anyio` | `>=4.14.2 → >=4.15.1` | 根（硬依赖）×1 | **抬** | 同线 minor；本仓已有 CVE 依据注释（TLSStream IDNA 2003 / process-pool 阻塞，first_patched 4.14.2） |
| `mcp` | `>=2.0.0 → >=2.2.0` | 根 `[mcp]` ×1 | **抬** | 同线 minor；已有 CVE 依据注释（DNS 重绑定 / WebSocket / HTTP session，high×3） |
| `transformers` | `>=5.15.0 → >=5.17.0` | 根 `[eval]` ×1 | **抬** | 同线 minor；已有 CVE 依据注释（RCE / 路径遍历，用于强制覆盖 `flashrag-dev` 传递边） |
| `ruff` | `>=0.5 → >=0.16.9` | 根 `[dev]` ×1 | **抬** | dev-only extra，不进运行时契约面；`0.x` 无 API 稳定承诺 |

**汇总**：回退 **1** 处（`opentelemetry-api`）· 抬升 **17** 处 · 合计 18 处 ✓
**锁文件面**：`uv.lock` 采信 #55 的解析结果（45 个包升级），**只改 1 行** —— 根 `opentelemetry-api` 的 `specifier` 记录（`>=1.45.0 → >=1.24`）。

## 4. 影响面

### 4.1 远端（外部可见、不可逆 —— 需单独批准才执行）

1. **关闭 #55**（`merged=false`），关闭说明里指回替代 PR。
2. **删除 head 分支** `dependabot/uv/minor-and-patch-f18118ef2b`：它是那 1 个提交的唯一持有者（相对 `origin/main` 独有 1 提交 + 10 文件），按 `docs/operations/git-ref-cleanup-2026-10-04.md` 的三重判据（`git cherry -v` 的 `+` 为 0 + 相对 base 独有文件为 0 + 树 OID 全等）判定为**不适用**（本分支不满足前两条，属「未合并而主动放弃」），故按「关票后删除、删除前先取证」记录在该操作文档的新增节里。

### 4.2 仓内（S2-S5 实取）

- `uv.lock`：45 个包版本升级（`torch` 2.13.0→2.14.0、`transformers` 5.15.0→5.17.0、`langchain-core` 1.5.6→1.6.5、`starlette` 1.6.0→1.7.0、`sqlalchemy` 2.0.52→2.1.1、`opentelemetry-*` 1.44.0→1.45.0、`langfuse` 4.14.4→4.15.6、`mcp` 2.0.0→2.2.0、`openai-agents` 0.21.1→0.22.3、`sentence-transformers` 6.0.0→6.1.0 等）。相对 `main`：`1 file changed, 656 insertions(+), 604 deletions(-)`；相对 `origin/pr55`：**`1 insertion(+), 1 deletion(-)`**。
- 9 个 `pyproject.toml`：**17 处声明下界抬升**（`opentelemetry-api` 那处已回退到主干值，故不出现在 diff 里），相对 `main`：`9 files changed, 17 insertions(+), 17 deletions(-)`。
- 主干产品代码：**零改动**。

### 4.3 残余局限（如实登记）

- **跨线下界被接受（甲档）**：`langchain-core >=0.3 → >=1.6.5`、`langchain-openai >=0.3 → >=1.6.6`、`sqlglot >=25.0 → >=30.20.0` 三包（4 处）的声明契约被抬高。含义是「不再允许被别的约束压到这些线以下」；对**不用锁文件**的安装路径（`pip install -e .`、`applications/*/requirements.txt` 双源、下游）是真实的兼容面收窄。备选乙/丙见 §6。
- **第二声明源未纳入门禁**：`applications/agent_federation/requirements.txt`（有下界：`langchain-core>=1.5.3` / `langchain-openai>=1.4` / `sqlglot>=25.0` / `pydantic>=2.13`）与 `applications/knowledge-service/requirements.txt`（无版本）不受 L-4 覆盖；`plan-observability §3.3` R2 原文提过「uv / pip / 各 app requirements.txt 双源」解析面差异，但 L-4 只读 `pyproject.toml` 5 个位。⇒ 登记为 L-4 的覆盖盲区，另行评估是否纳入。
- 45 个包升级的**行为面**在 10 session + eval 上一次性验证，不逐个包做隔离验证。

## 5. 迁移策略与执行记录（分步 · 可回滚）

| 步 | 内容 | 状态 | 实取读数 |
|----|------|------|---------|
| S1 | 本方案文档 + **用户批准（甲档）** | ✅ | 2026-10-04 用户拍板 |
| S2 | 从 `main` `0f85eba` 建分支 `chore/deps-pr55-lock-only-2026-10-04` | ✅ | — |
| S3 | `git checkout origin/pr55 -- uv.lock`：采信 #55 的解析结果 | ✅ | — |
| S4 | 9 个 `pyproject.toml` 按 §3 落 **回退 1 处 + 抬升 17 处**（回退那处恢复主干值 ⇒ 相对 `main` 的净 diff = 17 处抬升） | ✅ | `9 files changed, 17 insertions(+), 17 deletions(-)` |
| S5 | 让 lock 的 `specifier` 记录与 S4 后的 `pyproject` 对齐 | ✅ | **只改 1 行**；`uv lock --check` **rc=0**；与 `origin/pr55` 的解析版本差异 **0**、包集合相同 |
| S6 | 本地实跑门禁（顺序即 CI 顺序）：`ruff check .` → `scripts/lint_architecture.py` → 10 个 pytest session → `eval/run_eval.py` → `scripts/check_doc_sync.py` | ✅ 全绿 | `ruff` rc=0；`lint_architecture` rc=0（**L-4 通过**）；`check_doc_sync` rc=0（0 警告）；10 session 逐条：root `1006 passed, 6 skipped, 28 deselected`(243.6s) · shared-schemas 28 · agent-runtime `594 passed, 1 skipped` · agent_server 44 · agent_federation 176 · kefu 43 · exhibition `347 passed, 1 skipped` · knowledge-service `404 passed, 13 skipped` · nl2sql 18 · observability（`--extra otel` 真 SDK）15 —— 10/10 EXIT=0；eval **15/15 = 100%** rc=0 |
| S7 | 推送 + 开 PR（标题写明「替代 #55」、正文附 L-4 依据与实跑读数） | ⏳ | — |
| S8 | 关 #55（说明指回 S7 的 PR）+ 删 head 分支（先取证后删） | ⛔ 待单独批准 | — |

**S5 的一条工具纪律（本批实测得到，值得入库）**：对锁文件做「与 pyproject 对齐」时，**不要用 `uv lock` 全量重写**去替代最小改动 —— 本地 uv 0.11.21 重写会额外多写 **35 行**平台 marker 元数据（`sys_platform != 'emscripten'` 等，`main`/`#55` 的锁里各 24 处、重写后 34 处），而 `uv lock --check` 对标最小改动版**同样 rc=0**。即：判据是 `uv lock --check`，不是「与一次全量重写的字节等同」；全量重写把 diff 放大 36 倍且零收益。本批采用「#55 的锁 + 手工改 1 行」。

**红线自查**：本方案**不删用例、不收窄断言、不放宽前置条件**；S6 若红，修产品代码到契约要求，不得为凑绿回退断言。若红的根因确属某个包的升级，用 `uv lock --upgrade-package` 把该包排除并登记，而不是改测试。

## 6. 决策记录

### 6.1 已否决：三处 OTel 下界一同抬到 `>=1.45.0`

（对应 `CHANGELOG.md` L151 的三支之①）**否决**。理由：属改已敲定口径（`plan-observability §3.3` R2/L-4 原文归一 `>=1.24`），需先改方案 + 重跑全部依赖解析；收益仅是「声明下界与 lock 同值」，无功能收益。若将来要改，须同批改 `pyproject.toml[otel]` 3 条 + `agent-core[tracing]` 2 条 + 方案文档口径。

### 6.2 已否决：先补一条「三处下界必须相等」的用例再谈抬版

（三支之③）**不采纳为前置**。理由：L-4 已经就是这条不变量本身（脚本实现，非正则），再补用例是同义重复；本方案改用「解析版本逐包比对」+ `uv lock --check` 作为 S5 的可判定判据。

### 6.3 跨版本线下界（4 处）：甲/乙/丙三档，**用户拍板 = 甲**

| 档 | 做法 | 取舍 |
|----|------|------|
| **甲（采纳）** | 只回退 `opentelemetry-api` **1 处**，其余 17 处照收 | 改动最小、最贴 #55 原意；代价 = 默许机器人跨五条线抬声明契约（§4.3 残余） |
| 乙 | 回退 **5 处**（otel + `langchain-core`/`langchain-openai`/`sqlglot`） | 只收同线与 CVE 依据的抬升；多 4 处判断，下轮 dependabot 会再提 |
| 丙 | 18 处声明下界**全不动**，纯 lock-only | 兼容面最保守；丢掉 `anyio`/`mcp`/`transformers` 三条有 CVE 依据的下界 |

**三档装到的版本完全相同**（§1.3 语义），差异只在 `pyproject.toml` 里那几个 `>=` 数字。

## 7. 验收标准（S6/S7 逐条判）

1. `uv run --with ruff ruff check .` rc=0。**✅ 已过**
2. `uv run python scripts/lint_architecture.py` rc=0（**L-4 必须绿**，且不得通过改 L-4 规则/加白名单达成）。**✅ 已过**
3. `uv lock --check` rc=0；且新 `uv.lock` 与 `origin/pr55:uv.lock` 的**解析版本逐包比对差异 = 0**。**✅ 已过**
4. `git diff main -- '*pyproject.toml'` **恰为 17 处**（全部是抬升；`opentelemetry-api` 已回退到主干值、故不在 diff 里），无第 18 处。**✅ 已过**
5. 10 个 pytest session 全绿（缺环境自动 skip 者须在 PR 正文逐条登记，非静默）；`eval/run_eval.py` 15/15 或如实登记。**✅ 已过**（读数见 §5 S6；skip 项均为设计意图内的缺环境跳过，非失败）
6. `scripts/check_doc_sync.py` rc=0。**✅ 已过**
7. 新 PR 的 checks 5/5 pass（`ci` ×2 / `Analyze` ×2 / `CodeQL`）。
8. `#55` 状态 = closed、head 分支已删、`git ls-remote --heads origin` 只剩 `main`；删前取证已入 `docs/operations/git-ref-cleanup-2026-10-04.md` 新增节。

## 8. 待批准

- ~~A：方案 + 甲档~~ **已批准（2026-10-04）**
- **B**：S8 的两个远端不可逆动作（关 #55、删 head 分支）——**待单独批准**。
