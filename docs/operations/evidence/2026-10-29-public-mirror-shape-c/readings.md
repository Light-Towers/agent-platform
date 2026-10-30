# 形状 C 落盘与收尾读数：内网分支进入"全仓零基建真值"口径（2026-10-29）

**定位：** 证据记录（不是方案）。格式遵循 `docs/operations/evidence-format.md` §1 五字段 + §3 强度分档。
**对象：** 形状 C = 存量文档就地脱敏为占位符 + 真值住运维机本机 .intranet/keymap.json（不入库）+ 撤 `_REGISTRY` 台账项。
**读数绑定 rev：** `896f966e`（分支 `feat/nl2sql-ttl-and-006-slim`），**工作区含本批未提交改动** ⇒ 下述"仓内"读数都是
`HEAD + 未提交工作区` 这棵树，不是 rev 本身；两个口径在 §1 里分开写。
**关联方案：** `docs/plans/plan-public-mirror-gate-selfdisclosure-2026-10-29.md`（c10，本文 §4 复算它的实况读数）；
`docs/adr/0013-semantic-cache-single-track.md` 头部脱敏口径行；`docs/operations/env-126-inventory.md` 文首注记。

---

## 1. 落盘面（rev `896f966e`，本轮全部原样复跑）

| 命令 | 读数 | 判定 |
|---|---|---|
| `git rev-parse --short HEAD` / `git branch --show-current` | `896f966e` / `feat/nl2sql-ttl-and-006-slim` | 与上一轮同 rev ⇒ 本轮未产生提交 |
| `git status --short -uall` | 10 项 ` M` + 17 项 `??`（未跟踪文件数取 `git ls-files --others --exclude-standard` = 17） | 本批全部改动**未入库**，包括形状 C 的脱敏 |
| `git diff --cached --name-only` 计数 | **0** | 暂存面已清空（两项 staged 文档的处置见 §5） |
| `git ls-files` 计数 | **1309** | 比含 staged 时少 2 ⇒ 与上一行互为印证（那 2 件已离开 index） |
| `Test-Path .intranet/keymap.json` / `git check-ignore -v` | `True`；命中 `.gitignore:61:.*/` | 真值键表在本机存在且**不入库**，零新增仓级忽略规则 |
| 键表键数（`ConvertFrom-Json` 只取属性名，不打印值） | **8** | 8 条真值全部住在仓外 |
| `scripts/lint_public_mirror.py` L101–108 实读 | `_REGISTRY` 现 **1** 项（`docs/adr/0013-…md`），原 3 项中 2 项已随就地脱敏移除 | 台账收敛为"1 个文件携带一个非基建的合成示例" ⇒ 全仓零基建真值口径成立 |

## 2. 门禁面（同一棵树，四件各跑各的，rc 逐条取）

**① 文档同步**
命令：`uv run python scripts/check_doc_sync.py`
读数：`✅ 文档同步校验通过（0 警告）`，rc=**0**。
口径：该校验的作用域是 AGENTS.md/ARCHITECTURE.md/README.md 的引用路径 + Makefile session 数；本批新增的 `docs/` 文件不在其作用域内（⇒ 它绿不代表本批文档内部引用无悬空）。

**② lint**
命令：`uv run --with ruff ruff check .`
读数：`All checks passed!`，rc=**0**。

**③ 公开镜像门禁（registry 模式 @ HEAD，带 `--selftest`）**
命令：`uv run python scripts/lint_public_mirror.py --selftest`
读数：rc=**1**；`携带内网标识的仓内文件 3 个，命中行 30 处，登记台账 1 项；违规 2 项，警告 0 项`。
两条违规都是 `P-4`（`deploy/k8s/15-valkey.yaml`、`docs/operations/env-126-inventory.md`：携带标识但未登记）；
**输出里没有任何 `SELFTEST:` 前缀行** ⇒ `selftest()` 返回空 ⇒ 判据自身（正例被咬、豁免有边界、登记失效分流、mask-plan 换净）全部有牙。

**④ 工作区预检（模拟"提交之后"的 registry 口径）**
命令：`uv run python .tmp-scratch/c-mask/precheck.py`（判据 import 自门禁本体，不复制规则；该脚本不入库，换机器需自建）
读数：rc=**0**；`携带标识的文件 1 个，命中行 1 处，台账 1 项；未登记违规 0 项，幽灵登记 0 项，警告 0 项`；
形状豁免面 6 个文件共 17 处（5 个测试文件 + `uv.lock`），全部走形状豁免而非语义旁路。

### 机制性结论（本件要保留的那条，不许被"绿了"盖掉）

③ 与 ④ 的差值（**HEAD 树 3 文件/30 行** vs **工作区 1 文件/1 行**）就是混合态的直接证据：

