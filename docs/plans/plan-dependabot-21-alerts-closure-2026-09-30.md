# Dependabot 21 项告警收口方案（2026-09-30）

> 触发：门面退役推送后 GitHub 在 push 输出提示「21 vulnerabilities on default branch（4 critical / 11 high / 6 moderate）」。用户要求「将这 21 个漏洞修复掉」。
> 本文是**方案 + 实施记录**（AGENTS.md 红线：改动前先出方案）。§0-§7 为取证与方案，§8-§10 为实施与验证结果（分支 `fix/dependabot-eval-transitive`，PR #24），**§11 为 PR #24 合并后 Dependabot 重扫的二轮回报与后续维护（分支 `fix/dependabot-pyjwt`）**。

## 0. 一页结论

21 项**不是 21 个可升级的漏洞**，取证后分为两类，且两类都无法靠「升版」解决：

| 类别 | 项数 | 事实 | 可执行的收口手段 |
|---|---|---|---|
| **甲：孤儿告警（manifest 已从 main 删除）** | **14** | 告警的 `manifest_path` 是 `courses/zhanggui-wenda/data-agent/uv.lock`、`zhanggui-zhiku/uv.lock`（含/不含 `courses/` 前缀两种写法各一份）。这些文件在 main 的 git tree 里**不存在**（tree API `truncated=false`，`contents/…` 返回 HTTP 404），只存在于历史 commit（`981adbb` 初始化、`b546aa5`、`e54aa62`）。仓库当前**所有分支**都只有根 `uv.lock` 一个锁文件 | **无可改代码**。只能 dismiss（理由 `not_used`，注释附本方案 git 证据），或等 Dependabot 重扫——但 `.github/dependabot.yml` 只配 `directory: "/"`，那些已删除目录不会再被扫描，**自动关闭的假设已被 9-25→9-30 五天未关闭的事实证伪** |
| **乙：根 lock 真实命中，上游无补丁** | **7** | `fschat 0.2.36`（6 项：3 high SSRF/资源耗尽 + 2 medium 开放重定向/审核绕过 + 1 high）与 `nltk 3.10.3`（1 high 模型工件路径穿越），`first_patched_version = null`（NLTK advisory 原文「Patched versions: Not yet patched」）。两者唯一父节点均为 `flashrag-dev`，仅挂在根包 `eval` extra | **从 lock 真剔除**：`[tool.uv] override-dependencies` 摘掉 fschat/nltk 两条边（已静态证明 eval 代码路径不 import 它们）；或沿用 9-25 的「风险接受」登记并 dismiss |

**关键判定依据（非推测，均可复核）**：
1. `flashrag-dev`（git 依赖 `RUC-NLPIR/FlashRAG@d3feb72`）的 `requirements.txt` 里列出 `fschat` 与 `nltk`，但 `install_requires=extras_require['core']=requirements.txt` 全量带入 → 这是它们进入根 lock 的唯一通道。
2. FlashRAG 源码中 fschat 的真实 import 只在 `webui/`（streamlit 界面）；nltk 的真实 import 只在 `flashrag/refiner/llmlingua_compressor.py` 与 `selective_context_compressor.py`。`flashrag/utils/utils.py` 里的 `"fschat"` 只是 `config["framework"] == "fschat"` 字符串。
3. `scripts/flashrag_eval/run_eval.py` 只 import `flashrag.config.Config` / `flashrag.dataset.Dataset` / `flashrag.evaluator.Evaluator`；这三个包的 import 闭包（`config.py`→yaml/torch、`dataset.py`→datasets/numpy、`evaluator/metrics.py`→**rouge / rouge_chinese / jieba / transformers / tiktoken**）**均不含 fschat、nltk**；且 `flashrag/__init__.py` 大小为 0 字节（不自动拉起子模块）。
4. lock 反向边：`rouge`/`rouge-chinese` 只依赖 `six`，`spacy`/`bm25s`/`chonkie` 均不依赖 nltk → 摘掉 nltk 不会连带破坏其它已锁包。
5. 甲类 14 项里 `anyio 4.14.2`、`mcp 2.0.0`、`transformers 5.15.0`、`accelerate 1.15.0` 在 main 根 lock 均已 ≥ first_patched（`uv.lock` 直接可查），根项目侧本无缺口——与 9-25 登记一致。

