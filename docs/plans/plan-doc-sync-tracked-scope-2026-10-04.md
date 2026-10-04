# 方案：doc-sync 存在性校验改以「版本控制清单」为基准（2026-10-04）

> 立项来源：`docs/TODO.md` §5 L78「`check_doc_sync.py` 的存在性校验以本机 FS 为基准，本机 gitignored 脏目录会把它喂绿」
> （第十条工具假阳性）。上一批只修了措辞（commit `101a92c`），**门禁盲区本尊未动**。
> 拍板：2026-10-04 用户选 **候选 ①**——用 `git ls-files` 把判定面限制在 tracked 路径。

## 1. 背景与实测事实

- **事故**：PR #65 推上 `7949357` 后，`ci` job 的 `Doc sync check` step 报
  `ARCHITECTURE.md:125: 路径不存在 '.codeartsdoer/temp/'`，而**本机同一命令一直 rc=0**，账面还写着 rc=0。
- **判定面（读码事实，非推测）**：三条存在性面全部汇聚到同一个函数 `check_path_exists()`：
  | 面 | 命中条件 | 过滤顶层前缀？ |
  |---|---|---|
  | `check_agents_md_paths()` | AGENTS.md 表格首列反引号、含 `/`、非 `http` | 否 |
  | `check_architecture_paths()` | ARCHITECTURE.md 反引号内含 `/` 且以 `/` 结尾 + 代码块目录树里 `applications/`、`packages/` 子目录 | **否**（`.codeartsdoer/temp/` 就是在此被判） |
  | `check_doc_file_refs()` | 三份现状文档、`DOC_FILE_REF_ROOTS` 前缀、必须带扩展名 | 是 |
  ⇒ **单一收口点就在 `check_path_exists()`**，修法只需改这一处（架构原则「单一实现」，不是散点补丁）。
- **影响面实测（动手前取）**：探针复用真实提取逻辑（`importlib` 载入模块 + 把 `check_path_exists` 换成记录器，
  不重新实现正则 ⇒ 判定面无漂移），与 `git ls-files -z` 交叉分类：
  `tracked_files=1072 / tracked_dirs=179`，当前被断言的引用 **98 条全部「本机存在 ∧ 已入库」**；
  `fs_only=0`（⇒ **本修法零新增红**）、`tracked_only=0`、`neither=0`。

## 2. 目标与非目标

**目标**

1. 让「文档断言了一个只在本机存在的 gitignored 目录」**在本机就红**（与 CI / 新克隆同构）。
2. **fail-closed**：取不到仓内清单时不放行——宁可红一次并说明原因，绝不静默退回 FS 基准。
3. 三条面共用同一实现（收口在 `check_path_exists()`，不各写一遍）。
4. 用例钉住两条非空洞性：「构造 gitignored 引用必红」与「git 缺席必红」。

**非目标**

1. 不改被校验文档集——CHANGELOG 与 `docs/**` 仍故意不校（理由已由
   `test_changelog_is_deliberately_out_of_scope` 钉住：append-only 快照所指文件后来多被移动）。
2. 不做候选 ②（CI 里导出干净树再跑）——那只把证据搬到 CI，**不解决本机假绿**。
3. **不加路径白名单 / allowlist**——白名单是本门禁最容易被破窗的地方；需要写「本机才有、不入库」的
   目录时，按 `101a92c` 的姿势改用**不带反引号的普通文本**（改措辞，而不是放宽判定强度）。
4. 不动 `scripts/lint_architecture.py`、Makefile、workflow、`.gitignore`、`pyproject.toml`、`uv.lock`。

## 3. 设计

```python
class TrackedIndex:
    """版本控制清单（与 CI 检出面同构）。files 为 posix 相对路径，dirs 由 files 派生。"""
    def __init__(self, files: Iterable[str], source: str = "explicit") -> None: ...
    def has(self, ref: str) -> bool:
        # 目录引用（带或不带尾斜杠）⇒ 命中派生 dirs；文件引用 ⇒ 精确命中 files

def load_tracked_index(base: Path) -> TrackedIndex | None:
    # `git -C <base> ls-files -z`；rc != 0 / git 不在 / 输出不可解 ⇒ None（**刻意不回退 Path.exists()**）

_AUTO = object()   # 默认哨兵：按 base 走 git（生产路径）

def check_path_exists(doc, line_no, path_str, base=REPO_ROOT, tracked=_AUTO) -> None:
    # tracked is _AUTO → idx = load_tracked_index(base)（按 base.resolve() 缓存，一次 ls-files 服务三条面）
    #   idx is None  → err("… 无法取得仓内路径清单（git ls-files 在 <base> 失败）⇒ 门禁 fail-closed，拒绝以本机 FS 为基准放行")
    #   否则用 idx.has(path_str) 判定；违规时再用 (base/path_str).exists() **只区分措辞**：
    #     FS 有 ⇒ "路径未纳入版本控制 '<p>'（本机存在但未入库：CI / 新克隆上不存在）"
    #     FS 无 ⇒ "路径不存在 '<p>'"
```

