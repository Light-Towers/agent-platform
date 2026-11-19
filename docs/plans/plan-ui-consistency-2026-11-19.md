# UI 一致性收敛（消除样式散点，P3 债务）

> 状态：实现中。触发：用户 2026-11-19 要求处理 P3「全局统一靠机制」欠账。审计结论：`docs/.../plan-ui-consistency` 对应 subagent 报告（本文件附录摘要）。
> 原则：P1 修类不修点（收敛同一根因的所有散点）、P3 单一实现+门禁强制、P4 边界先行（只动证据确凿的最小集，不碰死类删除）。

## 审计证据（实取）
- `.is-active` 描边浮起态 **逐字 3 份**：`base.css:655-658 / 688-692 / 765-768`，声明完全相同 `border-color: var(--ry-primary); background: var(--bg-raised)`。消费者：ChatStream(KbUpload)、KnowledgeBaseSidebar、App 会话列表。
- 行内图标按钮 padding/color **5 份重复**：`base.css:704-708 / 777 / 778 / 786 / 787`。
- 空态容器 **3 套壳**：`.empty:239` / `.chat-stream__empty:806` / `.kb-workspace__empty:671`，各仅 1 消费者。
- 列表主操作钮 `.session-list__pick` / `.kb-sidebar__pick` 重复，且 KbUpload 跨组件借用后者（语义错位）。
- **门禁盲区**：check-tokens/ check-events 都不管类复用——三份 is-active 用着合法令牌全绿，新增第 6 份也无感。

## 范围（P4 边界）
**本次做**（风险最低、证据最硬、逐字相同）：
1. 合并 `.is-active` 描边浮起态为单一 `.is-active`（无前缀），三个组件各自保留自己的 `__item` 布局类 + 加通用 `.is-active`。
2. 新增**结构复用门禁** `check-ui-consistency.mjs`：`is-active` 的"描边浮起"声明块全仓恰好 1 处（合成违规能咬 + 真面参与判决），违反即红。

**本次不做**（超出边界，另议）：
- 行内图标按钮 `.ry-btn--icon` 收拢（涉及 5 处 + 确认按钮颜色分叉，语义复杂）
- 空态容器三合一（形状有差异，需产品拍板虚线/实线）
- `.ry-list-pick` 合并（需改 KbUpload 借用）
- 死类删除（`.ry-btn--danger` 等，属清理非复用）

## 实现
- `base.css`：删 3 处 `__item.is-active` 的重复声明，加一条全局 `.is-active`。
- 三个模板：在 `__item` 上追加通用 `is-active` class（保留原 BEM 类供布局）。
- `web/scripts/check-ui-consistency.mjs`：扫 base.css，统计"含 `border-color: var(--ry-primary)` 且 `background: var(--bg-raised)` 的选择器块"数量，必须 ==1；同时自证能咬（合成插入第二块 → 期望非零）。接入 package.json 的 lint 链（与 check-tokens 并列）。
- `web/scripts/verify` 门禁文档（若有）登记新判据。

## 实现结果
- `base.css`：删三处 `__item.is-active` 重复声明，末尾加全局 `.is-active`（蓝边+raised底）。
- 三个模板无需改（都已带 `is-active` 类）。
- 新门禁 `web/scripts/check-ui-consistency.mjs`：扫 base.css（先剥注释再判，避全文扫坑），选中态声明块恰好 1 处且选择器正好 `.is-active`；固定合成样本自证能咬。
- 接入：`web/package.json` 加 `check:ui-consistency` script；`Makefile:ci-web` 加一行；`web/README.md` 门禁件登记。

## 验证（真浏览器+门禁）
- ✅ 门禁全套绿：typecheck/lint/check-tokens/check-events/check-ui-consistency。
- ✅ 新门禁能咬：正常 rc=0；注入第二块 `.rogue-item.is-active` → rc=1 列出两处；恢复 rc=0。
- ✅ **真浏览器 computed style 抓到一个 CSS 坑并修复**：初版把全局 `.is-active` 放在 base.css 前部（211 行），被后定义的 `.session-list__item { border: 1px solid ... }` **简写覆盖**（同为 0,1,0，后者胜出）——三处选中态实测是灰边非蓝边。修复：把 `.is-active` 移到 base.css 末尾（所有布局类之后）。再测三处均 `border=rgb(64,158,255)` / `bg=rgb(35,39,46)` 完全一致。这正是 P5（真浏览器验证）的价值——门禁全绿但视觉是错的。
- 未做（边界外，另议）：行内图标按钮 .ry-btn--icon、空态容器三合一、.ry-list-pick 合并、死类删除。
