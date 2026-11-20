# 知识库页 UI 交互一致性收口（审查发现 10 项）

> 状态：实现中。触发（用户 2026-11-20）：反复出现"下线/上线/删除后 UI 状态过期、文档数不同步"，要求系统排查所有隐藏交互问题并全部修复。审查报告见本文件附录。
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
- 前端 typecheck/lint/6门禁/check-events/check-ui-consistency。
- 真浏览器（mock + 真环境）：下线→删除按钮即时出现、上线→即时消失、成功后绿提示、删库→右栏空态+下拉清理、改名→右栏新名、全部下线→可删库、刷新按钮有效、上传成功文档出现。
