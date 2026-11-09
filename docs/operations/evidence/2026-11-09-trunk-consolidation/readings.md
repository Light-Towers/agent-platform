# 主线收口取证：以 github main 为主线合并 feat/web-visual-poc

**结论绑定 rev**：合并提交 `d86ee4db`（parents = `88515cab` + `5c8522cd`），本地 `main` 已
前进到该提交；回退点 = `88515cab`（合并前 main tip，`git merge-base --is-ancestor 88515cab main`
rc=0 ⇒ 仍可达）。**未推送任何远端**（`github-legacy/main` 远端跟踪 ref 仍为 `88515cab`；
`github-legacy` 的 push URL 本就是 DISABLED-no-push）。company 仓（异宗历史，merge-base 报
`Needed a single revision`）本次未动，后续单独同步。

完成强度分档：**已验证**（五字段齐 + 命令当场可复跑 + 结论绑 rev）。

---

## 1. 合并的输入读数（绑 `88515cab` / `5c8522cd` / merge-base `73090d09`）

| 量 | 读数 | 取法 |
|---|---|---|
| main 独有提交 | 6 枚（`88515cab` #129 / `5095a62f` #140 / `b69b7b52` #141 / `7a6f43ea` #143 / `a70d1637` #142 / `ac4ebd32` #145） | `git rev-list --count main ^$(git merge-base main 5c8522cd)` |
| feat 独有提交 | 433 枚 | 同上反向 |
| main 侧改动文件 / 两侧同改 | 352 / 350 | `git diff --name-only 73090d09 88515cab` |
| feat 侧 delta | 541 文件 +71428/−4108 | `git diff --shortstat 73090d09 5c8522cd` |
| 树级差异 | 249 文件；仅 feat 有 126；仅 main 有 4 | `git diff --name-status 5c8522cd 88515cab` |
| 真冲突 | **42 文件 / 175 hunk**（不是 merge-tree 输出的 143 行 —— 那行数列里混了 `Auto-merging`/`CONFLICT` 信息行） | `git merge-tree --write-tree` 结果 tree 的 `^<<<<<<<` 计数 |
| `--no-commit` 落地后未合并路径 | 2（均为 modify/delete） | `git diff --name-only --diff-filter=U` |

## 2. 四处必须人工决策的落差与处置

### 2.1 `agent_runtime/cache.py` + `tests/test_cache.py`（modify/delete）⇒ 接受删除

三条判据（缺一条就不许删）：

1. **API 面全在位**：合并树内 `from agent_runtime.cache import ...` 的 8 种形态
   （`get_cache` / `close_cache` / `reset_cache_config` / `reset_cache_for_tests` / `config` /
   `factory` / `valkey_backend` / 裸 `import agent_runtime.cache`）逐一核过，全部由包
   `__init__.py` 的 `__all__` 或子模块提供；`applications/agent_federation/tests/test_health.py`
   的 `monkeypatch.setattr(agent_runtime.cache, "get_cache", ...)` 打的是包属性，同样命中。
2. **旧专有符号无残留消费者**：`cache_store` 在待删两文件之外引用数 = 0；
   `pending_background_tasks` 已由 `packages/agent-runtime/agent_runtime/background.py` 接管（非丢失）。
3. **main 新增的两个测试已被严格覆盖**（这是上轮"尚未判完"的那项，换量法后闭合）：
   `test_store_empty_tenant_skips_with_counter` → `test_valkey_backend_wire.py:929-939`
   （含"计数分账：`skipped_no_tenant` 是调用方没带租户，与 `error` 混了就查错方向"的语义注释）
   + `test_cache_contract.py:343` + `test_cache_config.py:248`；
   `test_reset_stats_clears_skip_counter` → `test_valkey_backend_wire.py:470-481`
   （显式置 `skipped_no_tenant=1` → `reset_stats()` → 断言 `== 0`），是 main 版的超集。

   > 上轮那次 `git grep -h -E '^def test_'` 返回空是**量法错**：包形态里的测试大量写在类内
   > 或带 `async`，行首不是 `def`。换成不锚行首的函数名全文匹配后才有上面这组数。

### 2.2 `applications/agent_server/db_dialect.py` 被 main 侧带回 ⇒ 移除（保持 `85fb165c`）

决定性事实（推翻上轮"main 侧自动复活旧文件"的说法 —— 它是**新增**，不是残留）：

```
git merge-base --is-ancestor 85fb165c 88515cab   ⇒ rc=1（不是祖先）
git log --oneline --diff-filter=A 88515cab -- applications/agent_server/db_dialect.py
  ⇒ ac4ebd32 chore(release): 公开镜像集成分支批次合入 main（nl2sql + 2026-10 依赖安全批次） (#145)
git ls-tree 73090d09 -- .../db_dialect.py  ⇒ 空
git ls-tree 88515cab -- .../db_dialect.py  ⇒ blob b1695347
```

即：**main 从来没收到 85fb165c（拆 `/health` 的 sql_backend 假灯）这个决策**，而 #145 那批
把 pre-85fb165c 的旧状态整簇带了回来。main 的 `health_router.py:38` 至今还挂着
`sql_backend=detect_dialect(settings.sql_dsn)`。

合并后的树是"半复活"：`config.py` 已无 `sql_dsn`/`sql_max_rows` 字段（feat 的退役赢了）、
`health_router.py` 正文已是 feat 的 nl2sql 意愿位，但 `health_router.py:10` 留下一行孤儿
import。全树 `agent_server.db_dialect` 的真实引用只剩这一行（其余 `detect_dialect` 命中属
`nl2sql_service.services.datasource`，是另一个活模块，别混）。处置：删该文件 + `git checkout
5c8522cd -- health_router.py`（行级 `Compare-Object` 证明合并版与 feat 版只差这一行，`<=` 为 0）。

> 教训形状：`tests/deploy/test_k8s_manifest_wiring.py::test_platform_does_not_inject_sql_dsn`
> 是专门禁止 `SQL_DSN` 这个名字回来的门禁。留着这个模块 = 留着门禁要杀的东西。

### 2.3 `applications/nl2sql-service/nl2sql_service/api/server.py` 同一块被放了两遍 ⇒ 取 feat 版

`-X theirs` 只作用于**内容冲突 hunk**；两侧在不重叠区域各自新增时，两份都会被留下。main 带回的
`_probe_pool` + `handle_ready` 与 feat 的那块逐字节相同（两个 `_probe_pool` 起点 L51 / L87，
偏移恰 36 行；按块 `-ceq` 比对 = BYTE-IDENTICAL=YES），合并后同名函数定义两次 ⇒ ruff
`F811 Redefinition of unused handle_ready`。取 feat 版 = 删一份副本，零信息损失
（`<=` 差行 = 0 已证）。

### 2.4 仅 main 有的 4 个文件逐个定性

| 文件 | merge-base 是否存在 | 来源 | 合并索引终态 |
|---|---|---|---|
| `applications/agent_federation/agent/cache/layers.py` | 有 | feat 主动删除 | absent（删除被正确应用） |
| `packages/agent-runtime/agent_runtime/cache.py` | 有 | feat 主动删除（模块→包） | absent |
| `packages/agent-runtime/tests/test_cache.py` | 有 | feat 主动删除 | absent |
| `applications/agent_server/db_dialect.py` | **无** | **main 新增**（`ac4ebd32` 带回旧状态） | absent（按 §2.2 移除） |

## 3. 依赖没有降级（本次最容易被 `-X theirs` 静默做坏的一格）

- **`uv.lock`**：合并初值是**手工三方合并出来的混合锁** —— 与 feat 同为 7914 行，却有 22 行
  feat 从未有过、另有 `{ name = "requests" }` 21→24、`{ name = "h11" }` 2→3 的计数漂移。
  锁文件不该长这样 ⇒ 改取 feat 版，终态 blob `c2135502` 与 `5c8522cd:uv.lock` 逐字节一致。
  成立依据：feat 与 main 的 **571 条 `name`/`version` 钉版行差异 = 0**，且六个安全钉逐个点名
  三方一致 —— Pillow `13.0.0` / langfuse `5.0.4` / cryptography `50.0.0` / aiohttp `3.14.5` /
  requests `2.34.2` / transformers `5.20.2` ⇒ feat 的锁本来就带着 main 的 Dependabot 升级。