## 1. 明细表（21 项逐条）

| alert# | 严重度 | 包 | 漏洞区间 | first_patched | manifest_path | relationship | 分类 | 锁定版本判定 |
|---|---|---|---|---|---|---|---|---|
| 24 | high | fschat | ≤0.2.36 | — | `uv.lock` | transitive | 乙 | HIT（0.2.36） |
| 23 | high | fschat | ≤0.2.36 | — | `uv.lock` | transitive | 乙 | HIT |
| 22 | high | fschat | ≤0.2.36 | — | `uv.lock` | transitive | 乙 | HIT |
| 20 | high | fschat | ≤0.2.36 | — | `uv.lock` | transitive | 乙 | HIT |
| 25 | medium | fschat | ≤0.2.36 | — | `uv.lock` | transitive | 乙 | HIT |
| 21 | medium | fschat | ≤0.2.36 | — | `uv.lock` | transitive | 乙 | HIT |
| 26 | high | nltk | ≤3.10.3 | — | `uv.lock` | transitive | 乙 | HIT（3.10.3） |
| 11 / 3 | critical | anyio | <4.14.2 | 4.14.2 | `…/data-agent/uv.lock`（×2 写法） | transitive | 甲 | manifest 不存在 |
| 10 / 2 | medium | anyio | <4.14.2 | 4.14.2 | 同上 | transitive | 甲 | manifest 不存在 |
| 9 / 1 | critical | asyncmy | ≤0.2.11 | — | 同上 | direct | 甲 | manifest 不存在 |
| 17 / 16 / 12 | high | mcp | <1.28.1 / ≤1.27.1 / <1.23.0 | 1.28.1/1.27.2/1.23.0 | `zhanggui-zhiku/uv.lock` | transitive | 甲 | manifest 不存在 |
| 18 / 15 / 14 / 13 | high×3+medium | transformers | <5.10.0 / <5.5.0 / <5.3.0 / <5.0.0rc3 | 各自有 | `zhanggui-zhiku/uv.lock` | direct | 甲 | manifest 不存在 |
| 19 | medium | accelerate | ≤1.14.0 | — | `zhanggui-zhiku/uv.lock` | transitive | 甲 | manifest 不存在 |

（合计 7 + 14 = 21 ✓；严重度分布 4 critical / 11 high / 6 moderate 与 push 提示一致 ✓）

## 2. 候选处置

### 方案 1（建议）：乙类真剔除 + 甲类 dismiss
- **乙（7 项）**：根 `pyproject.toml` 增 `[tool.uv] override-dependencies = ["fschat ; python_version < '3.9'", "nltk ; python_version < '3.9'"]`（uv 官方「移除传递依赖」写法：给出永假 marker，解析器直接丢弃该边；本仓 `requires-python >= 3.11`，该 marker 恒假）。随后 `uv lock` → 根 `uv.lock` 不再含 fschat/nltk 两个 `[[package]]` 块。Dependabot 下次扫描（weekly，目录 `/` 已覆盖）即把这 7 项置为 fixed，**无需 dismiss**。
- **甲（14 项）**：`POST /repos/{o}/{r}/dependabot/alerts/{n}` 逐条 dismiss，`state=dismissed` + `dismissal_reason=not_used` + 注释指向本方案（说明 manifest 已不在 main，附 tree 404 证据）。不改任何仓库文件。
- 影响面：仅 `eval` extra（`make eval-rag` / `scripts/flashrag_eval`）；生产运行时与 6 个 application 不受影响（fschat/nltk 从未进入 prod 依赖闭包）。

### 方案 2：乙类也走 dismiss（风险接受延续）
沿用 `docs/plans/dep-security-accepted-risks-2026-09-25.md` 的判断，21 项全部 dismiss，零代码改动。代价：`fschat`/`nltk` 仍留在 lock，任何 `--extra eval` 环境仍会装上这两个含漏洞包；把「告警消失」当成「问题解决」，与本仓「结论须基于实跑证据」的纪律相悖。**不推荐**，除非 override 验证失败。

### 方案 3：从 eval extra 摘掉 `flashrag-dev`
彻底删除 FlashRAG 边 → fschat/nltk 连同 torch/gradio/streamlit 一起消失，lock 大幅瘦身。代价：`make eval-rag`（检索回归基线，`docs/operations/opencode-llm-setup.md` §8 的 rerank 增益对照）直接失能。**除非愿意放弃该评测能力，否则不选。**

