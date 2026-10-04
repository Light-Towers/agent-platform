# 方案：取证脚本入库（`scripts/evidence/`）——候选 ① 的实施口径

> 状态：**已拍板候选 ①**（2026-10-04 用户选定），本文件即「先方案后编码」的方案本体。
> 来源遗留项：`docs/TODO.md` §5「取证脚本全住在 gitignored 目录里，而账面把它们当可重跑指针」。
> 关联：`docs/operations/testing-playbook.md` §2.1（计数必须附 sha + extras 形态）、
> `docs/plans/plan-doc-sync-file-ref-gate-2026-10-01.md`（文档内联文件引用存在性门禁）。

## 1. 问题（不是"整洁癖"，是可复现性缺口）

CHANGELOG / TODO / PR 正文把 `verify_main_*.py`、`normalize_dump.py` 等写成「下次必须在新
tip 上重跑」的**指针对象**，但整个 `.codeartsdoer/` 被 `.gitignore:60` 的 `.*/` 规则整目录
忽略（实取：`git check-ignore -v` 命中该规则；`git ls-files .codeartsdoer` = **0**）⇒
**新克隆 / 换机器上这些脚本根本不存在**。判据 6 这类"必须重跑"的验收，其可复现性目前只在
本机工作副本成立。本轮又新增 3 个同类脚本（`resolve_todo_conflict.py` /
`probe_deploy_channels.py` / `normalize_dump.py`），即**同一遗留的第二批证据**，因此本项
从"登记"转为"闭合"。

## 2. 目标与非目标

**目标**
1. 让「主干复验」这条**判据**在任何新克隆上可原样重跑（含其 fail-closed 语义）。
2. 让仓内文档指向这些脚本时，**路径存在性受门禁校验**（引用失效即 CI 红），而不是靠自觉。
3. 把本轮已经踩实的那条**纯逻辑不变量**（按 `on.push.paths` × changed paths 派生"预期应跑的
   check 名"）从脚本里剥出来钉成用例——这条曾经因为正则取 `jobs:` 失败而**把真阳性红漏成
   无关项**，比任何账面措辞都更需要回归保护。

**非目标（明确不做，附理由）**
- **不做候选 ②**（把全部判据改写成 pytest）：[A]/[B]/[C]/[D]/[E]/[F]/[G] 都要打 GitHub API，
  进 CI 即引入网络依赖与配额面；只对**纯函数**部分做用例化。
- **不收全部临时探针**：`probe_forged_suffix.py`、`fixture_skip_probe/` 这类"一次性定性"证据
  的结论已写进账面，脚本本身不入库（收了就变成需要长期维护的第二套测试面）。
  入库判据 = **会不会被"下次必须重跑"引用**；会 → 入库，不会 → 留在本机。
- **不给根项目新增 `pyyaml` 直接依赖**：脚本用 `yaml.safe_load` 取代正则（这是本轮修掉的坑），
  而 PyYAML 已由**已声明的直接依赖** `uvicorn[standard]>=0.54.0` 传递保证
  （实取：`importlib.metadata.requires('uvicorn')` 含 `pyyaml>=5.1; extra == 'standard'`，
  当前环境 `pyyaml 6.0.3`）。故不动 `dependencies` / `uv.lock`（避免为一个脚本触发锁文件重算），
  改为**脚本内 fail-closed**：`import yaml` 失败即打印明确原因并 exit 1，绝不静默降级成正则。
- **不改 CHANGELOG 的历史段**：CHANGELOG 是 append-only 快照、故意不校验路径（见
  `scripts/check_doc_sync.py` 校验项 8 的括注）。历史里指向 `.codeartsdoer/temp/...` 的句子
  **原样保留**，只更新仍然有效的指针（`docs/TODO.md`、`docs/operations/*.md`）。

## 3. 影响面与落地清单