- **全部 `pyproject.toml` 逐个与 main 比 blob**：根 / `agent-core` / `shared-schemas` /
  `exhibition-agent` / `kefu-service` / `knowledge-service` **同 blob**；`agent-runtime` 与
  `agent_federation` 的差行**全是 feat 新增**（valkey 进主依赖、`auth = ["argon2-cffi>=23.1"]`
  extra、per-file-ignores 收缩），main 侧独有行丢失数 = 0；`nl2sql-service` 丢行 = 0。
- **`.env.example` 丢的 6 行**：3 行是 `85fb165c` 明文退役（`SQL_DSN=` / `SQL_MAX_ROWS=100` /
  其表头），3 行是**改写而非删除** —— `NL2SQL_SERVICE_URL` 仍在合并版 L258（注释更详），
  PG 段与语义缓存段表头改写为 Valkey 单轨口径。`docker-compose.yml` 丢的 1 行 = `SQL_DSN` 注入，
  同属明文退役。
- **`applications/agent_federation/pyproject.toml` 的 per-file-ignores 少了 `agent/cache/semantic_cache.py`**
  一行：该文件仍有 1 处 `except Exception`，我原本推测这会判 BLE001 红 —— **实测 ruff rc=0，
  推测不成立**，故未据此改任何东西（见 §5 的量法教训）。

## 4. 门禁与测试（全部绑 `d86ee4db`，且在**非 `.tmp-scratch` 载体**上取）

> 取证件本身会把 tip 往前推一枚；终 tip 的复跑读数见 §8，**引用本节时连带它**。

载体：`git worktree add --detach ../ap-trunk-check d86ee4db`（临时校验树，取证后已
`git worktree remove --force` + `prune`，未入库）。
**为何必须换载体**：见 §5 最后一条 —— 树放在 `.tmp-scratch/` 下会让一条治理测试必然假红。

解释器复用主工作区 venv（worktree 无 `.venv`，`uv run` 会在那儿重建整棵依赖树），并用
`PYTHONPATH` 把包解析覆盖到校验树；覆盖有效性实证：
`importlib` 逐模块查 `__file__` 前缀，`checked=8 misresolved=0`
（`agent_core` / `agent_runtime` / `shared_schemas` / `agent_server` / `nl2sql_service` /
`knowledge_service` / `kefu_agent` / `exhibition_agent`）。
**注意**：主工作区 `.venv` 的 editable `.pth` 指回主仓路径 —— 不设 `PYTHONPATH` 直接在
worktree 里跑 pytest，测的是**主仓代码**，不能当作合并树的证据。

| session（对齐 Makefile `test` 目标逐行） | rc | 读数 |
|---|---|---|
| root `pytest -q -m "not requires_pg"` | 0 | 1564 passed / 10 skipped / 29 deselected |
| shared-schemas | 0 | 28 passed |
| agent-runtime | 0 | 888 passed / 2 skipped |
| agent-server | 0 | 183 passed |
| federation | 0 | 192 passed / 1 skipped |
| kefu | 0 | 49 passed |
| exhibition | 0 | 381 passed |
| knowledge-service | 0 | 416 passed / 7 skipped |
| nl2sql-service | 0 | 235 passed / 8 skipped |
| `tests/observability`（`--extra otel` 同集） | 0 | 18 passed（**实跑非 skip**，主 venv 有 OTel SDK） |

合计 **3954 passed / 28 skipped / 29 deselected / 0 failed**。

静态门禁（同一棵树）：

- `python -m ruff check . --output-format concise` → rc=0（修 §2.2/§2.3 之前是 F811 一条）
- `python scripts/check_doc_sync.py` → rc=0，0 警告
- `python scripts/lint_architecture.py` → rc=0，含 **P14 语义缓存单轨**（删 `cache.py` 未破该不变量）
- `python scripts/lint_public_mirror.py`（registry）→ rc=0，携带文件 0 / 命中 0 / 台账 1 /
  违规 0 / **警告 1**（ADR-0013 零命中，脚本自述"公开镜像上正是这种形状"）
- `python scripts/lint_public_mirror.py --mode publish --base 88515cab --ref d86ee4db`
  → **rc=0，新增命中 0 处** ⇒ 本次合并没有向公开主线新暴露任何东西

> registry 模式在合并**未提交**时曾报 rc=1（幽灵登记）。定性：它判的是 `@ HEAD`，那时 HEAD 仍是
> main，而 main 的 `docs/adr/` 到 0012 为止、**没有 0013** ⇒ 登记路径"不在 1266 项清单里"。
> 提交后 HEAD 含 ADR-0013（零命中）⇒ 退化为上面那条 WARN。**没有为此改门禁脚本，也没有删台账项。**

**未跑 / 待环境**（按字段 4 明列，不写作"已验证"）：

- `make eval` 启发式：**已跑**，读数与非空转对照见 §9。E1 黄金集的 LLM 质量分
  （`--require-llm`）与 `eval/run_planner_eval.py` 双 Planner 基线**仍未跑**。
- 变异门禁 `make mutation-cache` / `make mutation`：未跑。
- `-m requires_pg` 的 29 条：本次按 Makefile root session 口径**主动 deselect**，需 PG。
- `CACHE_CONTRACT_REQUIRED=1 VALKEY_URL=... pytest packages/agent-runtime/tests/test_cache_contract.py`
  （Makefile L78 那条独立目标）：未跑，需可达 Valkey。
- 126/241 现网回读：未做，本次纯仓库侧动作。
- **未推送任何远端**：`main` 前进只在本地；推 `github-legacy` 属 D3，且 433 枚历史级暴露
  需另行决策（publish 模式只判"这次新公开了什么"，不判历史里已有的）。

## 5. 本轮踩到并纠正的量法错（每条都曾给出错结论）

1. `git rev-parse --quiet -- "rev:path"` 的 `--` 会走**路径模式** ⇒ 打出的是字面串，据此判
   "字节相同"= 0 是假的。
2. `git cat-file -e "rev:path"` 配合 PowerShell `2>$null` + `[bool]` 把 main 侧存在的
   `db_dialect.py` 读成不存在 ⇒ 换成 `git ls-tree`（不存在则返回空行）才给出货真价实的三侧表。
   **这条直接推翻了我上一轮"main 保留了旧文件"的定性**：真相是 main 新增。
3. `git rev-parse` 失败时**把查询串原样回显**，`if ($x)` 于是把失败当存在 ⇒ 判 ADR-0013
   "在 main 里存在"（错）。同样换 `ls-tree` / `ls-files -s`。
4. PowerShell 5.1：`[string](if(...){}else{})` 与 `-f` 参数位里的 `(if ...)` 都不是表达式
   （`The term 'if' is not recognized`）—— 本轮又踩三次；`$(if ...)` 在字符串拼接里才合法。
5. `powershell -File x.ps1 -Files @('a','b')` **不能传数组**，第二个元素会被当位置参数吃掉；
   改 `-Command "& .\x.ps1 -Files 'a','b'"`。
6. `git show rev:path > 文件` 经 PS 重定向写成 UTF-16 ⇒ `git diff --no-index` 报
   `Bin 7970 -> 4896 bytes`，看着像整文件不同；行级 `Compare-Object` 才是准的（只差 1 行）。
7. 探测器的正例设计错：我把"孤儿新增型"（main 加了 feat 删掉的行）当成"重复型"写进自测，
   自测当场报 `<<< BLIND`。修法不是放宽判据，而是**如实声明射程**：该型由 ruff F401/F811 负责，
   两道判据互补。自测最终 4/4：两枚有牙 + 无误报 + 射程外如实声明。