## 3. 验证策略（含明确边界）

| 层 | 手段 | 能证明什么 | 局限（须如实声明） |
|---|---|---|---|
| L1 解析层 | `uv lock` 后 `Select-String 'name = "(fschat|nltk)"' uv.lock` 计数 0 + `uv lock --check` | 两条边确实从锁文件消失、workspace 其余解析不漂移（对比 lock diff 只减不增） | 不证明运行时 import 成功 |
| L2 冒烟 | `uv sync --extra eval` 后 `uv run --extra eval python -c "from flashrag.config import Config; from flashrag.dataset import Dataset; from flashrag.evaluator import Evaluator"` | run_eval.py 的 import 面在缺 fschat/nltk 时仍可用 | **需下载 torch/transformers/spacy 等数 GB wheel**（testing-playbook 已警告 eval extra 是最大耗时陷阱）；本机 Windows 若装不上，则此项验证只能在 126 容器补跑，不得凭 L1 声称「已验证」 |
| L3 端到端 | `make eval-rag`（需 pgvector 容器 + 真实 embedding/rerank 可达） | 检索回归基线仍能出数 | 本机大概率缺外部条件（`.env` LLM key / rerank 服务）；缺条件即如实记「未验证」，不写「通过」 |
| L4 告警侧 | 实施后复拉 `gh api dependabot/alerts?state=open&ref=refs/heads/main` 计数 | 唯一权威收口判据（目标 0） | 乙类关闭依赖 Dependabot 重扫节奏（weekly），提交后可能仍显示 open → 需说明等待窗口，不能伪报清零 |

**门禁**：改动只涉 `pyproject.toml` + `uv.lock`，仍跑 `make lint` 等价命令 + 根 pytest session（`uv run pytest -q`）确认无解析回归。

## 4. 回退策略

- override 是一行声明 + 锁文件变化，回退 = 删除 `override-dependencies` 两行 + `uv lock` 复原（`git checkout pyproject.toml uv.lock`）。
- 若 L2 冒烟出现 `ModuleNotFoundError: fschat/nltk`（说明存在我未覆盖到的 import 路径）→ 回退 override，转方案 2（dismiss + 更新 9-25 接受登记的复核触发条件），并在本文记录失败证据。
- 甲类 dismiss 可逆：`PATCH`/重新打开或由下次扫描重报，不产生代码影响。

## 5. 明确不做

1. **不重建 `courses/**/uv.lock`**（那些锁文件是课程脚手架产物，已被有意移出仓库；为消告警而把它们加回来是反向操作）。
2. 不动生产依赖版本（anyio/mcp/transformers/accelerate 在根 lock 已达标，无缺口可修）。
3. 不为通过告警计数而放宽任何测试或门禁。
4. 不合并/改动 `main` 上的其它在途内容；本次改动独立成 PR。

## 6. 落点与流程（待确认）

告警归属 **main**（`ref=refs/heads/main`），而当前工作分支是 `test/rag-route-ablation-eval`。要让 7 项真关闭，改动必须进 main：
`git checkout -b fix/dependabot-eval-transitive origin/main` → 改 pyproject + `uv lock` → 验证 → push → `gh pr create --base main` → 合并后 Dependabot 重扫。
（与既有 `fix/main-dep-security-floors` → PR #17 → main 的同款路径一致。）

## 7. 决策点（需用户拍板后我才动手）

- D1：乙类走 **方案 1（override 真剔除）** 还是 **方案 2（dismiss 接受）**？
- D2：是否授权对甲类 14 项执行 **dismiss**（`not_used`，GitHub 上会留下人工判定记录，公开仓库可见）？
- D3：是否授权 L2 实装验证的时间/磁盘成本（数 GB wheel），还是仅做 L1 + 在 126 容器补跑 L2？
- D4：落点确认——从 main 切分支并开 PR 合入 main（D4 否 → 只能留在特性分支，告警不会关闭）。

> **用户拍板（2026-09-30）**：D1=方案 1（override 真剔除）· D2=授权 dismiss 甲类 14 项 · D3=L1 + 实装冒烟 · D4=从 main 切分支 + PR 合 main。以下 §8 为该决定的实施与验证记录。