> registry 模式的**命中行来自 `git grep … <ref>`（默认 HEAD，只扫已提交树）**，而 `_REGISTRY` 台账是
> 从磁盘 import 的**新表**。⇒ 只要"脱敏内容"与"台账编辑"不在同一次提交里，门禁**必然**报 P-4 红：
> 树里还有真值，台账里已经不再为它登记。
> **推论（写死在此，免得后人当成 bug 绕过）：形状 C 这类改动必须"内容脱敏 + 台账编辑"同批提交。**
> ③ 当前那条红是**预期的混合态**，不是判据失效；提交后它应当转为 ④ 的读数（0 违规）。

CI 侧的接线证据（**静态证据，非本轮实跑**）：`Makefile` 的 `lint:` 目标含该门禁，`.github/workflows/agent-platform-ci.yml` L82 `run: make ci`
⇒ 提交前若不闭合混合态，CI 会断在 `make lint`。本机无 `make`，**未实跑 `make ci`**。

## 3. 测试面（本批受影响 session）

**读数**（rev `896f966e` + 未提交工作区，`uv run pytest tests/governance packages/agent-core/tests/test_guardrails.py packages/agent-core/tests/test_guardrails_errors.py -q`）：
**509 passed / 1 skipped / 0 failed / 0 deselected**（rev `896f966e`），99.72s，rc=0。
**口径与分母**：三个目标分别 `--collect-only` 取数为 465（tests/governance）+ 27（test_guardrails.py）+ 18（test_guardrails_errors.py）= **510**，
与 509+1 精确相等 ⇒ 没有"少跑"的暗区。
**两轮同值**：第二轮加 `-rs` 复跑（rev 同上、命令同上）仍为 **509 passed / 1 skipped**（109.25s vs 99.72s ⇒ 耗时不作判据）。
**那 1 条 skip 的真实原因**（`-rs` 实取，不是推测）：`tests\governance\test_corpus_tenant_isolation.py:186`
⇒ `agent_server/sql 已退役（ADR-0011 §7）；等价判据在 nl2sql 侧`。它是**永久件退役 skip**，**不是**"缺环境自动跳过"——
本件初稿把这句写成了后者（未取 `-rs` 就归因），以上面这条实取为准。**订正登记**：skip 归因必须先 `-rs` 取 reason 原文，
"缺环境"与"模块已退役"是两种完全不同的处置（前者待环境、后者是账面已结）。
**与上一轮那条 491 的关系**：491+1 = 492 = 465 + 27 ⇒ 上一轮的选法**不含** `test_guardrails_errors.py`（18 条）。两个数都对，是口径差，不是回归。
**未覆盖**：其余 8 个 pytest session（agent-runtime / 联邦 / kefu / exhibition / knowledge-service / nl2sql-service / agent-server / observability 真 SDK）**本轮未跑**——本批只动文档与门禁脚本，未触产品代码；按 `AGENTS.md`《验证策略》取"改动范围分层"，声称可提交前才升 `make test` 等价全量。
**前置**：`uv sync --all-packages --extra dev` 已完成的本机 venv；无需网络、无需 PG/密钥。

## 4. c10 公开侧实况复算（不用本地旧快照）

命令（先证明本地读的就是实况）：

```
git ls-remote --heads github-legacy                     # rc=0，heads=8
main                          live 88515cab = local 88515cab  equal=True
mirror/nl2sql-ttl-and-006-slim live 2011fe6a = local 2011fe6a  equal=True
uv run python .tmp-scratch/c-mask/mirror_disclosure.py
```

> 代码块末行那个 `mirror_disclosure.py` **不入库**（`.tmp-scratch/` 在 `.gitignore` 内）⇒ 只作取证出处，不当可复跑命令；要在他机复现得按本节的输出形状自行重建探针。

读数（两个 ref 逐项相同）：
- **A) 形状盲区**：`192.168.<n>.$IP` 这类"网段前缀 + shell 变量"在公开侧 **1 处**（`docs/operations/env-126-inventory.md` L719），现行 P-1 四段正则匹不到。
- **B) 门禁自披露**：碎片行 **5 行**（L58/L59/L61/L62/L356），而对 `_asm(...)` **实际求值**得到常量 **5 个**（L58/L59/L60/L61/L62）。
  两个计数**集合不同**（L60 不在碎片行匹配里）⇒ 探针自身的碎片识别也有形状盲区，**下限应以常量数 5 为准**；本件如实登记该探针局限，不拿"5 行"当"只有 5 处"。
  求值出的真值只出现在命令 stdout，**不转录进本文件**（转录即在另一处复制本件投诉的形状）。
- **对照**：同一棵镜像树上 `lint_public_mirror.py --selftest` 零命中 rc=0（`_self_source_clean()` 用的就是 `_PATTERNS`，而 `_asm()` 拆串正是为了让它匹不到自己）
  ⇒ **"门禁零命中" ≠ "未泄漏"**（与 `AGENTS.md`《观测面硬规矩》#1「状态灯亮 ≠ 数据到」同族）。