8. 树放在 `.tmp-scratch/` 下会让 `tests/governance/test_doc_sync_file_refs.py::
   test_real_tree_pyproject_enumeration_covers_all_tracked` 必然红 —— 它断言枚举到的 path
   的 `parts` 里不含 `.tmp-scratch`，而 REPO_ROOT **自己的路径**就含这一段。
   证伪方式：同一提交 `d86ee4db` 换到 `../ap-trunk-check` 跑 → rc=0。
9. **差点把真内网字面值写进公开镜像谱系**：§8 的 G5 对照里我初稿直接引了控制输出里的
   私有网段字面值。本轮写这一句时先 grep 了一遍本文件（私有网段前缀字面量）才确认为零残留。
   教训不是“门禁会拦”而是：**publish 门禁只在推镜像前跑，不拦本地提交** ——
   一旦落进 `main` 历史就改不回来（分支卫生第 5 条同理）。⇒ 往 `main` 写内容时，
   真网段/真主机名**不得入文**，词形只用在册占位符。
10. **把截断读数当结论**：判 cand-wt-20261106 的台账行时，我用 `Substring(0,200)` 打印
   main 侧整行，截掉了后半句，于是得出“这几条台账文字在 main 里没有对应物”并说了出去；
   扩到整行（宽 333 字）后正好相反 —— main 是超集。⇒ 引“整行”必须同时打**行宽**；
   截断长度小于行宽就是未证完。本轮已口头纠正该句，且它从未入库。
11. **单值输出被按两列索引**：`git rev-list --count main...<b>` 只打一个数，我却按
    `--left-right` 的两列形状 `-split "`t"` 再取 `[0]` ⇒ 拿到 null，"独有 commit 数"整列是
    **空读数**，表格照样打满。于是上一轮说出的"6 条分支独有 commit 都是 0"全部无效。换成
    `git rev-list --left-right --count` 后结论整个反过来：`feat/web-visual-poc` 独有 0，
    dependabot 四条各 1–2，`lineage/intranet-v3-until-2026-10-19` 独有 **797**。
    ⇒ 某一列齐刷刷为空时，先怀疑度量，不要先怀疑仓库。
12. **把 `git diff main <b>` 的 + 侧当分支独有面**（§10 同一个坑的第二次触发，方向相反）：
    本轮对 `fix/dependabot-security-int` 这么算出 2016 行"独有"，而它实际只有 2 个 commit、
    6 个文件。原因是该分支落后 main 441 个 commit，+ 侧把"main 在这 441 个 commit 里删掉/
    改掉的行"也算成了分支的独有信息。正确口径 = 以 merge-base 为原点取**分支自身贡献**
    （`git diff $(git merge-base main <b>) <b>`），再把这些行逐条回查 main 当前版本。
    上次是 - 侧虚高（cand-wt），这次是 + 侧虚高，同一个误读的两个方向。
13. **`2>&1` 把 stderr 计进行数**：`@(git ls-remote --heads company 2>&1).Count` 报 6，
    真 head 只有 3 —— OpenSSH 的 post-quantum 警告占了 3 行。远端 heads 要么丢弃 stderr
    单独取，要么按 `refs/heads/` 前缀过滤后再数；这个数一旦进"恒 2 分支"报警判据就是假报警。
14. **远端读数不能用本地缓存冒充现读**：`refs/remotes/github-legacy/*` 里 dependabot 是
    `brotlicffi` / `major-cb6f23add6` / `minor-and-patch-0e126670a4` 三条，现取
    `ls-remote` 却是 `brotlicffi` / `dnspython-2.9.0` / `minor-and-patch-ef4e6ffbb8` ——
    GitHub 服务端 dependabot 在这期间自己建过枝。⇒ 分支卫生第 3 条写的就是 `ls-remote`，
    `for-each-ref refs/remotes` 只能算"上次 fetch 时的状态"，引用时必须标出是哪一种。
15. **§5-10 在同一轮里复犯**：定位 §11.4 的锚点候选行时我又用 `Substring(0,60)` 打整行，
    短于 60 字的行直接抛 `ArgumentOutOfRangeException`，锚点清单只出一半就断了 —— 上次那次的
    形状是"截断当结论"（没说错但证据不足），这次是"截断自己崩"（连证据都没出）。⇒ 同一条
    教训的两种失效形状都出现过，说明**读过坑不等于写下一条命令时不踩**；能兜住的只有现取校验
    （整行 + 行宽一起打），不靠自觉。本轮因此把 m15/m16 全系列锚点脚本统一成
    `line=<1-based> width=<len> [<整行>]` 三件套。
16. **PowerShell 里 `git rev-parse HEAD^{tree}` 必须加引号**：`{tree}` 被 PS 当**脚本块**解析，
    参数被拆开后再喂进去，报的是 `fatal: ambiguous argument 'dAByAGUAZQA='`（那段 base64
    解码就是 `tree`），看上去像 git 不认 `^{tree}`，其实是载体把参数吃了。写成
    `git rev-parse "HEAD^{tree}"` 才对。⇒ 凡带 `{}` 的 rev 后缀（`^{tree}` / `^{commit}`）
    在 PS 下一律加引号；本轮两次触发（第二次才想起来查形状）。
17. **内联多行 Python 在 PS 5.1 下不可用**：`python -c "…\n…"` 里的 `\n` 不被解释，得到
    `SyntaxError: unexpected character after line continuation character`，import 解析自证
    整条没跑起来。修法不是转义，是**改成落盘脚本再跑**（本轮 = `.tmp-scratch/ap-visual/` 下的
    `m14_import_resolution_probe.py` + `m14-probe.ps1`，不入库）。与 §5 前几条同源：
    都是载体选择问题，不是被测物问题。
18. **复核"原句已从账上消失"时，`git grep -c <原句>` 与"`rc≠0` 就是零命中"两种读法都会骗人**
    （本轮两种形状同时踩到）：
    ① **命中数里含我自己改写句对原句的引号复述** —— 对 §11.4 原句跑 `git grep -F -c` 得
    `rc=0 / 1 命中`，而那 1 条正是新写的「本节初版写着"…整体重跑"」。照上一轮的教训换了
    只可能出现在原句里的连接形状才判得动。
    ② **探针可以整条是哑的却报"零命中"**：拿含**半角双引号**的串在 PS 5.1 下传给 git，参数被
    拆开 —— 吵的版本是 `fatal: unable to resolve revision: tip` / rc=128，**哑的版本是 rc=1，
    与"确实不存在"完全同形**。本轮实测：我在**改写前的提交 `652378a6` 上跑同一条**也得到 rc=1，
    而那句话当时明明在账上 ⇒ 探针无牙，结论当时是假的。
    ⇒ 复核必须同时满足三条：**用只可能出现在原句里的连接形状**（如 `：§4 那 3954 passed`，
    绕开引号本身）、**先在必含该句的对象上跑一个 control**（`652378a6` 上 rc=0 才允许引 main 的
    rc=1）、**rc 分档判定**（0 = 命中 / 1 = 零命中 / ≥128 = 命令根本没跑成，不许把"非 0"统称
    零命中）。本轮两条被改写的原句最终都按这三条验过：`：§4 那 3954 passed` 与
    `整体重跑（§8 那条限定同样适用` 在 `652378a6` 各 **1 命中**、在 `main` 各 **rc=1**。