## 8. 实施与验证记录（2026-09-30）

分支 `fix/dependabot-eval-transitive`（基底 `origin/main` = `e5904c8`）。

### 8.1 追加静态证据（比 §0 依据 2/3 更硬）

在**锁定的同一 commit**（`d3feb72`，取本机 uv git 缓存的 checkout）上直接验证：

1. 全包扫描 `flashrag/**/*.py` 中 `^\\s*(import|from)\\s+(nltk|fschat)` → **仅 2 处命中**，均在 `flashrag/refiner/`（`llmlingua_compressor.py:13`、`selective_context_compressor.py:14`）；**fschat 命中 0 处**（原 §0 依据 2 说的是 webui，本次扫描范围是整个 `flashrag/` 包，webui 不在包内，故 fschat 在包内彻底无引用）。
2. AST import 闭包 BFS（临时脚本，不入库：从入口模块起 `ast.walk` 取 `Import`/`ImportFrom`（含相对 import 还原）后按 `flashrag.*` 递归去重）；入口取 `scripts/flashrag_eval/run_eval.py` + `agent_retriever.py` 的**全部** flashrag 入口：`config` / `dataset` / `evaluator` / `retriever.retriever` → 访问 **46** 个模块，`NLTK_REACH=0`、`FSCHAT_REACH=0`、`refiner_in_closure=False`。入口面比 §0 依据 3 原先只列的 3 个模块多一个 `retriever.retriever`，结论不变。
3. 仓内自有代码 grep `^\\s*(import|from)\\s+(nltk|fschat)` → **0 命中**。

### 8.2 L1 解析层（本机 Windows，**通过**）

```
uv lock            → Resolved 300 packages；Removed fschat v0.2.36 / nltk v3.10.3 等 11 项
uv lock --check    → exit=0（锁与声明一致，无过期）
Select-String 'name = "(fschat|nltk)"' uv.lock → 2 处，均为 [tool.uv] overrides 头的回显行，
                          无任何 [[package]] 块（lock 里两包已彻底不存在）
包集合差分（HEAD:uv.lock vs 新 uv.lock）:
  old_pkgs=306  new_pkgs=295
  REMOVED(11)  = defusedxml, fschat, latex2mathml, markdown2, nh3, nltk,
                 prompt-toolkit, shortuuid, svgwrite, wavedrom, wcwidth
  ADDED(0)     = []
  VERSION_DRIFT(0) = []
```

11 项 = fschat + nltk + 仅由 fschat 带入的子树（`uv lock` 能整体摘除即证明无其它在锁包依赖它们）。**只减不增、零版本漂移**成立。

### 8.3 L2 实装冒烟——本机不可行（既存平台限制，非本改动引入）

本机 `uv sync --extra eval` **失败**，失败点与 fschat/nltk 无关：

```
× Failed to build chonkie==1.0.10
  building 'chonkie.chunker.c_extensions.split' extension
  error: Microsoft Visual C++ 14.0 or greater is required
```

- `chonkie` 由 `flashrag-dev` 引入，且**改动前后同为 1.0.10**（已核 `HEAD:uv.lock` 第 1208 行），即 `origin/main` 在本机同样装不上；
- PyPI 上 `chonkie-1.0.10` 发布的 wheel 仅 `macosx_*` 与 `manylinux_*`（cp39–cp313），**无任何 win_amd64 wheel** → 任何 Windows 机器跑 `--extra eval` 都必须本地编译 C 扩展。

结论：**本机（无 MSVC Build Tools 的 Windows）不可能完成 L2**，方案 §3 预留的「126 容器补跑」分支生效。

### 8.4 L2 补跑（126/ambari03，Linux）

126 侧另有一处既存限制：`git clone`/`git fetch` 到 GitHub 443 超时（对照组 `uv sync --extra eval` 因此在解析 `flashrag-dev` 时失败：`fatal: unable to access 'https://github.com/RUC-NLPIR/FlashRAG.git/'`），而 PyPI 可达。故补跑采用**保真替代供给**：