**关键口径**

- **判定基准 = git 索引**，本机 FS 仅在「已判违规」后用于区分措辞。理由：门禁要保的是「文档引用在
  新克隆上成立」，而 CI 检出的内容就是索引内容；本机工作树的临时增删（`git rm` 未提交、就地建的
  scratch 目录）**不是文档漂移**，不该由这个门判定。
- 空目录语义：git 不能跟踪空目录 ⇒ 文档写一个「本机有、但索引里没有」的目录会判红。这是**正确**行为
  （新克隆上该目录确实不存在），不是误报。
- 无 git 的环境（例如把源码 COPY 进容器后跑 docsync）⇒ 明确红一次并提示显式传 `tracked=`；
  **不提供 `--skip-git` 之类旁路开关**。

## 4. 影响面与落地清单

| 文件 | 改动 |
|---|---|
| `scripts/check_doc_sync.py` | 新增 `TrackedIndex` / `load_tracked_index` / `_AUTO` / 索引缓存；改 `check_path_exists()`；三条面各加 `tracked=_AUTO` 透传；docstring 增「校验基准 = 版本控制清单」 |
| `tests/governance/test_doc_sync_file_refs.py` | **迁移** 2 条 tmp_path 用例为显式传 `tracked=TrackedIndex([...])`（**断言逐字不变，只补输入**）；**新增** ≥5 条：gitignored-但-存在 ⇒ 红且措辞含「未纳入版本控制」、`load_tracked_index` 返回 None ⇒ 红（fail-closed）、`TrackedIndex.has` 的目录/文件/尾斜杠/`./` 语义、真实树在 auto 索引下 0 违规 |
| `docs/TODO.md` | L78 由开项改闭合，记实取与残余局限 |
| `CHANGELOG.md` | 新增本批段 |
| `docs/operations/testing-playbook.md` | §2.4 补一句：门禁已收到索引基准，干净检出复验仍作为**通用**纪律保留 |

零改动面：产品代码、测试断言强度、workflow、`pyproject.toml`、`uv.lock`、`.gitignore`、Makefile。

## 5. 验收标准（逐条可判，不靠形容词）

1. `uv run --no-sync python scripts/check_doc_sync.py` 在本机**脏工作树**（含 `.codeartsdoer/`、`.venv/`、
   `output/`）rc=0，且秒数量级不劣化（记录实测耗时）。
2. **核心新能力自证**：往 `ARCHITECTURE.md` 临时加一行含 `` `.codeartsdoer/temp/` `` 的引用 ⇒ 本机 docsync
   **rc=1** 且报「未纳入版本控制」；还原 ⇒ rc=0 且文件逐字相同。**这条就是 CI 抓到而本机放行的那一条。**
3. **fail-closed 自证**：monkeypatch `load_tracked_index` 返回 None ⇒ 三条面各产生「无法取得仓内路径清单」，
   错误列表**非空**（不放行）。
4. `tests/governance/test_doc_sync_file_refs.py` 全绿，用例数由 **17** 增至 **≥22**；被迁移的 2 条
   断言行逐字未改（`git diff` 可判）。
5. `uv run --with ruff ruff check .` rc=0；`uv run --no-sync python scripts/lint_architecture.py` rc=0。
6. 按 §2.4 的纪律，在主干 `3546190` 与本批 tip 的**干净 worktree** 上各跑一次 docsync ⇒ 均 rc=0
   （证明「新克隆语义下不误报」，也证明修的是判定基准而非措辞侥幸）。
7. CI：PR 上 `Doc sync check` 与两条 `ci` 矩阵实例全 pass；合入后用入库脚本在新 tip 复验判据 6
   （零 dismiss、最大告警号不增）。

## 6. 风险与回滚

- **风险 A**：将来文档需要写「本机才有、故意不入库」的目录 ⇒ 会被判红。
  处置：改用不带反引号的普通文本（见 §2 非目标 3），**不放宽门禁**。
- **风险 B**：`git ls-files` 的开销。实测本仓 `tracked_files=1072`，且按 base 缓存 ⇒ 一次调用服务三条面；
  验收 1 顺带记录秒数，劣化即回退设计。