19. **自证件的 stdout 被管道吞掉时，它的总结论照样能报"通过"**（本轮实踩，与 §5-18 同族，但这一型的
    载体是自己的取证脚本而不是 git）：给 m5 加固件写守卫自证时，第一版把每条用例包进函数、函数末尾
    `return ($rc -eq $expectRc)` ⇒ 函数体内的 `Write-Output` 全部进了**函数输出流**，调用点
    `$ok = $ok -and (Run-Case …)` 拿到的是"若干字符串 + 一个布尔"的数组，于是 **6 行 rc 一行没打印**，
    末行却照样打出 `teeth overall=OK`（`-and` 把非空数组按真处理）。我差点照这个 OK 写账面 ——
    暴露它的原因是**期望出现的 6 行整体缺席**，不是任何一条报错。
    ⇒ 处置：① 用例打印放**脚本作用域**，不进函数返回值；② 结论用计数器 `fail-cases=N` 而不是布尔摘要；
    ③ 自证件的判据写成"**每条用例的 rc 都看得见**"，看不见就当未跑。通用化一句：
    **探针的 stdout 形状本身就是证据的一部分** —— 只审 rc 不审"该出现的行有没有出现"，就会放过哑探针
    （§5-18 是"rc 与不存在同形"，本条是"结论与空跑同形"，同一个失效面的两个入口）。

## 6. 登记为遗留、本次不顺手改

- `applications/agent_federation/requirements.txt:5` 仍写
  `pip install -e "./agent_federation[observability,cache,docs,excel]"`，而 `cache` extra
  已随 ADR-0013 单轨化删除 ⇒ feat 侧自带的陈旧指引，属另一项决策，未并入本合并。
- `trunk-candidate` 分支与其 worktree `.tmp-scratch/ap-visual/trunk-wt`：现与 `main` 同指
  本取证件所在提交（现取：`git rev-parse main trunk-candidate` 应相同）、独有提交 0
  ⇒ 按分支卫生第 1 条属死枝。`feat/web-visual-poc` 是主工作区当前
  检出分支且并行线（ext 8 件）仍在动，**未动**。两者的清理都等用户批。
  → 用户 2026-11-09 已批“当场删分支 + worktree”⇒ 执行判据即本条登记的内容（与 `main`
  同点、独有 commit 0），用 `git branch -D trunk-candidate` + `git worktree remove --force`；
  `-D` 而非常规 `-d` 的理由：主工作区 HEAD 在 `feat/web-visual-poc`，而 trunk-candidate
  不是它的祖先 ⇒ `-d` 会拒。本条就是那条“确证退役结论”的登记处。
- **`AGENTS.md` 里同一路径两种写法并存**（本次合并的取值结果，不顺手改）：
  现取 `git diff --stat 5c8522cd main -- AGENTS.md` ⇒ `1 insertion(+), 1 deletion(-)`，
  即合并后两分支历史在 AGENTS.md 上只剩这一行差异：观测面第 3 条里的
  `docs/operations/env-126-inventory.md` 被 main 侧去了反引号（脱敏时代的形状），
  而「内网测试环境 126」节开头那条仍是 feat 侧的反引号写法。两边都不红（该路径在
  `88515cab` / `5c8522cd` / `main` 三侧**均已入库**，已用 `git ls-tree -r --name-only` 逐侧验过），
  存在性覆盖由带反引号那条提供 ⇒ 不补。真要统一得先答“公开镜像分支上该文件会不会不在”，
  那是另一个决策（分支卫生第 4 条射程）。
- **同一型默认值还留在 `m6-final-gates.ps1` 里**（本批只加固了 session runner，没动它）：它的 `-Wt`
  默认值是 `d:\Study\github\ap-trunk-final`（本轮实取 `Test-Path` = `False`，上轮已 `worktree remove`），
  且它的 `Push-Location` 也没带 `-ErrorAction Stop` ⇒ 不显式传 `-Wt` 时同样是
  "在调用方目录继续跑完 6 格并打出正常格式"的形状。本批所有门禁调用**都显式传了 `-Wt`** 且核对过首行
  `HEAD=`/`tree=` 与目标 sha 一致 ⇒ 账面读数不受影响，但**件本身未改**。为什么不顺手改：它是门禁读数
  的载体，判据与在册量具不得擅动（AGENTS.md《禁止行为》末条「所有代码优化/重构必须先制定
  方案」），要改就得先给方案 —— 与 session runner 不同，那边只是本地复跑便利，没有判据。

## 7. 复跑命令（本仓 Windows 侧，无 make）

```powershell
# 载体必须是"不在 .tmp-scratch 下"的 worktree，否则 §5-8 那条假红会复现
git worktree add --detach ..\ap-trunk-check d86ee4db
$Wt='d:\Study\github\ap-trunk-check'
$Py='d:\Study\github\agent-platform\.venv\Scripts\python.exe'
$env:PYTHONPATH = "$Wt\packages\agent-core;$Wt\packages\agent-runtime;$Wt\packages\shared-schemas;$Wt\applications;$Wt\applications\agent_federation;$Wt\applications\kefu-service;$Wt\applications\knowledge-service;$Wt\applications\nl2sql-service;$Wt\applications\exhibition-agent"
Push-Location $Wt
& $Py -m ruff check . --output-format concise
& $Py scripts\check_doc_sync.py
& $Py scripts\lint_architecture.py
& $Py scripts\lint_public_mirror.py
& $Py scripts\lint_public_mirror.py --mode publish --base 88515cab --ref d86ee4db
& $Py -m pytest -q -m "not requires_pg" --tb=no -rf
& $Py -m pytest packages/agent-runtime/tests -q
Pop-Location
git worktree remove --force ..\ap-trunk-check; git worktree prune
```

本轮新增的探测器 / 复跑器脚本 `m4-dup-block-scan.ps1` / `m4-dup-scan-selftest.ps1` /
`m5-run-trunk-sessions.ps1`（及 §8 的 `m6-final-gates.ps1`）都在 `.tmp-scratch/ap-visual/` 下，
**不入库**（该目录 gitignored），
判据本体已留在 §2/§3/§5 的文字里，不依赖脚本才能核对。其中 m4 探测器的用途与两型分工见 §5-7。

---

## 8. 终 tip（本取证件落地后）的复跑读数

本取证件所在提交（下称 **终 tip**）相对 `d86ee4db` 是**文档单提交**：只动本文，
`.py` / `.toml` / `uv.lock` / manifest 这类**可执行面**零变更。按字段 1「换 rev 必须重跑」，
在**又一个**非 `.tmp-scratch` 载体
（`git worktree add --detach ../ap-trunk-final <终 tip>`，取证后已 remove + prune）上对终 tip 复跑：

| 门禁 | rc | 读数 |
|---|---|---|
| `python -m ruff check . --output-format concise` | 0 | All checks passed! |
| `python scripts/check_doc_sync.py` | 0 | 通过，0 警告 |
| `python scripts/lint_architecture.py` | 0 | 含 P14 语义缓存单轨 |
| `python scripts/lint_public_mirror.py`（registry） | 0 | 0 文件 / 0 命中 / 台账 1 / 违规 0 / 警告 1 |
| `python scripts/lint_public_mirror.py --mode publish --base 88515cab --ref <终 tip>` | 0 | **新增命中 0 处** |
| `python -m pytest tests/governance -q` | 0 | 521 passed / 1 skipped |

载体：`D:/Study/github/ap-trunk-final`（**仓外**、非 `.tmp-scratch`），worktree 无 `.venv` ⇒
用主工作区解释器 + `PYTHONPATH` 覆盖（理由与 misresolved=0 的实证同 §4）。
复跑器：`m6-final-gates.ps1`（同样不入库）。

**G5 「新增命中 0 处」的非空转对照**（不绑终 tip，绑固定 sha，所以可直接复跑）：
同一 linter 对 `--base 88515cab --ref 12f03c8f`（`lineage/intranet-v3-until-2026-10-19`，
未脱敏的内网历史线）报 **新增命中 172 处 / rc=1**，命中行含私有网段字面值与
`packages/agent-runtime/agent_runtime/sandbox.py` 的 `docker_host` 示例（本文件不引用这些
字面值 —— `main` 是公开镜像谱系，真网段属禁止入库项，词形沿用在册的 `<internal-ip>` /
`<internal-host>`）。⇒ 本格有牙，0 处不是因它根本不扫。
G4 的那 1 项警告是台账项零命中的 WARN（`docs/adr/0013-*.md` 已脱敏），非硬红。