- 包版本：`uv export --extra eval --no-hashes --no-annotate` 从**本分支新 lock** 导出精确 pin（180 行；该导出文件里 `^(fschat|nltk)==` 命中 0，另证 8.2）。剔除三类不可用行：`-e .` / `-e ./packages/*`（workspace 成员与本冒烟无关，且在 `/root` 下会被 uv 当项目根而报错：`/root does not appear to be a Python project`）与 `flashrag-dev @ git+...`；
- `flashrag-dev`：scp 本机 uv **wheel 缓存**里同 commit `d3feb72` 的已构建产物（`flashrag/` + `flashrag_dev-0.3.0.dev0.dist-info`，209 KB）落地到 site-packages，绕开远端 git 限制；
- 解释器：`uv python install 3.12` 管理的 CPython 3.12.14（Linux）。

冒烟断言（**实跑结果，rc=0**）：

```
fschat_present=False
nltk_present=False
IMPORT_OK config/dataset/evaluator/retriever
torch=2.13.0+cu130 transformers=5.15.0 faiss=ok
REFINER_BLOCKED=nltk   # 预期：flashrag.refiner.llmlingua_compressor 确实需要 nltk
```

前三行是核心结论：按新 lock 精确 pin 组装的 Linux 环境里 fschat/nltk **确实不存在**，而 `make eval-rag` 入口的全部 4 个 flashrag import（含之前未列入静态分析范围的 `retriever.retriever`）**仍然成功**；`torch/transformers/faiss` 可导，说明重型依赖未被误伤。最后一行同时把 §5「副作用」从推断升级为实测：要跑 LLMLingua refiner 必须先移除本 override。环境体积 5.8 GB（取证后已清理，不留在 126）。

> 如实声明的偏差：8.4 的环境由「导出 pin + 同 commit 本地产物」拼装，**不是** 在 Linux 上完整跑通 `uv sync --extra eval`（受 126 GitHub 网络限制）。它证明的是「缺 fschat/nltk 时 eval 入口 import 面可用」，不证明 uv 在 Linux 上的整体装配流程（后者本就与本改动无关）。

### 8.5 门禁（本机，**通过**）

```
uv run --with ruff ruff check .        → All checks passed!
uv run python scripts/lint_architecture.py → P4-2 / P2 / P5 等全部通过
uv run python scripts/check_doc_sync.py    → ✅ 文档同步校验通过（0 警告）
uv run pytest -q（根 session）         → 622 passed, 17 skipped in 95.94s
```

### 8.6 L3/L4 状态

- L3（`make eval-rag` 端到端出数）：需 pgvector + 真实 embedding/rerank 服务，本机与 126 均不具备完整条件 → **未验证**，不写「通过」。
- L4（告警侧）：见 §9 收口回报。

## 9. 收口回报（2026-09-30 实拉状态）

**甲类 14 项已 dismiss**（`dismissed_reason=not_used`，逐条附 ≤280 字符证据注释），执行前用守卫确认「只 dismiss `manifest_path` 不在 main tree 的告警」（tree `entries=1102`、`truncated=false`；若 manifest 仍存在于 tree 则脚本直接拒绝）：

```
#1 asyncmy critical | #2 anyio medium | #3 anyio critical   ← courses/zhanggui-wenda/data-agent/uv.lock
#9 asyncmy critical | #10 anyio medium | #11 anyio critical ← zhanggui-wenda/data-agent/uv.lock
#12 #16 #17 mcp high | #13 transformers medium | #14 #15 #18 transformers high
#19 accelerate medium                                      ← zhanggui-zhiku/uv.lock
→ 全部 state=dismissed reason=not_used dismissed_by=Light-Towers
```

**实拉剩余 open（`?state=open`）**：

```
OPEN_TOTAL=7
  fschat  high x4 + medium x2   manifest=uv.lock
  nltk    high x1               manifest=uv.lock
按严重度：{high: 5, medium: 2}   （critical 0）
```

即 21 → 7：**critical 全部清除**（4 项均为甲类孤儿告警），high 11→5、moderate 6→2。

**为何不是 0**：这 7 项的修复在 PR #24（`fix/dependabot-eval-transitive` → main），**必须等到合并进 main 且 Dependabot 重扫（weekly，`directory: "/"`）才会翻为 fixed**。在未合并、未重扫前声称「21 项已清零」即为伪报。合并与重扫后的复核动作：`gh api "/repos/Light-Towers/agent-platform/dependabot/alerts?state=open" --jq length` 应为 0。

### 9.1 GitHub API 实操坑（写入以免下次重走）