**判定**：c10 在**现态**成立（不是历史快照），修法与代价见 `docs/plans/plan-public-mirror-gate-selfdisclosure-2026-10-29.md`；
该件仍是 **Proposal**，本轮**未动门禁一行代码**（改它属非 T0，先方案后代码；且已公开存量属公开侧历史改写 = D3，不在本批）。

## 5. 明确遗留两项的处置

**① 两项 staged（379 行）** ⇒ 本轮**执行了 `git restore --staged`**（只动 index，不动工作区），
现值复验：`git diff --cached --name-only` = 0 项、HEAD 仍 `896f966e`、两件在 `git status` 转为 `??`（内容仍在盘上）。
理由：这两件与本批脱敏无关（一份选型分析 + 一份历史取证读数），把它们混进提交会让"脱敏 + 台账同批"那条不变量难以逐行核对。
**本轮未复算的**：撤出前后的 blob 哈希对比（属上一段上下文的读数）⇒ 若要主张"零丢失"，需按 `git hash-object` vs `git rev-parse :path` 再取一次；当前只主张"两件仍在盘上、未进 index"。

**② `.evidence-out/` 那 5 张 PNG** ⇒ 判定**不删**。实取：

```
Get-ChildItem -Recurse -Filter console_step*.png -Force
  → .evidence-out\（5 张）+ .tmp-scratch\evidence-untracked\2026-10-29-roadmap-18-console\（5 张）
逐张 SHA256 对比 → 5/5 same=True
git check-ignore -v 两个路径 → 均命中 .gitignore:61:.*/
git ls-files 计数（两目录）→ 0
```

⇒ 事实是"**跨目录两份同内容副本**"（不是"5 张重复文件"），且**两份都不在版本控制里**：git 侧本就没有这项债。
不删的理由：截图不可再生（要重跑浏览器取证链路），且 `docs/operations/evidence/2026-10-29-roadmap-18-console/readings.md:124`
那条"磁盘上其实有两份同内容副本"的陈述依赖这两份存在才核得回来。删除属**不可逆 + 收益仅 679 KB**，不作自动执行项。

## 6. `evidence-format.md` §7 三条自查（扫本批新增行）

命令：`uv run python .tmp-scratch/c-mask/evselfcheck.py`（作用域 = `git diff -U0 -- '*.md'` 的 `+` 行 ∪ 未跟踪新 `.md` 全文；脚本不入库）
读数：**三跑**。① 本证据件未写时：受检 2621 行（未跟踪新 `.md` 11 个）/ A=1 / B=15（8 有界 + 7 候选）。② 写完本件后：2771 / A=3 / B=18。③ 按下面 A/B 行修正后：**2771 / A=1 / B=19（9 有界 + 10 候选）**。
**一个必须登记的口径发现**：B 类计数对"本件自身文面"**不是不动点**——写一行描述该检查的话，就多一行命中（③ 里本件占 3 行）。
⇒ 稳定口径 = **排除本证据件自身**，此时 B 回到与①逐项相同的 **15（8 + 7）**。本表以下采用该口径。

| 检查 | 命中 | 人判结果 |
|---|---|---|
| A) `N passed` 无 rev 上下文 | **1 行**（`2026-10-29-roadmap-18-console/readings.md:56`） | **非违规**：§7 那条 grep 是行级近似，同一文档 L24–26 有 `rev 896f966e` 绑定 + `git diff --stat` 排除污染的论证 ⇒ 该行继承文档级 rev。本件自已在②中因未写行内 rev 而**多算 2 行**命中 ⇒ 已补行内 rev（③ 回到 1，即**命中可修且修得动**，不是只能绕） |
| B) 空口径整体性名词（全仓/全部通过/都验证过） | **15 行** = 同行带命令/读数 **8** + 裸断言候选 **7** | v1 分类器报 **7** 行候选；v2 加了“邻域 ±3 行也算证据”一档后实为 **6** 行（差的 1 行是表格命令在邻行的那类），**六行已在 §8 逐条闭合**：2 条**不成立**已改写、4 条成立但作用域已钉住 ⇒ 复跑后 `全无证据` 档 = **0 行**（计数口径变了，不是同一批行的重新分类） |
| C)（本件加扫）现行门禁匹不到的新信息类 | 公司名 token **3 行/3 文件**、个人用户名 **1 行/1 文件**、本机绝对路径 **2 行/2 文件**；与现行 `_PATTERNS` **重叠命中 0 行** | 这是**词表缺口的量化读数**：这类内容形状上不含 IP/主机名后缀，P-1/P-2 结构性匹不到 ⇒ 推公开镜像时 publish 模式也不会拦。是否纳入词表属 D2 拍板项，本轮**只取数不改动** |
| D) 运维机主机名的**词根**（P-2 要求“词根 + 数字”，光秃词根匹不到；词根本身不在本行写出） | 首跑 **0 行**；本文初稿（那行里直接写了词根）再跑变 **1 行**——命中的正是本行自己的叙述；改成形状描述后③回到 **0 行**| **登记一个与 R-1 同族的悖论**：“描述该缺口”与“构成该缺口”在文档层是同一串字符 ⇒ 本文只能像现在这样**用形状描述代替字面词根**。副作用：任何拿“全仓扫零命中”当“文面干净”的做法，在这类词上不成立 |

