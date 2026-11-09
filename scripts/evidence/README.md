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
| `recount_todo_index.py` | 重算 `docs/TODO.md` §0 索引表的**声明值 vs 实算值**（含"一行一组 + 条数列求和"这种 0.3 形态）；不一致退出码 1 | 否 |
| `forensic_pg_roundtrip_probe.py` | 取证面 PG 往返实取：伪连接捕获 `save` 的 SQL/参数 + 合成行回放 `get`，证「记录级 forensic 不落库 / 读回 steps 是 dict」。**B 层修完后必须复跑**——同一条命令的读数应从 `False/None/dict` 翻成 `True/dict/ForensicContext 可读`（见台账 §25 与 `plan-forensic-provenance-wiring-2026-10-16.md` §1.1） | 否（不需要真 PG） |
| `recount_plan_status_lines.py` | 重算 `docs/plans/` 顶层 plan 的**状态行有无**（钉死口径：顶层 `.md`、排除同目录 `README.md`、前 25 行匹配 `状态[^。；]{0,14}[:：]`），并把已知口径漏计显式登记 ⇒ 输出「未命中」与「真待补」两个数。`rc=1` = 例外清单与现实不符；`rc=2` = 找不到 plan 目录（复制到仓库外运行即触发，**防止空目录冒充读数**）| 否 |
| `nl2sql_real_pg_probe.py` | nl2sql 元知识**真库往返**：走 `init_meta_schema.apply` 生产入口建全链 001-006 + 幂等第二遍 + `workspace_id=''` 写入路径 + 绕过 `_stamp` 的直接仓储写入 + D8 摘键语义反证 + 「库停在 005 时当前代码必须 42P10」发布顺序判据（11 项）。**改到 nl2sql 迁移或 `_upsert`/`_stamp` 后必须重跑**；`rc=2` 是 pgserver 起不来（前置不可用），不是通过 | 否（本机进程内 PG） |
| `migration_gate_mutation_probe.py` | `scripts/lint_migration_refs.py` 的**非空转反证**：三形——原样副本零违规（阴性对照）/ 注入 B-1 错表名 ⇒ M-1 报红 / 摘掉 006 ⇒ M-2 目标键消失。只在 `tempfile` 副本上动，不碰工作树。改过门禁判据后必须重跑 | 否 |
| `face_basis.py` | 面基准**唯一实现**：`face = git diff --name-only HEAD`，另提供 derived / ext-fresh / selftest 三模式；退出码 0/1/2 三态 | 否 |
| `typo-scan.ps1` | 文档面 T1..T5 形状扫描；扫描面 `$files` 表是本件的唯一来源 | 否 |
| `ts-provability.ps1` | 账面新增行的内容可证性 R-1..R-6（时间戳 / 件名在位 / 键绑件内容 / 逐字引用） | 否 |
| `k46-keypair-lib.ps1` | R-6 的 `(key,value,form)` 三元组抽取器**唯一实现** | 否 |
| `k71-basis.ps1` | 面基准的 PS 薄适配层：本机量具经它转调 `face_basis.py`，不在体内另拼基准 | 否 |

## 本机量具链（登记，非重构）

`scripts/evidence/face_basis.py` 是面基准的唯一实现。派生链与门件从**载体现取**三集合，
不手抄 CSV；调用边如下，两端都能在 tracked 面解析：

| 库内件 | 被谁调用 | 判据住处 |
|---|---|---|
| `scripts/evidence/k71-basis.ps1` | k70-attribution / k70-ext-derive / k70-candidate-derive dot-source | 面基准解析只此一处 |
| `scripts/evidence/typo-scan.ps1` | e26-gate-fill 的 B2b / C 段 | T1..T5 形状判据 |
| `scripts/evidence/ts-provability.ps1` | e26-gate-fill 的 B3 段（`-FilesCsv`） | R-1..R-6 |
| `scripts/evidence/k46-keypair-lib.ps1` | `ts-provability.ps1` 与 R-6 透视件 dot-source | 三元组抽取器 |

**本轮只登记不重构**：`e26-gate-fill.ps1`（99 KB / 13 代 fork）与 postcommit（8 代）仍在本机
一次性目录运行，拆分 / 迁 pytest 另开一刀。库内四件与同名运行时镜像逐字一致（sha256 自证见
取证件 §50）；一旦两者漂移，门件从本机镜像派生的扫描面就与库内判据不同源 —— 这条作为
**待拍项**登记，不在本轮偷改门件路径。T5 仍读本机一次性变异脚本 mutate-v1.mjs，新克隆上
不可直接跑，同属那一刀的射程。

## 运行

```bash
# 主干复验（参数是具名的，位置参数会报 usage）
uv run --no-sync python scripts/evidence/verify_main_tip.py \
    --merge-sha <merge commit sha> \
    --merged-at <gh 报的 mergedAt，如 2026-10-04T01:29:20Z> \
    --baseline-max-number 48

# 读任何 `>` / Out-File 产物之前先转码
uv run --no-sync python scripts/evidence/normalize_dump.py <dump 文件>

# 迁移/写入路径的真库往返（pgserver = 本机进程内 PG 16.2 + pgvector，免 docker）
uv run --no-sync --with pgserver python scripts/evidence/nl2sql_real_pg_probe.py

# 迁移静态门禁的非空转反证
uv run --no-sync python scripts/evidence/migration_gate_mutation_probe.py
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