- dismiss 的键名是 **`dismissed_reason` / `dismissed_comment`**，不是 REST 文档常见引用的 `dismissal_*`；传错得 `HTTP 422 "… are not permitted keys"`。
- `dismissed_comment` **上限 280 字符**，超长得 `HTTP 422 Only 280 characters are allowed`（此次先试长文本失败后改写为短版）。
- 方法为 `PATCH /repos/{o}/{r}/dependabot/alerts/{n}`，body `{state:"dismissed", dismissed_reason:"not_used", dismissed_comment:"…"}`。
- Windows PowerShell 5.1 传 `gh api --jq '…"…"…'` 会把内嵌双引号吞掉（jq 报 `unexpected token "\\"`）；需带引号的 jq 表达式改用 Python `subprocess` 直调 `gh` 传 argv。

## 10. 本任务遗留

1. ~~PR #24 待人工确认合并~~ → **已合并**（`2026-09-30T10:10:16Z`，merge commit `42cfe35`，CI 6/6 pass），见 §11。
2. ~~合并后等 Dependabot 重扫，按 §9 命令复核应为 0~~ → 重扫已发生：**原 7 项全部 `fixed`**（override 真修被扫描器独立确认），但同一轮**新暴露 10 项 PyJWT**（#27–#36），预测的「应为 0」未成立；已按「先取证再定性、不直接 dismiss」处理，转 §11。
3. L3（`make eval-rag` 端到端出数）在本机与 126 均无完整条件，**未验证**；若后续要声明「评测链路因 override 而回归」需先补环。

## 11. PR #24 合并后的重扫回报：原 7 项 fixed，新暴露 10 项 PyJWT（2026-09-30 二轮）

PR #24 于 `2026-09-30T10:10:16Z` 合入 main（merge commit `42cfe35`）。Dependabot 在 **10:11:23–10:11:25**（合并后约 1 分钟）自动重扫默认分支，实拉结果：

**① 原 7 项全部翻 `fixed`（override 真修得到独立确认）**

```
ALERT#20 fschat state=fixed fixed_at=2026-09-30T10:11:23Z
ALERT#21 fschat state=fixed fixed_at=2026-09-30T10:11:24Z
ALERT#22 fschat state=fixed fixed_at=2026-09-30T10:11:24Z
ALERT#23 fschat state=fixed fixed_at=2026-09-30T10:11:24Z
ALERT#24 fschat state=fixed fixed_at=2026-09-30T10:11:24Z
ALERT#25 fschat state=fixed fixed_at=2026-09-30T10:11:25Z
ALERT#26 nltk   state=fixed fixed_at=2026-09-30T10:11:25Z
```

非 dismiss、非人工关闭，是扫描器对照新 `uv.lock` 判定的 fixed → §8 的静态/实装证据与真实扫描器结论一致。

**② 同一轮重扫新暴露 10 项（alert #27–#36），全部 `PyJWT` / `manifest=uv.lock` / `scope=runtime` / `relationship=transitive`**

| GHSA | severity | vulnerable range | first_patched | alert |
|---|---|---|---|---|
| GHSA-ffc3-869f-jxw9 | **critical** | `<= 2.13.0` | 2.14.0 | #33 |
| GHSA-9v7f-9g4p-ffgj | high | `<= 2.13.0` | 2.14.0 | #31 |
| GHSA-p4g4-x82p-q773 | high | `>= 2.4.0, < 2.14.0` | 2.14.0 | #30 |
| GHSA-w2cx-738m-mc7w | high | `= 2.13.0` | 2.14.0 | #32 |
| GHSA-r6x4-923q-g947 | high | `= 2.13.0` | 2.14.0 | #29 |
| GHSA-9j54-fg26-wv3r | high | `>= 2.13.0, < 2.14.0` | 2.14.0 | #36 |
| GHSA-2gx3-rcp4-g85q | medium | `<= 2.13.0` | 2.14.0 | #28 |
| GHSA-hxm8-2xgr-2p9m | medium | `<= 2.13.0` | 2.14.0 | #34 |
| GHSA-w6j9-cwv2-h6wq | medium | `>= 2.9.0, <= 2.13.0` | 2.14.0 | #27 |
| GHSA-8wjv-2p76-3863 | medium | `>= 2.13.0, < 2.14.0` | 2.14.0 | #35 |