## 7. 完成强度分档（按 §3 选档，不混用）

| 陈述 | 档位 |
|---|---|
| 形状 C 的仓内落盘（文档脱敏 + 台账撤项 + 真值出仓 + 门禁/测试/selftest 复跑） | **已验证**（rev `896f966e` + 未提交工作区，§1–§3 命令当场可复跑） |
| "提交后 CI 会绿" | **未验证**（本机无 `make`，未实跑 `make ci`；只有 `Makefile`/workflow 的静态接线证据 + ④ 的 worktree 口径预测） |
| c10 的修复 | **未做**（本批只出方案与实况读数；已公开存量属 D3） |
| 分支卫生月度体检 | **标准环境已验证**（远端 ls-remote 走网络已实取；`git fetch --prune` 与公开仓分支处置属待拍板/待授权） |

**未跑与待环境清单（本件不承诺日期）：** `make ci` / `make test` 等价全量 9 session + otel session；`publish` 模式实跑（需 `--base` 公开基线 sha 且要真推镜像才有意义）；plan-public-mirror §6 五行变异反证（要先改门禁才能跑）；126/241 现网读数。（§6-B 那六行候选已闭合，见 §8。）

## 8. §6-B 那六行"裸断言候选"的逐条闭合（rev `896f966e`，全部当场实取）

口径先说清：§6 表里的“候选 7 行”用的是 v1 分类器（只看同行）；v2 把“命令在±3 行邻域”归入可核对档后，候选降到 **6 行**（那 1 行差量属分类口径变更，不是新增取证）。本 §8 闭合的就是这 6 行，下表 5 个探针其中一行同时证两行文档（同一取证）。

工具：`.tmp-scratch/c-mask/evselfcheck2.py`（口径 = 排除本证据件自身；新增“邻域 ±3 行”与“`path:123` 指针也算证据”两条判据）
+ `.tmp-scratch/c-mask/vague_probe2.py`（每条断言一个**正例锚点** + 一个取数，锚点不中即探针失效）。两枚均不入库 ⇒ 本节留下的就是上面这两条判据本身，换机器照判据重建。

| 断言行 | 目标 | 命令 | 读数 | 结论 |
|---|---|---|---|---|
| `unconfirmed-items.md:57` ④ 与 `nl2sql-release:48` | “无密钥熵校验” | `git grep -l -F -e INTERNAL_HMAC_KEY` → 在该 20 文件内 `git grep -I -n -E -e "entropy\|熵\|min_length\|len\(key\|token_hex\|太短\|强度"` | 作用域 **20 文件**；校验类命中 **1 行**，且那一行就是本断言所在的文档行 | **成立**，但作用域是“读该键的 20 个文件”而非字面意义整仓；已把两处文面改为带作用域写法 + 指针 |
| `business-corpus:138` | “唯一在跑的调用点” | `git grep -I -n -F -e with_structured_output -- "*.py"` | **12 行 / 6 文件**（测试替身 5；产品 7 = `router.py:91` 调用 + `graph_compose.py:146/153/156` 未启用降级路 + `fallback.py:227/233` 转发器 + `protocols.py:21` 注释） | **成立但需限定**；另发现引用坐标错：原文 `:87` 现为注释块，调用在 **:91**（两者均已写入文档订正） |
| `nl2sql-release:19` | “HEAD 全仓零 `.prompt` 引用” | `git grep -I -n -F -e ".prompt"` 与 `git ls-files -- "*.prompt"` | **97 行 / 34 文件**；`.prompt` 文件 **9 个**（KS 6 + nl2sql 3），nl2sql-service 内 **20 处**含 3 个活跃 `load_prompt(...)` | **不成立**（过宽）⇒ 已改写为“旧线 5 个死 prompt 已删，由 `test_i0_cleanup.py` 的 `_DEAD_PROMPTS` L21-27 + `:33-34` 断言现存恰为三个钉住”。同行第 2 条依据也不实：`_prompt.py` 是加载器（`load_prompt` 在 :38），文件内 `.prompt` 命中 **0 行**，不存在“白名单” |
| `plan-revert-checkpoint-integrity:19` | “无任何接口可取 checkpoint id” | `git grep -I -n -F -e checkpoint_id -- applications/ packages/`；再逐条核引用坐标 | **77 行 / 10 文件**；作 HTTP 入/出字段的只有 `session_router.py` :78 与 :91（:91 回填的正是目标 id）；`recall_exact.py` 实路径 `applications/agent_server/memory/`，:70-75 与 :45 两处引用**均核中** | **成立**，把“全仓”改为“接口面”并附 77 行分母；引用坐标逐个核过（未只信文件名） |
| `plan-web-frontend-minimal-core:29` | “该句在全仓无来源标注” | `git grep -I -n -F --untracked -e "FastAPI+Vue3"` | **3 行 / 2 文件**：选型文档 L16/L27 + 本文 L29 自身（自指命中）；两处原句都无出处 | **成立**，但命令**必须带 `--untracked`**（见下面的探针缺陷 ②） |

