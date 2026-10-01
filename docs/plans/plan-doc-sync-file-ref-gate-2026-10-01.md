# 方案：doc-sync 门禁补齐「文件引用」校验 + 修复存量路径漂移（2026-10-01）

> 类型：工具/门禁（`scripts/check_doc_sync.py`）+ 文档修正。规模：小。风险：低（只增校验面，不改任何产品代码路径）。
> 关联：本项源自 PR #33 收尾时的附带排查，与 CodeQL 主题无关，故拆独立分支 `fix/doc-sync-file-ref-gate`。

## 1. 背景与实测事实

先实测再动手，以下均为本仓当前状态的可复跑结论：

- **存量真实漂移 1 处**：`ARCHITECTURE.md:91` 引 `` `docs/architecture-boundary-app-vs-agent-federation.md` ``，实际文件在 `docs/architecture/architecture-boundary-app-vs-agent-federation.md`。`origin/main` 上同样如此。
- **门禁为什么没报警**（读 `scripts/check_doc_sync.py` 第 116–122 行确认，非推测）：

  ```python
  if path_str.startswith("http") or "." not in path_str.split("/")[-1]:
      if not path_str.endswith("/"):
          continue
  if path_str.endswith("/"):
      check_path_exists(...)
  ```

  带扩展名的引用（如 `x/y.md`）既进不了第一个分支的 `continue`，又不满足 `endswith("/")`，于是**直接落空、从未被校验**。`check_agents_md_paths()` 另有一处窄面：正则 `^\|\s*\`([^\`]+)\`\s*\|` 只匹配表格首列，行文内的反引号引用一概不查。
- **误判纠正**：中途曾登记「根 `AGENTS.md` 推荐的 `docs/operations/testing-playbook.md` 在仓内不存在」。该结论**不成立**——`git grep testing-playbook` 显示 `HEAD`/`origin/main`/`origin/v3` 的 `AGENTS.md` 命中 0，只有 `feat/isolation-hardening` 命中 1（且该分支持有该文件）。错因是把会话上下文里缓存的另一分支 `AGENTS.md` 当成了本分支事实。playbook 属该未合并分支的内容，本方案不动它。
- **范围必须排除 CHANGELOG**：一次性脚本对 4 份顶层文档探测得 117 个文件引用、25 个不存在，其中 **24 个在 `CHANGELOG.md`**（历史条目所指文件后来被移动/重命名，如 `tests/test_graph_planner.py` → `applications/agent_server/tests/`）。CHANGELOG 是 append-only 历史快照，按既有约定「历史快照文档不回改」；若纳入校验，门禁上线即一片红 → 必被当噪音关掉，反而破窗。故只校 `AGENTS.md` / `ARCHITECTURE.md` / `README.md` 三份**现状文档**。

## 2. 目标与非目标

**目标**
1. 修复 `ARCHITECTURE.md:91` 的存量路径漂移。
2. 让 `check_doc_sync.py` 校验现状文档里的**文件引用**（含行文内联），使同类漂移此后在 CI 失败而非靠自觉。
3. 门禁自身可测：判定谓词可单测，杜绝「静默失效」（谓词被改坏后检测面归零但 CI 仍绿）。

**非目标**
- 不改 CHANGELOG 历史条目；不校验 CHANGELOG。
- 不做 Markdown 链接 `[text](path)` 的 URL/锚点解析（只处理反引号引用，其余登记为已知漏报面）。
- 不引入新依赖，不碰产品代码。

## 3. 设计（单一实现 + 强制门禁）

在 `scripts/check_doc_sync.py` 增加一个共享谓词 + 一个校验函数，由 `main()` 统一装配（不在各 check 里重复实现）：

- `DOC_FILE_REF_DOCS = ("AGENTS.md", "ARCHITECTURE.md", "README.md")`
- `DOC_FILE_REF_ROOTS`：`applications/ packages/ docs/ scripts/ tests/ eval/ deploy/ courses/ .github/` —— 引用必须以其中之一开头才判定，避免把 `agent_core.guardrails.fs` 这类模块路径、外部 URL、口语片段误当路径。
- `DOC_FILE_REF_EXTS`：`md py toml yml yaml sh sql jsonl json cfg ini txt lock ps1 cmd` —— 末段必须命中已知扩展名。
- `DOC_FILE_REF_SKIP_CHARS = "*?<>${}()| "`：含通配符/占位符/空格的片段（如 `applications/*/pyproject.toml`、`<改动目录>/tests`）不判定。
- `is_doc_file_ref(text) -> bool`：纯谓词，无 IO，便于单测。
- `check_doc_file_refs(root=REPO_ROOT, docs=DOC_FILE_REF_DOCS) -> None`：逐行取反引号片段，命中谓词则复用**现有** `check_path_exists()` 报错（错误格式与既有校验项一致）。

**取舍声明**：判定面刻意保守——**宁漏报不误报**。误报会把门禁变成噪音并诱导关掉它；漏报只是维持现状。已知的两个漏报面（非顶层前缀的相对路径、Markdown 链接形式）在此明文登记，不假装全覆盖。

## 4. 影响面

| 对象 | 影响 |
|------|------|
| `scripts/check_doc_sync.py` | 新增 1 谓词 + 1 校验函数 + `main()` 一行装配 |
| `ARCHITECTURE.md` | 1 行路径修正 |
| `tests/governance/` | 新增门禁自检文件：真实树 0 违规 + 构造坏引用必报错 + 通配/占位不误报 |
| CI | 复用现有 `Doc sync check`（`.github/workflows/agent-platform-ci.yml:62`），无需改 workflow |
| 产品代码 / 运行时 / 对外契约 | 无 |

## 5. 验收标准

1. `uv run python scripts/check_doc_sync.py --verbose` 退出码 0、0 警告（即修完 §1 漂移后无新增违规）。
2. **非空洞性自证**：临时在 `ARCHITECTURE.md` 注入一个不存在的 `docs/nope-missing.md` 引用 → 脚本退出码 1 且报出该行；验证后撤销注入。
3. 新增单测在根 pytest session 通过；`uv run python scripts/lint_architecture.py` 全项通过（未触碰架构不变量）。
4. `docs/plans/plan-codeql-codescanning-remediation-2026-10-01.md` 中原「附带发现」条目的纠正已入库（PR #33 分支 `4acd366` 已做）。

## 6. 回滚

纯文档 + 门禁面：`git revert` 单个提交即可，无数据/契约迁移。