10 条告警 = **10 个不同 advisory、但收敛于同一个包同一个版本线**，`first_patched` 全部是 **2.14.0** → 单点升版即可全清。包名在 Dependabot 侧以 `PyJWT / pyjwt / pyJWT` 三种大小写重复出现（同一 lock 内规范名为 `pyjwt`），是账号侧索引噪声，不影响处置动作。

**为何 §10.2 的「重扫应为 0」没成立**：原始 21 项快照（推送时回显）只含 fschat/nltk（根 lock）+ 14 孤儿（courses/*），**从未包含 PyJWT**；pyjwt 2.13.0 一直在 lock 里，但原快照未将其列为告警（无法仅从告警 API 判定原因——可能是 advisory 发布时间晚于上次扫描，或上次扫描快照较早）。无论何种原因，本轮重扫把这 10 项补齐了，它们是对当前 lock 的真实命中。**处理原则不变**：仍 open 的先取证再定性，绝不因「不想再看」而直接 dismiss；也不得因「旧告警已处理」就推断总体已清零。

### 11.1 反向依赖与可修性取证

```
MAIN_HEAD: 42cfe35      MAIN_LOCK_PKG_COUNT: 295      MAIN_PYJWT: 2.13.0
DEPENDENTS_ON_PYJWT: mcp 2.0.0        （lock 内唯一第三方引入者）
PYJWT_DEPS: cryptography              （自身只依赖 cryptography，已在 lock 内）
```

- `mcp 2.0.0` 的 PyPI 元数据要求：`pyjwt[crypto]>=2.10.1` —— **无上限**，升到 2.14.0+ 不违反其契约。
- 根包 `[project.optional-dependencies] identity` 声明 `pyjwt[crypto]>=2.9`（同样无上限），本轮解析未被安装进 lock（唯一需求边来自 mcp）。
- PyPI 现状：`LATEST=2.15.1`，可用版本线 `2.14.0 / 2.15.0 / 2.15.1` 全部高于所有 vulnerable range 上界。
- 结论：**属于「有补丁版本」的常规可修项**，与 fschat/nltk 的「无补丁只能摘除」不同，走版本下限约束即可，不需要 override 摘边，也不需要考虑 dismiss。

### 11.2 修复手法与验证

- **手法**：沿用本仓既有 `[tool.uv] constraint-dependencies` 机制（与 `pyarrow>=25.0.1` 同处），追加 `pyjwt>=2.14.0`。选 2.14.0 作为下限而非钉死 2.15.1：与既有写法一致，让 resolver 取当前最新兼容版，后续小版本跟随不需改文件。
- **L1（lock 回归判据）**：要求包集合不变（ADDED=0 / REMOVED=0），仅 `pyjwt` 一条 VERSION_DRIFT（2.13.0 → ≥2.14.0）；`pyjwt[crypto]` 的 crypto extra 与 cryptography 已在位，预期无新增包。
- **门禁**：`uv run --with ruff ruff check .` + `lint_architecture.py` + `check_doc_sync.py` + 根 pytest session（与 §8.5 同口径）。
- **不做**：`--extra eval` 相关链路本轮不涉及（PyJWT 由 mcp 带入，与 eval extra 无关），故无需再走 126 补跑；本机 Windows 的 chonkie 阻断（§8.3）依旧存在，不因此次改动变化。

### 11.3 收口判据

合并进 main 且下一轮重扫后复核 `state=open` 应为 **0**；若仍有残留，按本节日志法重新取证（列出编号/包/advisory/first_patched），不得直接 dismiss。

## 12. 第三轮：PR #30 合并后重扫又暴露 13 项（2026-10-01）

PR #30 于 `2026-09-30T23:59:41Z` 合入 main（merge `8d53333`）。Dependabot 在 **2026-10-01T00:01:49–00:01:55Z**（约 2 分钟后）再次重扫：10 项 PyJWT 已翻 `fixed`（本轮 open 清单里已无 pyjwt），但**同时新开 13 项**（#37–#49）。证明 §10.2/§11.3 的「重扫应为 0」预测连续两轮不成立——**本仓 Dependabot 处于「每有 advisory 发布就持续重开告警」的稳态，不能以旧告警已处理推断总体归零**。

### 12.1 索引来源查证（为何不在 main 的 courses/* 仍产告警）

- main 树内唯一的依赖配置只有根 `.github/dependabot.yml`（`package-ecosystem: uv` / `directory: "/"`），**无任何 pip 生态或 courses/* 目录的 config**。
- 但这 13 项的 ecosystem 全是 `pip`，且 10 项落在不在 main 的 `courses/zhanggui-wenda/data-agent/uv.lock`、`zhanggui-wenda/data-agent/uv.lock`、`zhanggui-zhiku/uv.lock`。
- **存在性双重否定证据**（互相印证）：`git/trees/main?recursive=1`（`truncated=false`）只含根 `uv.lock`；直接 `contents/courses/.../uv.lock?ref=main` 返回 **HTTP 404**。（注：曾一度用 PowerShell foreach 批量探测得出“存在”的相反结论，但该输出被 PS 报错污染不可信，以单次干净调用为准。）
- **机制定性**：这些是早期 commit（`981adbb`/`b546aa5`/`e54aa62`，courses/ 尚未移除时）遗留在 Dependabot 依赖图中的**僵尸清单**。advisory 发布时 Dependabot 会把新 CVE 映射到这些已注册、但已从默认分支删除的历史 manifest 上→开新编号告警；因当前 config 不扫这些目录，它们**永不会自动 fixed**，只能 dismiss（与那 14 项同构）。

### 12.2 13 项分类

| 组 | 告警 | manifest | 包 / 状态 | 处置 |
|---|---|---|---|---|
| **真身（IN main）** | #40 #41 #42 | `uv.lock`（根）| urllib3 2.7.0（high×2/med×1），first_patched=2.8.0 | 升版到 2.8.0 可全清 |
| **僵尸孤儿** | #37-39 #43-45 #46-48 | courses/*、zhanggui-* | urllib3，manifest 不在 main | dismiss `not_used` |
| **僵尸+无补丁** | #49 | zhanggui-zhiku/uv.lock | transformers，first_patched=None 且不在 main | dismiss `not_used` |

### 12.3 urllib3 真修：为何不直接合并 Dependabot #31

Dependabot 已自开 PR **#31**（bump urllib3 2.7.0→2.8.0，单文件 uv.lock，CI 过、mergeable），看似可直接合。但 **扒它的 diff 发现不是外科式升级**：它是一次全量 re-resolution 抖动（重写 nvidia-*/cuda-pathfinder/h11/truststore/requests 等大量 marker，并改动 beartype/requests 的条件依赖）。这跟本仓由固定 uv 版本产出的 lock 不一致，合并爆炸半径不可控，还可能隐性 revert #24/#30 的不变量。**决定：自己用 `uv lock --upgrade-package urllib3` 做最小改动 PR，#31 关为 superseded。**