### 8.1 本轮回填的两条探针缺陷（不修就会把“没扫”读成“没有”）

① **正则的 `.` 当字面量用**：首版取数用 `-e .prompt`（未加 `-F`），`.` 匹任意字符 ⇒ 得到 **803 行/190 文件**的噪声读数；那条“零命中”断言完全是在噪声上判的。⇒ 含元字符的字面量一律 `-F`。
② **`git grep` 默认只扫已跟踪文件**：`git grep -I -n -F -e "FastAPI+Vue3"`（不带 `--untracked`）实取 **rc=1 / 0 命中**，而同一命令带 `--untracked` 得 **3 行**；根因是被引文档 `docs/plans/plan-frontend-stack-selection-2026-10-27.md` 本身尚未入库（`git ls-files` 对该路径 = 0 行）。
⇒ **一切实证“零 X”类断言必须声明跟踪口径**，否则“全仓零命中”只证“已提交树里零命中”。这与《文档防漂移》那条“存在性判定基准 = 版本控制清单”不矛盾——**那条管引用，本条管取证**，两者口径刚好相反。

### 8.2 闭合后的复跑读数

命令：`uv run python .tmp-scratch/c-mask/evselfcheck2.py`（rev `896f966e`，口径 = 排除本证据件自身；脚本不入库）
读数：受检 **2639 行**（全量 2779）/ A = **0 行** / B = **12 行**（同行有证据 **9** + 邻域 **3** + 全无 **0**）；不动点对照：那一次 B 含自身 **16**、本件贡献 **4**。
⇒ §6 遗留的 A=1 也已闭合（那一行补了行内 rev 指向同文档 §1 字段 ①）。B 从 15 降到 **12** 不是“扫得松了”，而是三条改写把“全仓”换成了真实作用域（去词而不是加词）。
**写完本节后的再跑（同一命令，rev `896f966e`）**：受检 **2663 行**（全量 2831）/ A 仍 **0** / B 仍 **12**（9 + 3 + 0 不变），但**本件贡献从 4 涨到 9**（含自身口径 16 → 21）——§8 写了九行描述这些检查的话，自身就多九行命中。
⇒ 上一段那个“4”是本节未写入时的读数，**不得当现值引用**；不动点只能定在“排除本件”这一口径上（=12），含自身口径随写作单调增长。这是 §6 那条“非不动点”发现的**第二次实测印证**，不是新现象。
**未闭合项（诚实保留）**：~~邻域档那 3 行未逐条人工定性~~（**已闭合，见 §8.3**）；本件自身那 **9** 行命中未逐条看（按上面口径，它们全在“描述检查自身”的句子里）。

### 8.3 邻域档那 3 行的逐条闭合（rev `896f966e`，本轮实取）

取数件：`.tmp-scratch/c-mask/nb3_close.py`（两口径对照）+ `.tmp-scratch/c-mask/nb307_recount.py`（按清单真实目标重取）；两枚均不入库，可复跑的是下面表里逐行写出的 `git grep` 那类命令。**三行全部判完，但结论方向不同：两个“成立但只在一个口径下成立”，一个直接反噬到我自己写的更正文面。**

