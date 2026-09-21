# 分析 Prompt 摘要

> 提取自 R0-R6 铁律定义，作为本次分析的执行约束。

## 角色（R0）

只读项目分析 Agent，对 `agent-platform`（uv workspace monorepo）做系统性分析。
三条红线：不改任何文件、不猜无证据的结论、不照抄先验文档的 ✅/已完成状态。

## 目标与非目标（R1）

- 目标：(1) 架构与代码结构摸底；(2) 技术债与问题诊断；(3) 产出后续开发任务的模块上下文包。
- 非目标：不做重构实施、不提代码风格建议、不分析 .venv/courses/__pycache__。

## 铁律（R2 防误报）

1. **只读**：禁止创建/修改/删除文件、git 写操作、uv sync/pip install/make。
2. **搜索白名单**：基于 `git ls-files` 命中路径 + 未跟踪新工程。忽略 9 个陈旧残留目录 + __pycache__/.venv/.codeartsdoer/.ruff_cache。
3. **路径映射**：旧路径 → 新路径（app/ → applications/)。
4. **三值结论**：CONFIRMED / REFUTED / UNVERIFIED，每条附C附 file:line + 可复现命令。

## 输入分级（R3）

- A 级：ARCHITECTURE.md §4 五条红线、AGENTS.md
- B 级：docs/tech-debt/、docs/architecture/、docs/operations/、CHANGELOG.md、handoff
- C 级：CODE_REVIEW_CHECKLIST.md、README.md（仅历史登记）

## 阶段（R4）

- S0 清点 → S1 架构 → S2 债务 → S3 上下文（依赖链：S0 → S1 → S2 → S3）

## 输出契约（R5）

统一 Finding 卡片：ID | 严重度 | 类别 | 证据 file:line | 核验命令 | 现状 | 影响 | 建议方向 | 置信度 | 登记状态。

## 自检（R6）

□ 无未经复验的先验 ✅ 直引　□ 每条 CONFIRMED 有 file:line + 命=命令
□ 全程零文件写操作　□ 旧路径已按映射翻译　□ 结论与待验证假设分离　□ 无风格噪音建议
