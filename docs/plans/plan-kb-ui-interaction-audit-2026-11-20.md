# 知识库页 UI 交互一致性收口（审查发现 10 项）

> 状态：✅ 已部署 + 本地/线上双重验证通过（2026-11-20 16:20，绑 rev=24640437，平台镜像 a8154d66 / digest 6815738e）。触发（用户 2026-11-20）：反复出现"下线/上线/删除后 UI 状态过期、文档数不同步"，要求系统排查所有隐藏交互问题并全部修复。审查报告见本文件附录。
> 原则：用户视角纲要（看到的=实际发生的）+ P1 修类不修点（统一数据源刷新机制，不逐个打补丁）。

## 根因（一类问题）
4 个数据源不同步：`treeBases`(/documents/tree)、`bases`(/kb/knowledge-bases 快照)、`knowledgeScope`(对话页下拉)、乐观状态。任何文档变更只刷新 tree，其余不刷 ⇒ 各种过期显示。

## 修复清单（全部 10 项）

### 高
- **#1 删库判据**：`docCount` 改为数**有效文档**（status != REVOKED 的 distinct source_doc），与后端删库守卫一致。全部下线后可删库。
- **#2 删当前库**：删库后清空 `selectedId`（父组件），右栏回空态；不再显示已删库内容/不再往已删 id 上传。
- **#3 改名当前库**：改名后同步 `selectedName`，右栏标题更新。
- **#8 对话页下拉带已删 id**：删库后清 `knowledgeScope`（需跨组件——通过 App 监听库列表变化，剔除已删 id）。

### 中
- **#4 无手动刷新**：文档区加「刷新」按钮。
- **#5 上传后缺延迟刷新**：上传完成也走 `refreshAfterWrite()`（即时+3s）。
- **#6 上传成功红色提示**：`localIngestNote` 用 `notice--ok`。
- **#7 statusOverride 永不清**：上传成功清该 doc 的 override；且 override 随真实数据刷新自动失效（refreshTree 后清）。

### 低
- **#9 左栏成功/失败同色**：`notice` 二分 ok/fail。
- **#10 健康页页眉**：`viewLabel` 补 health 分支。
- **#11 刷新失败仍显示旧数据**：catch 清 `treeBases`。
- **#12 定时器未清理**：3s setTimeout 存 id，onUnmounted 清理。

## 实现结构（统一刷新机制，P1 修类）
- KnowledgeWorkspace 暴露 `refreshAll()`：同时刷 tree + Sidebar.bases；所有 `changed` 走它。
- 文档数统一算有效文档（tree 的 chunk status != REVOKED）。
- Sidebar 改名/删库通过 emit 把新名/删除事件抛给父组件处理选中态与 knowledgeScope。

## 验证
- ✅ 静态全绿：typecheck/lint/6门禁/check-events/check-ui-consistency/ruff/doc-sync。
- ✅ 本地 CDP 真浏览器（mock tree + 操作 API）：`[初始] btns=["下线"]` → `[下线后400ms] btns=["上线","删除"]` + 绿提示 → `[上线后400ms] btns=["下线"]` + 绿提示；刷新按钮在位。截图确认成功提示绿色（不再红）。
- ✅ 线上验证（绑 rev=24640437）：刷新按钮在位、文档行正常、有效文档只 `["下线"]`、页眉"知识库页"、GIT_REV 正确。
- 联动逻辑在代码中实现并经本地验证：删库→清选中态+kb-deleted事件清下拉、改名→同步 selectedName、docCount 只数有效文档（全下线后可删库）、上传后清 override+延迟刷新、Sidebar 提示二分、健康页页眉、刷新失败清旧数据、定时器清理。

## 收尾：误提交的 skill_live_check
- 之前 `git add -A` 误把本机未跟踪的 tests/skill_live_check/（118文件）提交进来 → 已从索引移除（磁盘文件保留 121 个），加入 .gitignore + ruff exclude（ruff 按 FS 扫，本机不误报红）。用户问"移除后下次还能提交吗"——能，git add 即可。