| 面 | 动作 |
|---|---|
| 新增 `scripts/evidence/README.md` | 说明收录判据、运行命令、输出落盘位置、以及**不得据本地缺环境下的 skip 声称已验证** |
| 新增 `scripts/evidence/verify_main_tip.py` | 判据 6 通用版（七项 [A]–[G] 全 fail-closed；预期集派生式）。相对本机版做三处适配：① 纯函数 `derive_expected_checks()` 与网络部分分离；② 输出可 `--out` 落盘（默认 `.evidence-out/<tip8>.txt`，被既有 `.*/` 规则天然忽略，**不需要改 `.gitignore`**）；③ 依赖缺失 fail-closed |
| 新增 `scripts/evidence/normalize_dump.py` | PowerShell `>` 重定向产物（默认 UTF-16 LE）按 BOM 嗅探 → 转 UTF-8 落盘再读。本轮第六条坑**再次踩到**，固化为工具 |
| 新增 `tests/governance/test_evidence_scripts.py` | ① 两个脚本存在且 `ast.parse` 可解析（防"指针失效"从文档面漏到代码面）；② `derive_expected_checks()` 的纯函数用例：路径命中/不命中、`on: push` 无过滤、**`jobs:` 位于文件末尾**（旧正则坑）、YAML 1.1 把 `on:` 解成布尔 `True` 键 |
| 修改 `ARCHITECTURE.md` | 在门禁/运维面登记 `scripts/evidence/` 三个文件路径 ⇒ 由 `check_doc_file_refs()` 校验存在性（该校验只覆盖 AGENTS/ARCHITECTURE/README 三份现状文档，故登记位置必须是其中之一） |
| 修改 `docs/TODO.md` §5 | 该 `[ ]` 项转 `[x]`，并把仍有效的指针改指 `scripts/evidence/...` |
| 修改 `docs/operations/testing-playbook.md` | 主干复验固定姿势那处指针改指 `scripts/evidence/verify_main_tip.py`（原写本机脚本路径） |
| 修改 `docs/operations/audit-operator-principal-runbook.md` | 引用处同步（该 runbook 已入库，不依赖本机脚本） |

**不碰**：任何产品代码、任何 workflow、`.gitignore`、`uv.lock`、`pyproject.toml`。

## 4. 迁移策略（零数据、零契约）

- 本机 `.codeartsdoer/temp/` 下的原件**不删**（历史取证痕迹，且账面按原名引用过它们）；
  入库版是"移植 + 适配"，文件头注明「由本机探针 `verify_main_tip.py` 移植，2026-10-04」。
- 输出目录从 `.codeartsdoer/temp/` 改到 `.evidence-out/`：两者都被 `.gitignore` 的 `.*/`
  规则忽略 ⇒ 换目录不影响"忽略"这一事实，但**新克隆上能创建**（脚本自己 `mkdir(parents=True)`）。
- 参数口径不变：`--merge-sha` / `--merged-at` / `--baseline-max-number`。上一轮踩过"位置参数
  误用报 usage"的坑，故 README 里把**可直接复制的完整命令**写死一份。

## 5. 验收标准（逐条可判，不靠形容词）

1. `uv run --no-sync python scripts/evidence/verify_main_tip.py --merge-sha <本次主干 tip>
   --merged-at <gh 报的 mergedAt> --baseline-max-number 48` 在**最终树**上跑出 **rc=0 且打印
   `=== 总体：PASS ===`**，七项逐条有数字（不接受"某项缺失"）。
2. 同脚本对**已知旧 tip** `bb2b9a8` 派生的预期集与当时的硬编码集合逐项一致
   （`{ci, assembly, Analyze (python), Analyze (actions)}`），且对 `789309c`（含
   `packages/**`+`applications/**`）派生出**额外**的 `ha` ⇒ 证明派生式没有把该跑的漏掉。