### 12.4 实施与验证（本轮）

- **改动**：`uv lock --upgrade-package urllib3` → **仅 3 行 diff**（urllib3 版本 + 两条 sdist/wheel 哈希）。
- **L1**：包集合 295 不变，ADDED=0 / REMOVED=0，仅 1 条漂移 `urllib3 2.7.0→2.8.0`；`pyjwt` 仍 2.15.1（#30 在位）；fschat/nltk **无 `[[package]]` 块**（只在头部 `overrides` 回显 L36/37，#24 完好）。
- **门禁**：ruff 全过 · lint_architecture 全过 · check_doc_sync 通过 · 根 pytest **622 passed, 17 skipped**。
- **孤儿 dismiss**：10 项（#37-39/43-49）走与 §9 相同的守卫（dry-run + 仅 manifest 不在 main 树才放行）+ `not_used` 短证据注释。
- **不动**：#26–#29 例行升级 PR（非安全告警，#26 含 13 更新）本轮不处理。

### 12.5 验收与后续治理建议

- 本轮预期：#40-42 随 urllib3 PR 合并+重扫后翻 fixed；#37-39/43-49 dismiss 后不再出现在 open。
- **结构性问题**：只要僵尸清单还挂在 Dependabot 图上，每次 urllib3/transformers 等基库出 CVE 就会重开一批 courses/* 告警，dismiss 成可循环劳动。候选长期方案（需另行方案+确认）：核 GitHub 能否从依赖图移除已删 manifest（或开 GitHub Support 工单）；评估是否可以归档/删除历史引入这些锁文件的旧分支。本轮先按用户决策完成取证与记录，不改 dependabot config、不动 #26-29。