本节 6 格**不含** 10 个 pytest session —— 取数当时未对终 tip 整体重跑，§4 那 3954 passed
绑的是 `d86ee4db`，本节只有这 6 格。**这个限定已由 §12 解除**（10 个 session 于
`652378a6` 整体重跑、10/10 rc=0、合计与 §4 逐项相等），引用本节时改连 §12 一起引，
不要再引"未整体重跑"。

当时为什么可以不重跑：用「**可执行面**零变更」而不是「代码树等价」——后者是错的，三棵
tree 对象名各不相同（`d86ee4db` `59433cd7` / 本节 tip `cb155db3` / `652378a6` `4de874a7`），
可直接验（**PS 下 `{}` 后缀必须加引号，见 §5-16**）：`git rev-parse "d86ee4db^{tree}"` vs
`git rev-parse "<tip>^{tree}"`。可执行面零变更同样可直接验，但**这条是参数化的、会随 tip
前进而变**：`git diff --name-only d86ee4db <tip>` 在本节落地当时只列出本文一个路径，tip
走到 `652378a6` 时列出**两个**（本文 +
`docs/plans/plan-platform-tenant-workspace-identity-2026-10-18.md`，即 §11.1 并入的那 19 行
台账及其改写句），仍然全是文档面 ⇒ "可执行面零变更"这个结论没变，**路径数变了**。

**顺手抽掉一个错说法**：本节初稿写过一句“文档面由 `tests/governance` 守”，实读不成立 ——
`check_doc_sync.py` 的存在性校验只扫 `AGENTS.md` / `ARCHITECTURE.md` / `README.md` 三份
（`DOC_FILE_REF_DOCS`），`tests/governance/` 里也没有以 `docs/operations/evidence/` 为射程的用例。
⇒ 本目录的引用完整性**无门禁覆盖**，本文里的路径对不对靠人工；这也是把上面两条自证命令
写进文档而不是只写结论的原因。

**终 tip 故意不在本文写死 sha**：写死就自我指涉了 —— 补 sha 的那次编辑本身又是一枚新提交，
文档永远追不上自己的 sha。现取用 `git log -1 --format=%H main`。本节 6 格只对**取数当时**
那个 tip 成立；tip 一旦前进（哪怕只改本文），要么重取，要么把限定一起引。

---

## 9. `make eval` 启发式（本批唯一补跑的评测面）

载体 `D:/Study/github/ap-trunk-eval`（仓外、非 `.tmp-scratch`，取完已 remove + prune），命令
就是 Makefile `eval` 目标的等价式（本机无 make，但不走 `uv run` —— worktree 无 `.venv`，
理由同 §4）：`python eval/run_eval.py --fail-below 0.8`，解释器用主工作区 venv + `PYTHONPATH` 覆盖。

- **rc=0，启发式路由准确率 15/15 = 100%**。逐条命中形状：sql 4 / search 3 / rag 3 /
  direct 2 / code_execution 3，无一条误路由。
- **阈值有牙对照**：同一命令换成 `--fail-below 1.01` → **rc=1** 并打印「未达门禁阈值 101%」
  ⇒ 那个 100% 不是“阈值设得低所以必过”；而 “集子是空的” 这一型也不成立 —— 真读到了
  15 条逐行表格与 15/15 的分母，不是 0/0。
- 射程边界：只跑**确定性启发式**这一层（= `make ci` 守的那层）。**E1 黄金集的 LLM 质量分**
  （`--require-llm`，缺 key 时显式 SKIP rc=2）与 `eval/run_planner_eval.py` 双 Planner 基线
  仍未跑 —— 前者需真模型配额且属发布决策，不拿启发式 100% 替它发声。

---

## 10. 两个遗留 cand-wt worktree：独有面定性与处置

用户问“cand-wt 中独有的内容是不是主分支所需要的”。先定“独有”的口径，否则
`git diff main` 那 404 / 4589 行删除量会被读成“丢了 4589 行”：

| worktree | HEAD 是否 `main` 祖先 | 未提交面 | 相对 main 的**独有行** |
|---|---|---|---|
| `.tmp-scratch/ap-visual/cand-wt` | `a3a808e5` rc=0 | 2 件 staged | 2 |
| `.tmp-scratch/ap-visual/cand-wt-20261106-142601` | `2d5bb0ff` rc=0 | 28 改 + 7 未跟踪 | 11（分属 6 个文件） |

“main 有而 worktree 无”那几千行是**该 worktree 比 main 旧**，不是它的独有信息；
独有面 = `git diff main --numstat` 里 `ins>0` 的文件之和。

未跟踪 7 件在 `main` 里**全有同名入库版**（`git ls-tree main -- <path>` 逐条有 blob）；
用 `git hash-object`（不带 `-w`）比 blob：3 件逐字节等价（`applications/agent_server/api/auth_router.py`、
`applications/agent_server/tests/test_auth_router.py`、`scripts/evidence/face_basis.py`），
4 件不同；而不同处的 worktree 侧独有行**全是被 main 取代的缺陷形状**：

| worktree 侧独有行 | main 侧对应 | 性质 |
|---|---|---|
| 表格单元里裸竖线 | 同一行已改为转义形 | 裸竖线破表 |
| 「批准范围仅 §4 五条」 | 已订正为六条，且订正说明原文就写着“本行原写五条是初版遗留” | 旧数 |
| 无占位符的 f-string 参数化行 | 同一行去掉了 `f` 前缀 | ruff F541 型（main 的 ruff rc=0 反证） |
| PEM 私钥头的**整串字面值** | 改为运行时拼接，注释里写明理由：不让测试自己成为 publish 门禁的“新公开凭据”命中 | 合过来会让 G5 判红 |

文档类 11 行：逐条取独特短语 `git grep -F <短语> main`，**9/9 命中**；再抽 main 侧整行（带行宽）
读，main 版是超集。cand-wt 那 2 行同型：AGENTS.md 只差反引号；ADR-0013 那行 worktree 版仍带
**未遮的私有网段示例**，main 版已换成在册 `<internal-ip>` ⇒ 拿进 main 是脱敏回归（就是 §5-9 那一型）。

⇒ 结论：**不是“先合并再删”那一型**（独有面无可合之物，两处还是 main 有意修掉的）。已按用户
2026-11-09 批示对两个 worktree 做 `git worktree remove --force`。

**删前的可逆处置**：`remove --force` 对两类内容的可逆性不同 —— staged 改动的内容已进对象库，
按 blob hash 随时 `git cat-file -p` 找回；而 **untracked 文件从未入库，删了就真没了**。
⇒ 6 件内容异于 main 的文件（4 件 untracked + 2 件 staged）已原样复制到
.tmp-scratch/ap-visual/cand-wt-retired-20261109/（该目录 gitignored、**不入库**，按本文规矩
不用反引号包裹），附 BLOB-HASHES.txt 记两个 staged 件的 blob。备份只是防“比对漏看”，
不是保留它们的理由 —— 上面的逐行判定已说明 main 不需要。

**复审触发条件**（分支卫生第 2 条，没有复审条件的登记不许写）：若日后出现“某条独有行在
`main` 里找不到对应事实”的证据（典型来源：拿 `git log -S<短语>` 查不到出处），则按本节
表格逐行复原；判定只需上面那三条命令（is-ancestor / diff --numstat / hash-object 对 blob），
不依赖本轮上下文。另需记住两个量法陷阱：存在性只用 `git ls-tree`（`rev-parse` 失败时会回显查询串）、
引整行必须同行宽一起看。

---

## 11. 本地分支体检：7 条分支的独有面定性与 4 条死枝处置

量具（两枚都在 `.tmp-scratch/ap-visual/` 下，**不入库**）：`m7-branch-health.ps1` 取
「独有 commit 数 / 落后 main 数 / 是否 main 祖先」三列；`m8-branch-unique.ps1` 取
「相对 merge-base 的自身贡献 + 逐行回查 main」。判据链三段，各答一件事：
`git rev-list --left-right --count` 答"有没有独有 commit"，`git cherry -v` 答"这些补丁是否
已在上游"，m8 的逐行回查答"内容在不在 main"。缺第三段就会把"比 main 旧"读成"有独有信息"
（§5-12 本轮就是先缺了第三段才虚报 2016 行）。