3. `uv run pytest tests/governance/test_evidence_scripts.py -q` 全绿，且**不访问网络**
   （用例只喂 `tmp_path` 里的假 workflow 文本；无 `gh` 调用）。
4. `uv run --with ruff ruff check .` rc=0；`uv run python scripts/lint_architecture.py` rc=0
   （新脚本不得触发 P7-1 的 `is_relative_to` 手写字面，也不得新增 BLE001）。
5. `uv run python scripts/check_doc_sync.py` rc=0 ⇒ 证明 `ARCHITECTURE.md` 里新增的
   `scripts/evidence/*.py` 引用**确实被存在性校验覆盖**（故意把一个引用改成一个不存在的路径，
   临时验证门禁会红，验完还原；该"剥掉防线必红"自证不入库，只在 PR 正文里报结果）。
   - **（2026-10-04 实施后追记订正）本条的 rc=0 必须在干净检出上取**：该校验拿本机 FS 做基准，
     本机 gitignored 目录会把存在性判成「存在」而返绿。正确做法：`git worktree add --detach
     $env:TEMP\wt <sha>`（只落地 tracked 文件）后在该目录内跑。订正缘由与双向实取证见 §6.1 第 3 条。
6. 账面收口：`docs/TODO.md` §5 该条目转 `[x]` 并附测量时点；CHANGELOG 新增实施段；
   本方案 §6 追加「实施结果」段。
7. **反向判据**：脚本在未安装 PyYAML 的环境里必须 **fail-closed（exit 1 + 明确原因）**，
   不得退化为"正则解析成功但静默漏 check"。用 `uv run --no-sync --with "" python -c "…"`
   这类可控方式验证不了时，就**直接读代码 + 加一条用例**断 `derive_expected_checks`
   在 `yaml` 缺席时由 `main()` 报 `IMPORT_FAIL` 而非继续——不拿"应该没问题"当证据。

## 6. 实施结果（2026-10-04 回填）

状态：**已按 §5 逐条实取，7 条全达**。落地文件：`scripts/evidence/verify_main_tip.py`（304 行）、
`scripts/evidence/normalize_dump.py`、`scripts/evidence/README.md`、
`tests/governance/test_evidence_scripts.py`（22 条）；登记位 `ARCHITECTURE.md` §4.2；
指针更新 `docs/operations/testing-playbook.md`（新增流程第 8 步 + UTF-16 转码约定）与
`docs/operations/audit-operator-principal-runbook.md`（标明本机探针未入库）。

| # | 判据 | 实取结果 |
|---|------|----------|
| 1 | 最终树 rc=0 且 `=== 总体：PASS ===` | `--merge-sha 91cd79a --merged-at 2026-10-04T01:29:20Z --baseline-max-number 48` ⇒ **rc=0**；`[A]` 两条 analysis（`1887424643` actions @01:29:53Z / `1887425562` python @01:30:24Z，`commit=91cd79a` `results=0` rules 17/43）、`[B]` open **0**、`[C]` `dismissed_at` 非空 **0**（总 46）、`[D]` 最大号 **48**（基线 48）、`[E]` 合入后新建 **0**、`[F]` `Analyze×2` + `ci` 全 success、`[G]` 预期外 **0** |
| 2 | 旧 tip 派生集与硬编码一致，且能多派生 | `bb2b9a8` ⇒ `{Analyze (actions), Analyze (python), assembly, ci}`（与当年逐项一致）；`789309c`（含 `packages/**`）⇒ 多出 **`ha`**；两 tip 均 rc=0 PASS |
| 3 | 新用例全绿且不访网络 | `uv run pytest tests/governance/test_evidence_scripts.py -q` ⇒ **22 passed**；autouse 替身把 `_run`/`gh_api` 装为“调用即 AssertionError”，结构上不可能跑子进程 |
| 4 | ruff / lint 零回归 | `ruff check .` **rc=0**（未新增 per-file-ignores）；`lint_architecture.py` **rc=0**（P1–P12、L-1..L-4 全过，未触 P7-1 手写字面、无 BLE001） |
| 5 | docsync rc=0 + 剥防线必红 | 基线 rc=0；把 `ARCHITECTURE.md` 一条引用改成 `scripts/evidence/verify_main_tip_MISSING.py` ⇒ **rc=1** 并指名 `ARCHITECTURE.md:129: 路径不存在`；还原 ⇒ rc=0、`now == orig`（逐字），且未引入 CRLF/BOM（`crlf=0 lf=174 bom=False`）。自证脚本本机一次性，未入库（结论已在 CHANGELOG 与本表） |
| 6 | 账面收口 | `docs/TODO.md` §5 该条已转 `[x]`（附测量时点与本表同口径数字）；CHANGELOG 新增实施段；本节即 §6 回填 |
| 7 | PyYAML 缺席必 fail-closed | 未靠“应该没问题”：`monkeypatch` 把模块 `_yaml` 置 `None` ⇒ `derive_expected_checks` 抛 `EvidenceDependencyError`；另以 `main()` 报 `IMPORT_FAIL` 且 **rc=2** 钉住。同时验了 `PRECONDITION_FAIL`（`gh` 不可用）与 rc 映射未写反（PASS⇒0 / 未达成⇒1） |