| 行 | 原断言 | 实取（命令 → 读数） | 判定 |
|---|---|---|---|
| `2026-10-28-nl2sql-release/readings.md:220` | 邻域 L218 有命令+读数 ⇒ 算证据 | `git grep -n -F --untracked -e '^[A-Z0-9_]+:'` → **2 行/2 文件**；不带 `--untracked` → **1 行/1 文件**（= `checklist.md:49`）；`… HEAD -- …checklist.md` → **rc=1** | 邻域证据**当时成立、现在过期**：L218 写的“只存在于本文档（命中 1 处 = 本文件本行）”已被同批次我自己加的 `checklist.md:49` 推翻 ⇒ 已改写为带两口径读数的快照句 |
| `plan-web-frontend:307` | “同批必 add 清单（终态）…已逐条全仓 `*.md` 实取” | 目标选错首轮：探针里填的是**另外三份文档**（不是表内 5 项）⇒ 作废重取。按真目标：默认口径下 **#4a/#4b/#4c/#5 全为 0 行**，`--untracked` 下 #2 = **9 行/4 文件**、#3 = **6 行/5 文件**、#5 = **3 行/2 文件** | **实质成立、口径与措词两处要改**：“终态”撑不住（引用边只会随后续轮次增加，现 #2 已 4 文件而表内记 2 个引用者）；而默认口径会把“必须同批入库”的判据读成“零引用可不入库”⇒ 已改写为取数口径 + 复跑注 |
| `plan-web-frontend:348` | “移动前已验：无任何文档按旧路径引用（全仓检索只命中它自身）” | `git grep -n -F --untracked -e "DEEP_RESEARCH_React_NextJS_SSR_SEO.md" -- "*.md"` → **1 行/1 文件**；默认口径 → **0 行**；新路径 → **3 行/2 文件** | 结论成立，但**归因写错了**：唯一命中不是“它自身文件”（被移动文件的正文不含自己路径），而是**断言自身所在的这句**；默认口径下本来连这句都扫不到 ⇒ 已改写为自指型描述 + 两口径读数 |

本轮新增两条取证纪律（已写入 `docs/plans/plan-public-mirror-gate-selfdisclosure-2026-10-29.md` §10 条 3/4，不新增门禁）：

③ **写“仓库里只有 N 处 / 本批终态”的句子自带过期时间，终点是自己的下一次编辑**——上表前两行都是这一型，而且推翻者都是我自己本批的编辑（不是别人）。
⇒ 这类断言只能写成“截至 rev X + 取数时刻”的快照；写“终态”就是在给未来的自己埋一条错事实。
④ **grep 命令字符串只能答“它出现在哪里”，不能答“它对不对”**。L218 那句更正文面里顺手写的“那条命令本身没毛病”就是被这个混淆放过的：
实跑 `Select-String -Path deploy/k8s/00-config.yaml -Pattern '^[A-Z0-9_]+:'` → **0 命中**（同文件缩进口径 `^  [A-Z][A-Z0-9_]+:` → **21 命中**）
⇒ 命令确实错，**而我那条“更正”把一个只对一半的指控改成了全错**（上一轮的错是误归因，这一轮的错是矫枉过正，两个都是错）。

顺带一个工具自检：`nb3_close.py` 首版的 `mask()` 我写成了空循环（假遮蔽），当场删掉——本探针只用 `-c`，输出是 `文件:计数` 不含内容，无需遮蔽。

**收尾最后一次复跑（本批文档全部改完之后，rev `896f966e`）**：受检 **2672 行**（全量 2854）/ A = **0** / B = **13 行**（同行 **10** + 邻域 **3** + 全无 **0**）；含自身口径 **22**。
⇒ “排除自身 = 12”也不是终值：上一段之后我又在本批**另一件**文档（plan-public-mirror §10）里新写了带“全仓”的行，于是 12 → **13**（多的那一行同行带命令，已归入可核对档）。
⇒ 正确的不变量不是某个总数，而是 **“全无证据档 = 0” 保持为 0**；总数随任何一件本批文档的编辑可变。本节不拿“12”当现值引用。

**三行闭合后再跑（同一命令，rev `896f966e`）**：受检 **2680 行**（全量 2886）/ A **0** / B = **9 行**（同行 **9** + 邻域 **0** + 全无 **0**）；含自身口径 **21**、本件贡献 **12**。
⇒ 13 → 9 这 4 行的去向要分开报，**不能读成“文面变干净了 4 处”**：四处（L218、L220、L307、L348）确实都是把“全仓”换成了具体作用域 + 同行命令/读数；但**含自身口径只从 22 降到 21**，因为我在本件 §8.3 的表格里以“原断言”名义**引用**了那些被删掉的措辞——它们落进了“排除本件”这个稳定口径的盲区里。
⇒ 这是 §6 那条悖论的**第三种形态**：不仅“描述检查的那行会构成命中”、“引用被订正掉的错措辞”也会把命中搬进排除区。**口径本身能被写作方式绕过** ⇒ 报 B 数必须同时报含自身数（本次 9 vs 21，差的 12 行全在本件内），否则“降到 9”就是一句可以被质疑的话。

## 9. 本批收尾复跑（五项门禁，全部当场实取，rev `896f966e`）