体检起点 `main = ce8487a0`，7 条非 main 分支实测：

| 分支 | 独有 commit | 落后 main | 是 main 祖先 | `git cherry` | m8 口径的真独有面 | 判定 |
|---|---|---|---|---|---|---|
| `feat/web-visual-poc` | 0 | 8 | 是 | 全 `-` | 无（tip 已在 main） | **保留**：主工作区当前检出，且 ext 8 件仍未提交 |
| `docs/dependabot-round4-2026-10-24` | 1 | 441 | 否 | `-` 已上游 | 14 行 = §13.4 的**实施前草稿**（main 侧同小节已改写成「已实施，2026-10-25」） | 死枝 |
| `fix/dependabot-pillow-13-2026-10-24` | 1 | 440 | 否 | `-` 已上游 | 方案文档那个 blob 与 main **逐字节同一**；uv.lock 88 行全在 main；只剩 5 行旧注释写法被 main 重写 | 死枝 |
| `fix/dependabot-security-oct-2026-10-24` | 2 | 442 | 否 | 2 枚 `+` | 依赖批次已在 main（uv.lock 自身贡献 423 行 not-in-main=0）；真独有只剩 AGENTS.md 2 行 | 死枝 |
| `fix/dependabot-security-int` | 2 | 260 | 否 | 2 枚 `+` | **19 行文档台账**（下节） | 并入 main 后转死枝 |
| `lineage/intranet-v3-until-2026-10-19` | 797 | 1113 | 否 | — | §8 那格 G5 有牙对照的载体（`12f03c8f`，172 处命中） | 保留，**禁删**（已在册） |
| `mirror/nl2sql-ttl-and-006-slim` | 4 | 439 | 否 | 4 枚 `+` | 公开镜像载体：按分支卫生第 5 条不住在「恒 2 分支」计数里，且未累积第二条 | 保留 |

**那 2 行 AGENTS.md 为什么算"被取代"而不是"丢了"**：一行是「上 126 前先记住**六**条容易踩死的
差异」（main 现为七条），另一行是第 7 条里的「docker+git 齐、空闲 39G/13G，**同机只有我们自己的
东西**」—— main 已用 2026-10-28 实取把这句订正成错的（241 的 moby 上常驻整套观测后端 +
exhibition-dashboard，全与那块 `ROTA=1` 单盘同盘）。⇒ 分支侧那 2 行是 main **有意改掉**的形状。
判定用的是"同一位置 main 有更新版"，不是"main 没这句话"。

**可逆性前置读数**（决定要不要备份）：`git for-each-ref --contains` 实取 —— 其余 4 枚独有 commit
在 `github-legacy` 上都有同名远端分支兜着；只有 `43f86c68` / `372870a4` **只被
`fix/dependabot-security-int` 这一个 ref 引用**。本批纪律是不推任何远端 ⇒ 那条分支一删，
那两枚对象只剩 reflog / gc 窗口，没有持久副本。这是下一节必须先做的原因。

---

### 11.1 唯一真独有面（19 行台账）并入 main

用户批「合入 main，并同步改掉那句『只存在于内网分支』」。落地提交 `7d9c7116`
= `git cherry-pick -x 43f86c68`（干净 auto-merge，19 行落在 §9.16 ⑧ 台账末尾）
**同提交内**改写 `docs/plans/plan-platform-tenant-workspace-identity-2026-10-18.md`
原第 657 行那句「台账里这条之后的文字只存在于内网分支：镜像 `08237f8` 不含它」——
它随本次并入变成假陈述，按"不在账上留已变假的陈述"就地改成带判据的限定，改写后的那句
自记实测：`mirror/nl2sql-ttl-and-006-slim`（含其远端 tip `a6753c9c`）与
`lineage/intranet-v3-until-2026-10-19` 上本文件对「第二批追加发布」`git grep -c` **均 rc=1**
（零命中）⇒ 公开侧不变，本轮只动 main 一侧。

为什么必须同提交：分两个提交，中间那个 tip 就带着一个已假的说法在账上。

**并入后复核**：`m8-branch-unique.ps1 -Base 7d9c7116 -Branches fix/dependabot-security-int` 实取
⇒ 那 6 个文件自身贡献**全部** `not-in-main=0`（含本文档那 19 行），整条分支转死枝，备份需求随之
消掉（内容已在 main，不再依赖 reflog 窗口）。注意读数里 `blob-vs-main=differs` 与
`not-in-main=0` 并存是对的：blob 不同源自行级改写（657 那句），不是内容有缺失。

`7d9c7116` 上 6 格实取（载体 = 仓外 worktree `d:/Study/github/ap-doc-wt`，非 `.tmp-scratch`）：
G1 ruff `rc=0` / G2 doc_sync `rc=0`（0 警告）/ G3 arch `rc=0`（含 P14）/ G4 registry `rc=0`
（0 文件 0 命中，台账 1，违规 0 警告 1）/ **G5 publish `88515cab..7d9c7116` 新增命中 0 处 `rc=0`**
/ G6 governance `521 passed, 1 skipped`。G5 本格有牙，对照见 §8（同一 linter 对 `12f03c8f`
报 172 处 / rc=1）。⇒ 那 19 行含 `zhanggui-*` 这类内部项目名，但它**不在门禁口径内**且
main 早已有 40 处同词形、镜像树同样含 ⇒ 不是本批新增暴露面（这条是实测，不是推断）。

---

### 11.2 死枝处置登记（分支卫生第 1 条要求的"确证退役结论"就写在这里）

用户批「登记判定后进取证件，再 `git branch -D`」。执行 4 条：`docs/dependabot-round4-2026-10-24`、
`fix/dependabot-pillow-13-2026-10-24`、`fix/dependabot-security-oct-2026-10-24`、
`fix/dependabot-security-int`。`feat/web-visual-poc` 虽独有 commit = 0，但它是主工作区当前检出且
ext 8 件在动 ⇒ **不删**，等那条线收口后用 `-d` 即可（那时它是 main 祖先）。

为什么必须 `-D` 而非常规 `-d`：这 4 条都**不是** main 的祖先（独有 commit ≠ 0），
`-d` 的"已合入"检查会拒；而"内容已在 main"是 §11 表格里 m8 的逐行结论 + `git cherry` 的
补丁级结论，不是 ancestry。⇒ 本条就是那条确证退役结论的登记处。

**复审触发条件**（第 2 条：没有复审条件的登记不许写）：
① 若在 main 里查不到某条独有行的对应事实（典型来源：`git log -S<短语>` 查不到出处）⇒ 按 §11
表格逐行复原。复原成本分两档：那 3 条 dependabot 枝在 `github-legacy` 上有同名远端分支，
`git fetch github-legacy` 即回（现取 sha 逐字相同：`ba01872c` / `1b2119e4` / `f8f6b0cb`）；
`fix/dependabot-security-int` 无远端副本 ⇒ 窗口内 `git cat-file -p 43f86c68`，窗口过后只能靠
本文 §11.1 的文字结论 —— 而那 19 行已经并入 main，所以真需要复原的场景只剩"我判定错了"。
② 只要 `zhanggui-*` 这类内部项目名将来被列进门禁口径 ⇒ §11.1 那句"不是新增暴露面"立刻失效，
必须复审这 19 行该不该留在 main。

---

### 11.3 远端 heads 超标：登记为已知条件（用户批）

**现取**（`git ls-remote --heads`，不是本地缓存 —— 理由见 §5-14）：

- `github-legacy` **9 条**：`main = 88515cab`（就是本文一路用的公开基线）、
  `mirror/nl2sql-ttl-and-006-slim = a6753c9c`、`feat/nl2sql-meta-build-recovery`、
  `docs/dependabot-round4-2026-10-24`、`fix/dependabot-pillow-13-2026-10-24`、
  `fix/dependabot-security-oct-2026-10-24`、`dependabot/uv/` 3 条
  （`brotlicffi-1.2.1.0` / `dnspython-2.9.0` / `minor-and-patch-ef4e6ffbb8`）。