- **风险 C**：非 git 环境跑门禁会红。这是**刻意选择**（fail-closed 优于静默放行），已在 §3 给出显式 `tracked=`
  的正道，不设旁路开关。
- **回滚**：单文件判定收口 + 用例，`git revert` 一个 commit 即回到 FS 基准；无数据、无契约迁移。

## 7. 实施结果回填（逐条对齐 §5，实取于本批工作树）

| 判据 | 结果 | 实取证据 |
|---|---|---|
| 1 脏工作树 rc=0 且耗时不劣化 | **达成** | `check_doc_sync.py` rc=0，**2.48s**（含解释器启动）；`load_tracked_index` 单次 **0.083s**（1072 files / 179 dirs，按 base 缓存 ⇒ 一次调用服务三条面） |
| 2 核心新能力自证 | **达成** | 差分自证（同一脏工作树 + 同一探针行 `` `.codeartsdoer/temp/` ``）：新实现 **rc=1** 报「路径未纳入版本控制」；旧实现（`git show 3546190:scripts/check_doc_sync.py`，放 ROOT 下恰好一层） **rc=0 放行**；`finally` 还原后 sha256 全等 + rc=0 |
| 3 fail-closed 自证 | **达成** | `load_tracked_index` 被换成返回 None ⇒ 三条面各产出一条「仓内路径清单不可用」；实取计数 agents=13 / arch=7 / refs=78 / explicit_None=1（均 >0）；用例 `test_fail_closed_when_index_unavailable` 钉住 |
| 4 用例全绿且 ≥22 | **达成（超预期）** | 17 → **35 passed**；被迁移的 2 条 tmp_path 用例**断言逐字未改**（`git diff` 可判），只补 `tracked=_idx(...)`；新增含 parametrize 共 18 条 |
| 5 ruff / lint rc=0 | **达成** | `ruff check .` rc=0；`lint_architecture.py` rc=0 |
| 6 干净 worktree 复验 | **达成** | `git worktree add --detach` 两个 sha（与 actions/checkout 同构，实取 `tracked files=1073`、`.codeartsdoer` 与 `.venv` 均不在场）：本批 tip `60655c0` 上**新实现 rc=0** 且用例 **35 passed**（证明绿不依赖本机脏工作树）；主干 `3546190` 上**旧实现 rc=0** 且 17 passed（基线对照）。验完 `worktree remove --force`，`git worktree list` 只剩主工作区。附带**入库 blob 逐字节面**（`git cat-file`）：8 个文件 crlf=0 / lone_cr=0 / 无 BOM / 无 NUL ⇒ `.gitattributes` 的 `* text=auto eol=lf` 已生效（工作树曾有 CRLF 不影响仓内形态） |
| 7 CI + 合入后复验 | **待取** | PR 上 `Doc sync check` 与两条 `ci` 矩阵全 pass；合入后用 `scripts/evidence/verify_main_tip.py` 在新 tip 复验判据 6 |

**与计划的偏差**（只记真实发生的）：

1. 实施中多做了两个面（不在 §4 清单里但属同一收口）：`AGENTS.md` 文档防漂移段与 `ARCHITECTURE.md` §4.2 口径③ 都补了「判定基准 = 版本控制清单」，理由：该门的口径需要被**下一个人读到**才算全局解，只写脚本文档不够。
2. 新增了一条**残余局限 ④**（见 `docs/TODO.md` L78 闭合段）：`git ls-files` 默认读索引而非 HEAD ⇒ stage 未 commit 的新文件也算「已入库」。该缝隙由判据 6 的干净 worktree 兜住，**不改用 `git ls-tree HEAD`**（那会让「新文件尚未 stage」这种常见中间态假红，噪声风险大于收益）。
3. 风险 B（`ls-files` 开销）实测**不成立**：0.083s / 单次，相对整脚本秒量级可忽略。
4. **账面自己当场撞了一次新门**（不是构造的探针，是真实漏报面）：本批往 `AGENTS.md:54` 与 `ARCHITECTURE.md:134`
   引了新方案文件，而它当时**尚未 stage** ⇒ docsync **rc=1** 并报两处「路径未纳入版本控制
   'docs/plans/plan-doc-sync-tracked-scope-2026-10-04.md'」；`git add` 后 **rc=0**。旧实现（FS 基准）同一棵树始终放行。
   ⇒ 这同一条就是残余局限 ④ 的镜像面（索引基准会把「写了但未入库的引用」挡在门外），也是本批里最强的一条真实证据。
