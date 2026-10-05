# 已合并 ref 清理取证（2026-10-04）

> 目的：把「哪些本地/远端分支可以安全删除」的证明**先落成文档再执行删除**。删除后 tip 消失，逐条证据不可复现，所以判据、命令、删除前读数必须先进仓（他人可用本文命令在任意时刻复核 main 侧结论——复核依赖 main 上的 merge 提交，不依赖被删分支）。

## 1. 判据（来自本仓既有经验，非临时约定）

1. 先 `git fetch --prune`。`[gone]` 只说明远端已删，不代表本地可删。
2. base **必须取该分支 PR 的真实 `baseRefName`**（`gh pr list --state all` 建映射表），无 PR 才回落 `main`；否则长期特性分支会算出大量假「独有提交」。
3. 判「已并入」用 `git cherry -v <base> <head>`：`+`（独有）为 0 且相对 base 的独有文件为 0，即内容已在 base。`git branch -d` 成功本身是第二重保险（git 拒绝删未合并分支）。
4. **强证**：本仓 PR 一律 `--merge`（非 squash），故 `mergeCommit` 是真实 merge 提交 ⇒ 比**树 OID 全等** `rev-parse <head>^{tree}` vs `rev-parse <mergeCommit>^{tree}`。计数类判据（`rev-list --left-right --count`、`merge-tree` 退出码）在 squash 场景会三者同时假阳性，故不采信。
5. 唯一持有探测：`git diff --name-only <base>...<head>` 非空即否决删除。
6. 远端删除**不可逆且无本地 reflog 兜底**，风险高于本地；与版本线/里程碑同名（`vN` 系列）的分支**保留远端，只删本地副本**。

## 2. 删除前实取读数（2026-10-04，`main = 24d71b8`）

采集方式：一次性脚本（不入库，探针性质；命令面见 §4，可原样重跑）。`fetch --prune rc=0`、PR 映射 63 条。

| branch | kind | PR/state | cherry `+/-` | 独有文件 | treeEQ(merge) | 本地=远端 | 处置 |
|---|---|---|---|---|---|---|---|
| `fix/audit-operator-principal-p12` | local | #61 MERGED | 0/0 | 0 | True `bb2b9a812` | True | **删** |
| `docs/p12-main-verification` | local | #62 MERGED | 0/0 | 0 | True `c0a9133b1` | True | **删** |
| `docs/p62-closeout` | local | #63 MERGED | 0/0 | 0 | True `91cd79a9d` | True | **删** |
| `fix/forged-suffix-test-flake` | local | #64 MERGED | 0/0 | 0 | True `789309c99` | True | **删** |
| `docs/evidence-closeout-2026-10-04` | local | #65 MERGED | 0/0 | 0 | True `3546190e3` | True | **删** |
| `fix/doc-sync-tracked-scope-2026-10-04` | local | #66 MERGED | 0/0 | 0 | True `24d71b8e2` | True | **删** |
| `v3` | local | 无 PR | 0/0 | 0 | — | True | **删本地，保留远端** |
| `main` | local | — | 0/0 | 0 | — | True | 保留 |
| `dependabot/uv/minor-and-patch-f18118ef2b` | remote | **#55 OPEN** | **1/0** | **10** | — | — | **保留**（open PR 的 head，且唯一持有 10 个文件的改动） |
| `v2` | remote | 无 PR | 0/0 | 0 | — | — | **保留远端**（内容已并入，但版本线同名 + 远端不可逆） |

上表 6 个 `fix/*`、`docs/*` 本地分支的**远端同名分支**同判据（同一 mergeCommit 的树 OID 全等 + mirror True）⇒ 一并删除。

worktree 面：`git worktree list --porcelain` 只返回主工作区 1 条 ⇒ 无遗留 worktree（本批判据 6 用的两个 `--detach` worktree 已 `worktree remove --force` 回收）。

## 3. 结论与保留理由

- **本地 7 个 ref**（6 个已合并 PR 分支 + `v3` 本地副本）—— 本文档入库的同一批已执行，`git branch -d` 全部成功（未用 `-D`）。
- **远端 6 个 ref**（同 6 个 PR 分支）—— 本 PR 合入后执行（远端不可逆且无 reflog 兜底，所以取证先入库）。
  注：**本 PR（#67）自己的 head 分支 `docs/account-closeout-ref-cleanup-2026-10-04` 合入后同判据一并删除**（本地需先 `git switch main`）
  ⇒ 本地共删 8 个、远端共删 7 个；该分支合入前不在上表（取证时它尚不存在），但它满足同一组判据（`cherry +/- = 0/0`、独有文件 0、merge 树 == head 树）。终态预期不变（§4）。
- **保留并说明理由**（不是遗漏）：
  - `origin/dependabot/uv/minor-and-patch-f18118ef2b` —— 绑定 open PR #55，且相对 `origin/main` 有 1 个独有提交 + 10 个独有文件，属「唯一持有」，删它等于毁掉那条决策线的现场。
  - `origin/v2`、`origin/v3` —— 版本线同名，远端删除不可逆且无 reflog 兜底；本地已并入的部分只删本地副本。若日后要清 `vN` 系列，须单独决策。
  - `company` 这个 remote **整体不触碰**（另一套治理线，不在本次口径内）。

## 4. 命令面（复核 / 执行）

复核（只读，任何时刻可跑）：