- `company` **3 条**：`main = fe22794c`、`feat/web-visual-poc = d4d3d329`、
  `lineage/intranet-v3-until-2026-10-19 = 12f03c8f`。

两条都 > 2 ⇒ 触分支卫生第 3 条的报警项。**为什么本批不在远端清**：`github-legacy` 的推送 URL 是
`DISABLED-no-push`（脱敏闸门），且 `dependabot/uv/*` 由 GitHub 服务端自动建枝、本地删不动
（现取比本地缓存多出一条新的 `dnspython-2.9.0` 就是证据）；`company` 那侧是"后续单独同步"，
本批纪律是不推任何远端。⇒ 如实登记，不假装达标。

**复审触发条件**：
① 恢复 `github-legacy` 推送能力时，第一批要清的就是上面 3 条 dependabot 枝 + 已并入 main 的
3 条死枝同名远端；动手前先按 publish 模式确认它们没被当作公开基线引用（`main = 88515cab`
是基线，不能碰）。
② GitHub 侧 dependabot 关掉自动建枝或收成 security-only 之后 ⇒ 重跑 `ls-remote`，那时
>2 才算真违规，不再是"第三方在服务端建"这一型。
③ `company` 同步完成时，`ls-remote --heads company` 期望读数 = 3（`main` + 集成分支 +
已登记禁删的 `lineage/intranet-v3-until-2026-10-19` 载体），出现第 4 条才当周处理。

---

### 11.4 本节自己的 tip 限定

本取证件所在提交（现取 `git log -1 --format=%H main`）相对 `7d9c7116` 只有文档提交、
只动本文 —— 自证 `git diff --name-only 7d9c7116 main` 只列出本文这一个路径。枚数改成现取
`git rev-list --count 7d9c7116..main`：本节初版写的是"单提交"，那时确实是 1；此后每补一格
就 +1，所以那个数不该写死在文里（§5-10 的同族形状：把取数当时的计数当成永久属性）。

10 个 pytest session 本节初版写着"**仍未**对本节 tip 整体重跑" —— **该限定已由 §12 解除**：
`652378a6` 就是本节所在 tip，10 格已在它上面整体重跑、全 rc=0。保留的限定只剩下面这两条：
§11.1 那 6 格绑的是固定 sha `7d9c7116`，本节所在 tip 的 6 格是**另跑的一轮**；结果仍按 §8
口径不写死 sha —— 跑就绑当时 tip，不跑就别引。

---

## 12. 10 个 pytest session 对 `652378a6` 整体重跑（解除 §8 与 §11.4 各自那条限定）

为什么补这一格：§8 与 §11.4 都写着"未整体重跑"，而 §4 的 3954 绑的是 `d86ee4db`。
主线收口收尾时不该把这句话留在账上 —— 它当时的性质不是"没必要跑"，是"还没跑"。
本格只做**复跑已有校验件**，不新开判据。

**载体**：`git worktree add --detach d:/Study/github/ap-trunk-sessions 652378a6`（**仓外**、
非 `.tmp-scratch`，理由见 §5-8；tree = `4de874a7`，与 §11.1 那 6 格用的 `7d9c7116`
tree `18f2c5da` 只差文档 blob）。取证后已 `git worktree remove` + `prune`，未入库。
**解释器**：主工作区 `.venv` 的 python（worktree 无 `.venv`，`uv run` 会在那儿重建整棵依赖树），
`PYTHONPATH` 覆盖到 worktree。

**覆盖有效性本轮重做，不再只引 §4 那句**：探针 `.tmp-scratch/ap-visual/m14_import_resolution_probe.py`
+ 包装 `m14-probe.ps1`（都不入库；为何落盘而不是 `python -c` 见 §5-17）实跑 →
8 个包（`agent_core` / `agent_runtime` / `shared_schemas` / `agent_server` / `nl2sql_service` /
`knowledge_service` / `kefu_agent` / `exhibition_agent`）的 `__file__` 前缀**全部**落在 worktree 内，
`checked=8 misresolved=0`，**probe rc=0**。不设 `PYTHONPATH` 直接在 worktree 里跑的后果照 §4：
测的是主仓代码，不能当合并树的证据。

| session（逐行对齐 Makefile `test` 目标） | rc | 读数 |
|---|---|---|
| root `pytest -q -m "not requires_pg"` | 0 | 1564 passed / 10 skipped / 29 deselected（153.55s） |
| shared-schemas | 0 | 28 passed |
| agent-runtime | 0 | 888 passed / 2 skipped |
| agent-server | 0 | 183 passed |
| federation | 0 | 192 passed / 1 skipped |
| kefu | 0 | 49 passed |
| exhibition | 0 | 381 passed（11 warnings） |
| knowledge-service | 0 | 416 passed / 7 skipped |
| nl2sql-service | 0 | 235 passed / 8 skipped |
| `tests/observability`（`--extra otel` 同集） | 0 | **18 passed，零 skip**（18.54s） |

合计 **3954 passed / 28 skipped / 29 deselected / 0 failed**，10/10 rc=0。
取数件：`.tmp-scratch/ap-visual/m13-sessions-652378a6.log`（前 9 格，13:06 那一轮）+
`m16-obs-652378a6.log`（第 10 格，本轮复跑），均不入库。第 10 格本轮**又跑了一次**且读数一致
（18 passed / 0 failed），本格引的是复跑那次 —— 因为它有对应的 SDK 在位性证据同批取。

**取数件自身的两个坑 —— 本轮已把件改掉**（第一版的描述保留在下面，因为它解释了加固后每条守卫为什么在那儿）：
① m13 那份日志的首行印 `trunk-candidate session rerun`，那是 runner
`m5-run-trunk-sessions.ps1` 里的**陈旧硬编码字样**，不代表当时真跑在 `trunk-candidate` 上；
② 该 runner 的默认 `-Wt` 曾指向上轮那个已删的 cand 载体（`Test-Path` 实取 = `False`），而它的
`$ErrorActionPreference` 是 `Continue` ⇒ `Push-Location` 失败只是**非终止错误**，实测
`cwd-after` 仍是调用方原目录，脚本会**继续在错误的树上跑 pytest 并打出正常格式的读数**。
那两轮是靠人工对账兜住的：`m14-probe.ps1` 打印的 `root=` 与 `misresolved=0`、
`m6-final-gates.ps1` 首行的 `HEAD=652378a6 tree=4de874a7…`。

加固后的件（**仍不入库**，只影响此后的本地复跑，**不改动本节任何读数的归属**）：`-Wt` 无默认值；
载体不是目录 / 解释器缺失 / `HEAD`-tree 现取失败 / 探针文件缺失 / 包解析不落在 `-Wt` ⇒ 一律**起跑前**退出；
log 首行由硬编码文案改为现取 `wt= head= tree= at=`；新增一条最硬的守卫 —— 起 pytest 前先用
`importlib` 查 8 个包的 `__file__` 前缀（**CWD 对不等于读的就是这棵树**：worktree 无 `.venv`，全靠
`PYTHONPATH` 那九条，拼错一个子目录就静默回落到主仓 editable 安装，正是 ② 那一型的续集）。

守卫自证 `m21-guard-teeth.ps1`（本轮实跑，脚本 rc=0，`fail-cases=0`；每条都要有能触发的 proof）：

| 用例 | 期望 rc | 实取 rc |
|---|---|---|
| 不传 `-Wt` | 2 | 2 |
| `-Wt` = 旧默认值那个已删载体 | 3 | 3 |
| `-Wt` 存在但不是 git 工作树 | 5 | 5 |
| `-Py` 指向不存在的解释器 | 4 | 4 |
| `-Probe` 指向不存在的探针（不许"没探针就当过了"） | 8 | 8 |
| `-Wt` = 一次性 mini repo（8 个包解析不落在它内） | 8 | 8 |

