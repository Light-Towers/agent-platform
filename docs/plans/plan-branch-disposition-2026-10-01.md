# 分支资产台账与处置路径（2026-10-01）

> 类型：纯登记（不改代码、不动任何 ref）。目的：本轮分支清理的全部取证结论落库，避免后续会话重复推导或凭分支名猜"没用了"。
> 触发：用户要求清理"已处理完问题"的分支。判定纪律见文末「可复跑命令」。

## 1. 已清理（均为证据充分后的动作）

本轮清理：本地删 9 条（14 → 5，新建台账分支前）、远端删 4 条（`fix/dependabot-urllib3`、`fix/dependabot-eval-transitive`、`fix/dependabot-pyjwt`、`fix/main-dep-security-floors`），定性依据三类，逐条实测：

> 2026-10-02 又追加一轮（CodeQL Batch 7 系列 9 条），判据同上，取证与处置见文末 **§6**。

| 证据类型 | 判据 | 本轮实例 |
|---------|------|---------|
| 完全并入 | `git cherry -v <真实 base> <branch>` 行数全为 `-`（ahead=0） | `feat/courses-productionization`、`fix/deepagents-typed-memory`、`fix/intent-kernel-consolidation`、`fix/ws-monitor-shared-infra`、`fix/zhanggui-kg-real-query`、`v2`(本地)、`fix/dependabot-*` |
| squash 合并 | head **不是**目标分支祖先，但 head 与 merge commit 的 `git show --stat` 文件清单+增删行数逐项一致 | `fix/main-dep-security-floors`（PR #17：4 files +26/−6 与 `e5904c80` 完全一致） |
| 纯镜像 | 两 ref 的 `^{tree}` OID 相同 | `company-release` ≡ `company/main`（`f638624…`） |

**注意 base 陷阱**：`feat/isolation-hardening` 的 PR base 是 **v3** 不是 main。按 main 算会得到 48 个假"独有提交"，按 v3 算才是 15。判分支一律先取该分支 PR 的 `baseRefName`。

## 2. 保留的三条：都是资产，不是债

| 分支 | tip | 相对基准 | 为什么不能删 |
|------|-----|---------|-------------|
| `v3` | 26cd2fa（09-27） | ahead 47 / behind 19 vs `main` | V3 执行平台长期集成分支，主干尚未吸收；自身 CI 绿 |
| `feat/isolation-hardening` | d078312（09-28） | ahead 15 / behind 12 vs `v3` | 相对 v3 净差 **+842/−46 / 12 文件**，含 ADR-0005 执行记忆内核契约、`packages/agent-core/agent_core/memory/execution.py`（+109）与 `store.py`/`__init__.py` 接线、2 个 kernel 测试、`plan-memory-hardening-2026-09-27.md`、`docs/operations/testing-playbook.md`、`audit_tenant_access.py` 真库修复。PR #18 **CLOSED 未合**，PR #21 只并入了 ADR-0006 那一段 |
| `test/rag-route-ablation-eval` | 4cffe7c（09-30） | ahead 75 / behind 19 vs `main` | **从未开过 PR**（`gh pr list --head` 返回空），即评审记录为零；且是唯一持有者（marker 计数见下） |

`test/rag-route-ablation-eval` 的唯一性取证（`git grep -c <marker> <ref>` 命中文件数）：

| marker | main | v3 | 该分支 | 含义 |
|--------|------|----|--------|------|
| `shutdown_tracing` | 0 | 0 | **7** | tracing 生命周期 shutdown 接线只在它身上 |
| `agent_runtime.otel` | 10 | 10 | 11 | 门面退役（`e086483`）未进主干，主干仍是旧门面 |
| `build_api_app` | 12 | 12 | **18** | 工厂装配站点更多（ks 迁 `build_api_app` + lint 白名单摘除，`b3c5c97`） |
| `RAGAS` | 1 | 1 | **7** | RAGAS adapter 接线 + 126 容器实跑（`4278e23`） |
| `ablation` | 12 | 11 | **25** | RAG 路别消融评测主体 |

## 3. 处置路径（下一步该做什么，而非删什么）

- **`feat/isolation-hardening` → 先解冲突再开 PR（base `v3`）**：`git merge-tree --write-tree origin/v3 feat/isolation-hardening` 退出码 **1**，唯一冲突文件 `scripts/audit_tenant_access.py`（v3 与分支两侧都改过）。它是 ADR-0005/T0 的内核下沉，属"先方案后编码"里已有方案的成件套件，不是随手可丢的实验。
- **`test/rag-route-ablation-eval` → 拆分成小 PR 进 `main`**：75 个独有提交里混着两类主题（观测全局装配 / RAG 消融评测 + 演练记录）。整体开一个 PR 评审面过大；建议按 `refactor(observability)` 链与 `feat(eval)` 链各切一刀，且注意主干已发生 P2/P6/P7/P8 门禁收敛（PR #33 系列），重放时 lint 白名单需按现状重写。
- **`v3` → 与主干的合流是独立议题**（47 commits），不在分支清理范畴。

## 4. 远端残余（需人工拍板，本轮未动）

- `origin/v2`：本地已删（内容确已并入），**远端保留**。名字带里程碑语义（CHANGELOG 有"见 v2 修复 #14"的交叉引用），删 ref 会丢历史锚点。若要清，建议先 `git tag archive/v2 origin/v2 && git push origin archive/v2` 再删分支。
- `origin/dependabot/uv/minor-and-patch-37a69dd668`：对应 **PR #26 OPEN**，是活分支，勿删。

## 5. 可复跑命令（任何"这分支没用了"的判断都须先跑这四条）