| 门禁 | 命令 | 读数 | 判定 |
|---|---|---|---|
| 文档防漂移 | `uv run python scripts/check_doc_sync.py` | rc=**0**，“校验通过（0 警告）” | 新增的 `applications/agent_server/memory/recall_exact.py`、`.tmp-scratch/...` 等引用未打破存在性校验 |
| Lint | `uv run --with ruff ruff check .` | rc=**0**，“All checks passed!” | 入库代码未被本批文档改动打破（scratch 件在 gitignored 目，不入 ruff 面） |
| 脱敏预检 | `uv run python .tmp-scratch/c-mask/precheck.py` | rc=**0**；未登记违规 **0** / 幽灵登记 **0** / 豁免 **6 文件 17 处** | 本轮文档改写**没引入新的内网字面量** |
| 门禁自检 | `uv run python scripts/lint_public_mirror.py --selftest` | rc=**1**；SELFTEST 失败 **0** 条；`registry 模式 @ HEAD：3 个文件 / 30 行 / 台账 1 / 违规 2 / 警告 0` | 与上一批逐项同值的那条**预期混合态红**（§2 机制性结论）；提交后应转 0 违规 |
| 文档治理用例 | `uv run pytest tests/governance/test_doc_sync_file_refs.py -q` | rc=**0**，**44 passed in 3.55s**（rev `896f966e` + 未提交工作区，与本文所有读数同树） | 未因本批改写而破 |

**§8.3 闭合后的五项复跑（本轮，同一棵工作区树）**：`doc_sync` rc=**0**（“校验通过（0 警告）”，读数与上表同值）、`ruff check .` rc=**0**、`.tmp-scratch/c-mask/precheck.py` rc=**0**（豁免清单尾部逐项同值）、`--selftest` rc=**1** 且仍为 `3 文件 / 30 行 / 台账 1 / 违规 2 / 警告 0`（上表逐项同值 ⇒ 预期混合态红未变形状）、治理用例 **44 passed in 1.17s**。
⇒ 上表的 `44 passed in 3.55s` 与本轮 `1.17s` 是**同一条命令的两次独立实跑**（耗时随机器负载变，不是两个结论）；两者都与本文读数同树。

**本批未跑（不得读成已验）**：`make ci` 全链（本机无 make）、其余 8 个 pytest session、`publish` 模式、`git fetch --prune` 与公开仓分支处置（均属待拍板/待授权）。

## 10. 落地后复跑（2026-10-30，rev `cfc7bf19` = 形状 C 相关的六批落库之后）

> 本节是**追加**，§9 那张表保持原样——它是 `896f966e` + 未提交工作区那棵树的历史快照（历史正文不改写，订正只加注）。

- §9 门禁自检行末尾那句“**提交后应转 0 违规**”是当时下的**预测**，本轮已把它跑成读数：
  `uv run python scripts/lint_public_mirror.py --selftest` → `registry 模式 @ HEAD：携带内网标识的仓内文件 1 个，命中行 1 处，登记台账 1 项；违规 0 项，警告 0 项`，**rc=0**
  （§9 当时：rc=**1** / 3 个文件 / 30 行 / 台账 1 / 违规 **2**）。⇒ 混合态红不是规则失效，而是“台账按磁盘 import / 命中行按 HEAD 取”这个提交切面的必然产物；
  **rc 1→0 由提交动作自己触发**，所以它同时是形状 C 门禁的非空转反证（落库批 = `efe938c1`，它的 message 里逐字记了这两个 rc）。
- 同树复跑其余四项（均 rev `cfc7bf19`）：`uv run python scripts/check_doc_sync.py` rc=**0**（“校验通过（0 警告）”）、`uv run --with ruff ruff check .` rc=**0**、
  `uv run python .tmp-scratch/c-mask/precheck.py`（不入库）rc=**0** 且未登记违规 **0** / 幽灵登记 **0** / 形状豁免 **6 文件 17 处**（与 §9 逐项同值）、
  `uv run pytest tests/governance/test_doc_sync_file_refs.py -q` **44 passed in 1.17s**。
- 本批新覆盖（§9 当时没跑）：根 session `uv run pytest -q` = **1487 passed / 38 skipped in 170.64s**（rev `cfc7bf19`）；
  `uv run pytest tests/governance -q` = **464 passed / 1 skipped in 102.86s**（同一棵）。skip 项本轮**没逐项复算归属**（按《conftest 守卫识别》口径它们多半是缺外部依赖的自动跳过，
  但那是待核对项，不拿它当本轮读数的一部分）。
- 仍未跑（不得读成已验）：`make ci` 全链、其余 8 个 pytest session（联邦 / kefu / exhibition / knowledge-service / nl2sql-service / shared-schemas / agent-runtime / agent-server）、
  `publish` 模式、以及 126/241 现网侧命令（六批零产品代码，但零代码不等于零验证——只是说明剩下的缺口不在代码侧）。
- ⚠ **可核对性的一个口子（顺手把 §9 也管上）**：上面两条里的 `precheck.py` 路径住在 `.tmp-scratch/`，
  `git check-ignore -v` 实取命中的是 `.gitignore:61:.*/`，且 `git ls-files -- .tmp-scratch` = **0 行**
  ⇒ 那两条命令**只在本机可复跑**，不是外人能重放的核对路径（§9 表格的“脱敏预检”行早就如此，本批只是把它说出来）。
  真正入库可重放的只有前三条：`check_doc_sync.py`、`lint_public_mirror.py`（含 `--selftest`）、`ruff check .`，
  以及两个 pytest 调用。要把它固化成可重放，得把 `precheck.py` 的等价能力收进 `scripts/`——那是 D2（待拍板），不属本批。