```bash
git fetch --prune origin
gh pr list --state all --limit 300 --json number,state,baseRefName,headRefName,mergeCommit
git cherry -v origin/main <branch>                    # 期望：无 '+' 行
git rev-parse "<branch>^{tree}" "<mergeCommit>^{tree}" # 期望：两值全等
git diff --name-only origin/main...<branch>           # 期望：空
```

执行。第一段（本地）已随本文档入库前跑完；第二段（远端）在本 PR 合入后跑。`-d` 而非 `-D` 是刻意的——git 拒绝即说明判据不成立，届时停手而不是强删：

```bash
git branch -d fix/audit-operator-principal-p12 docs/p12-main-verification docs/p62-closeout \
              fix/forged-suffix-test-flake docs/evidence-closeout-2026-10-04 \
              fix/doc-sync-tracked-scope-2026-10-04 v3
git push origin --delete fix/audit-operator-principal-p12 docs/p12-main-verification docs/p62-closeout \
              fix/forged-suffix-test-flake docs/evidence-closeout-2026-10-04 \
              fix/doc-sync-tracked-scope-2026-10-04 docs/account-closeout-ref-cleanup-2026-10-04
git fetch --prune origin
git branch -a    # 期望：本地只剩 main；远端只剩 main / v2 / v3 / dependabot 那一条
```

执行后预期 `git ls-remote --heads origin` 恰好 4 条：`main`、`v2`、`v3`、`dependabot/uv/minor-and-patch-f18118ef2b`。本地预期剩 `main` 一个分支。**实际执行读数不入库**（本文给出的是可复核判据与预期，任何人可自行 `ls-remote` 验证结果，无需依赖我的转述）。

## 后记（2026-10-04 晚，v2/v3 处置变更）

本文 §4 的「远端预期剩 4 条」已被晚间清理轮取代：`v2` / `v3` 经用户显式指令删除（`git push origin --delete v2 v3` rc=0，随后 `git remote prune origin`）。变更依据：两分支经 `git branch -r --merged origin/main` 实取均已**完全合入 `main`**（v3 tip `26cd2fa` = 2026-09-27 PR #22 合并点、v2 tip `b691ff1` @ 2026-08-22），无独有内容可失；本文原列「刻意保留」的理由（远端不可逆且无 reflog 兜底）属风险提示，被「已确认合入 + 显式指令」覆盖。`dependabot/*`（OPEN PR #55 的 head 现场）与 `company` remote（另一套远端）保留理由不变。**现远端实测恰 2 条**：`main` / `dependabot/uv/minor-and-patch-f18118ef2b`；本地恰 `main`。本批台账见 `CHANGELOG.md`「评审遗留收口一批」§6。

## 5. `dependabot/uv/minor-and-patch-f18118ef2b` 删除（2026-10-04，随 PR #55 关票）

**本节判据与 §1 的三重判据不同，不得混用。** §1 的三重判据是为「**已合并**分支」设计的；本分支**三条全不满足**（`git cherry -v` 输出 `+`、相对 `origin/main` 独有文件 10 个、无 merge commit），因为它**从未合并**。⇒ 删除依据替换为下列三条，且关票属外部可见、不可逆动作，**必须先经用户显式批准**：

1. **内容已被替代 PR [#71](https://github.com/Light-Towers/agent-platform/pull/71) 收编**：`uv.lock` 与 #55 head 的**解析版本逐包差异 = 0**（只差 1 行 `specifier` 记录），见 `docs/plans/plan-pr55-disposition-2026-10-04.md` §3；
2. **用户显式批准关闭 #55**（2026-10-04 独立审核轮）；
3. **删前读数先入库**（本节 §5.1），满足本仓「取证先入库再删」纪律（§1 判据、§2 读数、§3 保留理由同属此纪律）。

### 5.1 删除前实取读数（2026-10-04）

| 项 | 读数 |
|----|------|
| branch | `origin/dependabot/uv/minor-and-patch-f18118ef2b` |
| tip sha | `b23269a4134905a63b89abce2c09e8c8c5532210`（与 `gh pr view 55 --json headRefOid` 一致） |
| 相对 `origin/main` 独有提交 | **1**（`git cherry -v main <branch>` 输出 `+ b23269a`） |
| 相对 `origin/main` 独有文件 | **10**：`pyproject.toml` · `uv.lock` · `applications/{agent_federation,exhibition-agent,kefu-service,knowledge-service,nl2sql-service}/pyproject.toml` · `packages/{agent-core,agent-runtime,shared-schemas}/pyproject.toml` |
| merge-base | `baa965f79a7ba03ebecf8ffe7736fcfd6f588ce0` |
| `git branch -r --merged origin/main` | **不含本分支**（从未合并 ⇒ §1 判据不适用） |

### 5.2 执行（#71 合入后）

```bash
gh pr close 55 --comment "已被 #71 替代（同解析结果收编，见 plan-pr55-disposition-2026-10-04 §3）"
git push origin --delete dependabot/uv/minor-and-patch-f18118ef2b
git push origin --delete chore/deps-pr55-lock-only-2026-10-04   # 本 PR 自身 head，随合入删除
git fetch --prune origin
```

**预期终态**（沿用 §4 口径：只给可复核判据与预期，实际读数不入库，任何人可自行 `ls-remote` 验证）：`git ls-remote --heads origin` 恰 1 条 = `main`；`git branch -a` 本地恰 `main`；`gh pr view 55 --json state` = `CLOSED`。