```bash
git fetch --prune
BASE=$(gh pr list --repo Light-Towers/agent-platform --head <branch> --state all --json baseRefName -q '.[0].baseRefName // "main"')
git cherry -v origin/$BASE <branch> | grep -c '^+'          # 0 = 内容已在 base
git rev-list --left-right --count origin/$BASE...<branch>    # behind / ahead
git merge-tree --write-tree origin/$BASE <branch> >/dev/null; echo $?   # 0 = 可干净合并
```

补充判据（按需）：`git show --stat <branch>` vs `git show --stat <merge-commit>`（squash 取证）、`git rev-parse "<a>^{tree}" "<b>^{tree}"`（镜像取证）、`git grep -c <marker> <ref>`（唯一持有者取证）。

**squash 场景的最强判据（§6 实例坐实）**：若 squash 提交的父就是分支的 fork 点，则 `git rev-parse "<branch-head>^{tree}" "<squash-commit>^{tree}"` 应**两个树 OID 完全相同**（比 diffstat 逐项比对更强，因为它是内容等价而非行数巧合）。该判据成立时，`git cherry -v` 仍会把分支的每个提交列成 `+`（patch-id 对不上单个压缩提交）、`git rev-list --left-right --count` 仍报 `ahead = 分支提交数`、`git merge-tree` 退出码也可能为 1——**这三个指标在 squash 已并入后均为假阳性，不得据此判“未并入”**。

**教训登记**：分支名里的 `test/` `fix/` `chore` 前缀不携带任何合并状态信息；`[gone]` 只说明远端已删；`ahead>0` 只说明未被 base 包含，不说明内容无价值。本轮两条"看起来最像垃圾"的分支（`test/…`、feature 收尾分支）恰恰是唯一持有者。

## 6. 追加登记（2026-10-02）：CodeQL Batch 7 系列 9 条分支处置

> 背景：Batch 7 / 7b / 7c / 7d / B7b-1 / B7b-2 连开 9 个 PR（#38〜#47）全部已合入 `main`，但分支未清。**取证先入库，再删 ref**（删完本地/远端 tip 就不可复现）。取证脚本：`.codeartsdoer/temp/branch_disposition_check.py`（只读，逐条跑 §5 四条命令 + PR 元数据 + 本地/远端 tip 对比）。

共同前提：9 条均 `base=main`（逐条从该分支 PR 的 `baseRefName` 取，非假定）、PR `state=MERGED`、本地 tip == 远端 tip（无未推送提交）。

| 分支 | PR | 落主干方式 | `cherry +` | behind/ahead | 本地=远端 tip | 落主干 commit |
|---|---|---|---|---|---|---|
| `docs/b7b2-main-verification` | #47 | merge | 0 | 1/0 | `409efc7` | `5d8f9916` |
| `docs/codeql-b7b-plan` | #44 | merge | 0 | 8/0 | `130d7ff` | `d3bee611` |
| `docs/codeql-b7c-acceptance` | #40 | merge | 0 | 64/0 | `759b4e4` | `d838aa36` |
| `docs/codeql-b7d-acceptance` | #43 | merge | 0 | 10/0 | `c6aa82d` | `facd65fc` |
| `fix/codeql-b7b2-rate-limit-bucket` | #46 | merge | 0 | 4/0 | `0bef447` | `76589c4f` |
| `fix/codeql-b7d-workflow-permissions` | #42 | merge | 0 | 12/0 | `6fb57d5` | `9ee00007` |
| `fix/codeql-batch7-real-fixes` | #38 | merge | 0 | 68/0 | `cab1eda` | `a6602201` |
| `fix/codeql-batch7c-path-shape` | #39 | merge | 0 | 66/0 | `0db4ed1` | `bb46dd3b` |
| `fix/codeql-b7b1-llm-cache-slot` | #45 | **squash** | **5** | 7/**5** | `40e74ec` | `85cd9bfe` |

前 8 条：`cherry +` = 0 且 `ahead` = 0 且 `merge-tree` 退出码 0 ⇒ **内容已在 `origin/main`**（§1 表第一类）。

第 9 条（#45，唯一一条 squash 入主干的）不能走计数判据，改用§5 的树 OID 直比：

```
$ git rev-parse "40e74ec^{tree}" "85cd9bfe^{tree}"
62fb9c1dfa03247dfb6b1fbfd49464dba0012b5a      # 分支 head
62fb9c1dfa03247dfb6b1fbfd49464dba0012b5a      # squash 提交 ⇒ 完全相同
$ git rev-parse --short "85cd9bfe^"           # squash 提交的父 = 分支 fork 点，上述判据适用
$ git diff --shortstat "85cd9bfe^..40e74ec"    # 5 files changed, 216 insertions(+), 35 deletions(-)
$ git show --stat --format="" 85cd9bfe | tail -1   # 5 files changed, 216 insertions(+), 35 deletions(-)
```

⇒ 两条独立判据（树 OID 全等 + 净差与 squash 提交逐项一致）互证：**#45 已完整并入**。它的 `cherry + = 5` / `ahead = 5` / `merge-tree` 退出码 `1` 全部是 squash 形态下的**预期假阳性**（§5 已记入该陷阱），不得拿它们当“未并入”证据。

处置结果：本文件入库后，上述 9 条**本地 + 远端均删**。§2 保留的三条（`v3` / `feat/isolation-hardening` / `test/rag-route-ablation-eval`）与 §4 的两条远端残余（`origin/v2`、`origin/dependabot/…`）**本轮仍未动**，它们不是本轮 PR 的产物，处置路径仍按 §3。