## 11. 把“同批”从一句话跑成 2×2（2026-10-30，rev `6e33c744` 实取）

> 触发点不是新需求，是收尾自查：我在 HEAD 上**不经门禁**独立 `git grep` 基建真值，捞到一处门禁没报的地址，
> 顺着查它为什么不被拦 ⇒ 读到一句我自己写在门禁注释里的**错陈述**（批 `6e33c744` 已订正：它把 README 也列为
> pod CIDR 的公开来源，实测 `git log -S "10.244" -- README.md` 与 `git grep HEAD -- README.md` 对 10.244 均 **0 命中**，
> 而 `-- deploy/k8s/VERIFICATION.md` = **5**）。订正只动注释，`git diff` 里 `re.compile` 行的增减 = **0**。

- **被这条查出来的事实**：`docs/operations/evidence/2026-10-14-morning-state/readings.md:35` 有一条 Pod IP `10.244.2.15`。
  它不被拦不是漏检：`_PATTERNS` 的 `10/8` 条带 `(?!244\.)` 负向前瞻，且 `--selftest` 里有一条**负控**断言它必须不命中。
  即“设计意图的豁免”，只是豁免理由的旧文面写胖了一半。
- **不变量实测（四格全取，不是推的）**。台账取磁盘版本、命中行取 `--ref` 那棵树，所以两轴能各自独立摆：

  | 树 ╲ 台账 | 旧台账 3 项 | 新台账 1 项 |
  |---|---|---|
  | 旧树 `db4fea6c`（未遮） | **rc=0** / 3 文件 30 行 / 违规 0 / 警告 0 | **rc=1** / 30 行 / 违规 **2** |
  | 新树 `efe938c1`（已遮） | **rc=0** / 1 文件 1 行 / 违规 0 / 警告 **2** | **rc=0** / 1 行 / 违规 0 / 警告 0 |

  ⇒ **§2 末尾那两句（「形状 C 这类改动必须"内容脱敏 + 台账编辑"同批提交」，以及它上面那句“不在同一次提交里，门禁**必然**报 P-4 红”；
  `efe938c1` 的提交标题也用了同一个说法）只对了一个方向**：先收台账而不遮内容 ⇒ 硬失败（右上格）；
  先遮内容而不收台账 ⇒ 仍是 rc=0，只留 2 条 WARN（“登记项现零命中＝已被脱敏”，故意不删行）。
  所以准确的不变量是**单向**的：允许台账宽于内容，不允许台账窄于内容。左上格（旧树+旧台账 rc=0）是必要对照，
  没有它，右上格那个红什么也证明不了。
- **可重放命令**（两条都只调用入库脚本，不在 D26 那张网里）：
  `uv run python scripts/lint_public_mirror.py --ref db4fea6c` → 右上格 rc=1（这也是 §9/§10 记的“混合态红”现在**随时可重跑**，不再是一句转述）；
  旧台账那两格需先物化旧版脚本：`git show db4fea6c:scripts/lint_public_mirror.py > <仓库根下一级>/lpm-old.py` 再 `--ref`。
  ⚠ 它算仓库根用的是 `Path(__file__).resolve().parent.parent` ⇒ 放在 `.tmp-scratch/c-mask/` 下会把根算成 `.tmp-scratch`，
  得到 `[FAIL] 枚举/取数失效 … 文件清单为空` / rc=**2**（我第一次就踩在这上面）。那是 fail-closed **正常工作**，不是脚本坏。
- **顺手把“门禁到底有没有人跑”钉住**（之前只说过“进 `make lint`”，没追到 CI）：`Makefile:13` 在 `lint:` 目标内，`Makefile:158` 行的正文就一句 `ci: lint test eval`，
  而 `.github/workflows/agent-platform-ci.yml:82` 是 `run: make ci` ⇒ 链条完整（CI → ci → lint → 本门禁）。
  反面一项：`git grep -l lint_public_mirror HEAD -- tests applications packages` = **0 个文件**，即没有任何 pytest 用例断言它的行为，
  它自身的正确性**只靠 `--selftest`**（本轮 rc=0）。
- 本批零产品代码；仍未跑的项目同 §10 末条（`make ci` 全链、其余 8 个 session、`publish` 模式、现网侧）。
  根 session 在 `cfc7bf19` 跑过（1487/38 skipped），`6e33c744` 之后的两批只动注释与台账口径，且已证**没有任何测试引用该脚本**，
  所以没重跑全量——这一条是“按分层验证策略选择没跑”，不是“跑了且是绿的”。
