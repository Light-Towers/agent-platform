# `scripts/evidence/` — 可重跑的取证脚本

> 方案：[`docs/plans/plan-evidence-scripts-intake-2026-10-04.md`](../../docs/plans/plan-evidence-scripts-intake-2026-10-04.md)

## 收录判据

**会不会被「下次必须重跑」引用？** 会 → 入本目录；不会 → 留在本机一次性探针目录。

本目录存在的唯一理由是**可复现性**：仓内账面（CHANGELOG / TODO / runbook / playbook）把一些
判据写成「任何一次合入后必须在新 tip 上重跑」的指针。这些脚本原本住在 .codeartsdoer/temp
（**不是仓内路径**）里，而该目录被根 `.gitignore` 的 `.*/` 规则整目录忽略 ⇒ **新克隆上脚本根本不存在**，判据只在
本机工作副本成立。收进来 + 在 `ARCHITECTURE.md` 登记路径，使其受
`scripts/check_doc_sync.py` 的**文件引用存在性校验**保护（引用失效即 CI 红）。

**不收**成 pytest 全量：`[A]`–`[G]` 需打 GitHub API，进 CI 即引入网络依赖与配额面；只对**纯逻
辑**部分（预期 check 名派生）在用例里钉住。

## 脚本清单

| 文件 | 用途 | 是否访问网络 |
|---|---|---|
| `verify_main_tip.py` | 判据 6：在给定 merge sha 上实取七项 fail-closed 复验 | 是（`gh api`） |
| `normalize_dump.py` | PowerShell 重定向产物默认 UTF-16 LE ⇒ 按 BOM 嗅探转 UTF-8 | 否 |

## 运行

```bash
# 主干复验（参数是具名的，位置参数会报 usage）
uv run --no-sync python scripts/evidence/verify_main_tip.py \
    --merge-sha <merge commit sha> \
    --merged-at <gh 报的 mergedAt，如 2026-10-04T01:29:20Z> \
    --baseline-max-number 48

# 读任何 `>` / Out-File 产物之前先转码
uv run --no-sync python scripts/evidence/normalize_dump.py <dump 文件>
```

`mergedAt` 取自：`gh pr view <n> --json mergedAt,mergeCommit`。

**退出码**：`0` = 总体 PASS · `1` = 总体未达成 · `2` = 前置不可用（PyYAML 缺席 / `gh` 调用失败 /
`git` 取不到 changed paths）。`2` **从不**折算成通过——前置不可用与判据未达成是两件事，
都不得被写成「已验证」。

产物默认落 `.evidence-out/<tip 前 8 位>.txt`（UTF-8，脚本自己 `mkdir`）。该目录被既有
`.*/` 规则天然忽略，**无需改动 `.gitignore`**。

## 三条必须知道的坑（都是实踩过的）

1. **`on:` 在 YAML 1.1 里被解成布尔 `True` 键**，取 `cfg["on"]` 会拿到 `None` ⇒ 本脚本对
   `"on"` 与 `True` 两个键都试。
2. **绝不用正则取 `jobs:`**。`jobs:` 位于文件末尾时正则匹配不到终止符 ⇒ 该 check 静默掉出
   预期集，把真阳性红漏成无关项。故 PyYAML 缺席时**直接 exit 2**，不降级。
3. **门禁预期集必须派生，不能硬编码**。硬编码两个方向都会错：该跑的没进集合 ⇒ 它红了没人
   按 `[F]` 看；不该跑的写进集合 ⇒ 永远等不到而被误判未达成（例：纯文档批次不触发 `ha` /
   `assembly`）。

## 不得声称的事

本机没跑通的一律不写「已验证」；本地缺 `gh` 登录态 / 缺 PyYAML 导致的失败或跳过属**前置不可
用**，不是通过。任何「全绿」计数必须附 sha + extras 形态（见
[`docs/operations/testing-playbook.md`](../../docs/operations/testing-playbook.md) §2.1）。