### 6.1 实施期间修掉的三个自身缺陷

1. `gh_api(..., want_key="analyses")` 会 `AttributeError`——`code-scanning/analyses` 与 `alerts` 返回
   **顶层数组**，而 `check-runs` 返回 `{check_runs: []}`。改为 `want_key is None` 直返 +
   `isinstance(data, dict)` 守卫。
2. 用例里用 `Path.write_text(..., encoding="utf-8")` 写含 `\n` 的样本，在 Windows 被转成 `\r\n` 而断言
   失败 ⇒ 取证类断言一律 `write_bytes`（属本批新踩的第九条编码坑，与 §3 表格里的 `newline=""` 同源）。
3. **判据 5 的「基线 rc=0」当时不成立**（推上 `7949357` 后由 CI 推翻，而非本机发现）：§4.2 的引用块里
   把探针原住址写成了反引号 + 尾斜杠的目录形，而 .codeartsdoer/temp **不是仓内路径**（被根
   `.gitignore` 的 `.*/` 忽略）⇒ 本机存在所以本地 docsync 假绿，CI 干净检出上不存在所以红。
   处置（只改措辞，不改判定代码/不加白名单/不放宽阈值）：改成不包反引号的普通文本并明写
   「不是仓内路径」，路径字面值保留以便 `git check-ignore` 复核；`scripts/evidence/README.md` 同步。
   双向实取（§3.1 的 worktree 法）：干净树 + 旧措辞 **rc=1**（与 CI 逐字一致）、干净树 + 新措辞 **rc=0**。
   另存一条**残留盲区**（不属本方案验收面）：门禁本身仍以本机 FS 为基准，已登记 `docs/TODO.md`，
   若要消除需改 `check_doc_sync.py`（产品代码面，按红线先方案后编码）。

### 6.2 未达项：判据 5 曾被推翻一次，已闭环

如实登记：§5 判据 5 首次回填时拿的是**本机脏树 rc=0**，推上后在 CI 变红 ⇒ 那次「已取证据」实际不成立（
详见 §6.1 第 3 条）。2026-10-04 已按订正后的口径重取：干净检出上 rc=0，且反向（旧措辞 ⇒ rc=1）也实取。
本批其余六条判据未被推翻。最终状态下七条均达，但判据 5 是**推翻后重取**的，不是一次过的。

仍需如实说明的局限（不属本方案验收面）：本机只能证明脚本在
**已登录 `gh` + PyYAML 在场**的形态下成立；无 `gh` 凭据的环境会走 `PRECONDITION_FAIL`（rc=2），
**不得被当成通过**。