两条如实的边界：**exit 6/7 未被端到端触发** —— 构造不出"`Push-Location` 成功而当前目录不等于 `-Wt`"
（试过 `\.` 后缀形式，`Resolve-Path` 与 `Push-Location` 归一化一致），那条比对只按**表达式两向对照**
验过：同值 → `False`、仅尾分隔符不同 → `False`（`TrimEnd` 生效）、真差异 → `True`，即它既不恒真也
不恒假。另一条：自证件第一版把用例包进函数并 `return` 布尔，6 行 rc 全被管道吞掉却照样打出
`overall=OK` ⇒ 见 §5-19，本表的"实取 rc"列就是为这条而存在的。

happy-path 自检（证明守卫不误杀正常载体）：载体 = 新建 detached worktree `ap-m5selftest` @
`ff2ebaf5`（tree `be69661b`，与本轮 6 格首行那枚 tree 同一对象），加固后的 runner **显式传 `-Wt`**
跑前 9 格，**9/9 `rc=0`**，逐 session 三列与上表**逐条相等**（root `1564 passed / 10 skipped /
29 deselected` … nl2sql `235 passed / 8 skipped`），9 格合计 **3936 passed / 28 skipped /
29 deselected / 0 failed** = 上表十格减去第 10 格那 18 条。日志 `m22-selftest-9sessions.log`，不入库。
第 10 格不在本件射程（runner 只覆盖 Makefile `test` 的前 9 个 session），它仍是
`m16-obs-652378a6.log` 那一格。**上表的归属没有因此改变**：它绑 `652378a6`，这次自检绑 `ff2ebaf5`，
两棵 tree 的差别仍只在本文这一只 blob（`git diff --name-only 652378a6 ff2ebaf5` 只列一个路径）。

**与 §4 的交叉核对才是本格的意义**：合计四个数 **3954 / 28 / 29 / 0** 与 §4 绑 `d86ee4db`
的读数**逐项相等**，且逐 session 的 passed/skipped/deselected 三列**逐条相等**（10 行全对齐）。
⇒ `d86ee4db → 652378a6` 之间那 3 枚提交（含 §11.1 并入的 19 行台账）对可执行面零影响，
这条不再只是"`git diff --name-only` 只列文档"的推理，而是被 10 个 session 的直接读数证实。
反过来说：如果哪天逐条不相等，先查是不是哪枚提交动了代码，不要先怀疑 §4 的旧读数。

**第 10 格为什么不走 `uv run --extra otel`**：`--extra otel` 的动作是往 venv 里装 OTel SDK，
而 worktree 没有 venv ⇒ 装过去等于改主仓环境。改为**先现取 SDK 在位性再跑**：
`import opentelemetry.sdk.version` → `otel-sdk=1.45.1`（主 venv 内），同一解释器直接跑
`tests/observability`。本格**非空转证据 = skip 数为 0**：这不是"缺 OTel SDK 自动 skip"
那一型（conftest 守卫那一族见 AGENTS.md《验证策略》），18 条全是实跑。

**Makefile 里还有一条不算第 10 格**：`test` 目标另有
`VALKEY_URL=… CACHE_CONTRACT_REQUIRED=1 … test_cache_contract.py`，Makefile 自带注释声明它
不计入那 9 个 session，且需要活的 Valkey ⇒ 仍未跑，列在下面，不含糊进"10/10"。

**同一 sha 上的静态 6 格**（`m6-final-gates.ps1 -Wt …\ap-trunk-sessions -Rev 652378a6`，
取数件 `m16-gates-652378a6.log`）：G1 ruff `rc=0` / G2 doc_sync `rc=0`（0 警告）/
G3 arch `rc=0`（含 P14 语义缓存单轨）/ G4 registry `rc=0`（携带文件 0 / 命中 0 / 台账 1 /
违规 0 / 警告 1）/ **G5 publish `88515cab..652378a6` 新增命中 0 处 `rc=0`** /
G6 governance `521 passed, 1 skipped`。⇒ 本格与 §11.1 那 6 格同形，差别只在绑的 sha：
§11.1 绑 `7d9c7116`，本节绑 `652378a6`。G5 本格的有牙对照仍照 §8（同一 linter 对 `12f03c8f`
报 172 处 / rc=1），0 处不是因它根本不扫。

**仍未跑**（本格解除的只有"10 session 未整体重跑"这一条，别的一条都没解除）：

- `-m requires_pg` 的 29 条：需真 PG。
- Valkey 契约目标（上面那条）：需活 Valkey。
- E1 黄金集的 LLM 质量分（`--require-llm`）与 `eval/run_planner_eval.py` 双 Planner 基线：
  需模型配额，属发布决策；§9 的启发式 100% 不能替它发声。
- 变异两把 `make mutation-cache` / `make mutation`：未跑。
- 126 现网回读：本批纪律是不推任何远端、不上 126。

**本节的 tip 限定**（不因"多跑了一格"就免）：以上全部读数绑**固定 sha `652378a6`**，它是本取
证件所在提交的父提交。本取证件所在提交不在本节射程内，自证 =
`git diff --name-only 652378a6 main` 只列出本文这一个路径 ⇒ 可执行面零变更，本格读数可直引，
但引用"10/10 全绿"时**必须连带这句**一起引，不许简写成"终 tip 全绿"。

**"文档单提交"这个形状自己也过了一遍门禁**（`90d79e09` = 本段所在提交的父提交；
`m6-final-gates.ps1 -Wt …\ap-doc-wt -Rev 90d79e09`，取数件 `m17-gates-90d79e09.log`，
首行 `HEAD=90d79e09 tree=a21fa29c…`。它与 §12 那些读数所在的 `4de874a7` **不同 tree**，
差别仍只在本文这一只 blob：`git diff --name-only 652378a6 90d79e09` 只列出一个路径）：
G1 ruff / G2 doc_sync / G3 arch（含 P14）/ G4 registry 四格 `rc=0`，
**G5 publish `88515cab..90d79e09` 新增命中 0 处 `rc=0`**，G6 governance `521 passed / 1 skipped`。
⇒ §5-9 那条坑只能自己防：publish 门禁只在推镜像前跑、**不拦本地提交**，所以每往 `main` 写
一批文字就得自己跑一次，而不是等推镜像时被拦。本段新增的行写入前也就地扫过私有网段字面量
（`10.` / `172.` / `192.` 三段前缀，0 命中）。
**本段所在提交自身的 6 格不在本节射程内**（跑了也只能"绑当时 tip"，见 §8 末段那条规矩）；
需要时现取 `git log -1 --format=%H main` 再跑，别把上面的数当成它的数。

**本批最新一枚文档提交 `3cd8831e`（父提交 `ff2ebaf5`）的 6 格**：载体 = 仓外 worktree `ap-doc-wt`，
首行现取 `HEAD=3cd8831e tree=b41b14ac…`。G1 ruff / G2 doc_sync / G3 arch（含 L-4、P14）/
G4 mirror registry / G5 mirror publish `88515cab..3cd8831e` **新增命中 0 处** / G6 governance
`521 passed, 1 skipped`（71.04s），**六格全 `rc=0`**。这组数绑固定 sha `3cd8831e`，不是"当前 tip"
的数；`ff2ebaf5` 与 `3cd8831e` 不同 tree，差别仍只在本文这一只 blob（`git diff --name-only ff2ebaf5
3cd8831e` 写入前实取 = 1 个路径）。日志 `m24-gates-3cd8831e.log`，不入库。
上面那两段（加固后的取数件 + 本组 6 格）都不改本节主表的归属：主表仍绑 `652378a6`，取数件自检仍绑
`ff2ebaf5`。**本段所在提交自身的 6 格仍不在本节射程内**（同 §8 末段那条规矩）：本轮在它之后又动了本文，
所以要引"终 tip 门禁全绿"就必须在终 tip 上现取一次，不许复用上面任何一组数。
