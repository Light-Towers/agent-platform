# Dependabot 21 项告警收口方案（2026-09-30）

> 触发：门面退役推送后 GitHub 在 push 输出提示「21 vulnerabilities on default branch（4 critical / 11 high / 6 moderate）」。用户要求「将这 21 个漏洞修复掉」。
> 本文是**方案 + 实施记录**（AGENTS.md 红线：改动前先出方案）。§0-§7 为取证与方案，§8-§10 为实施与验证结果（分支 `fix/dependabot-eval-transitive`，PR #24）。

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

1. PR #24 待人工确认合并（本仓约定：合并动作等最终确认）。
2. 合并后等 Dependabot 重扫，按 §9 命令复核应为 0；若仍有 open，重新取证而非直接 dismiss。
3. L3（`make eval-rag` 端到端出数）在本机与 126 均无完整条件，**未验证**；若后续要声明「评测链路因 override 而回归」需先补环。


