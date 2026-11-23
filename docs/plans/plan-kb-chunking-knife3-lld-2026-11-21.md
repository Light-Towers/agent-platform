# 刀 3 施工清单（LLD）：前端 UI（切分设置编辑 + 上传页精简 + 同名覆盖提示）

> 状态：✅ 已施工（2026-11-21 主体 + 2026-11-22 上传后读数增强；HEAD=0f3a26b0 工作区未提交；typecheck/lint/3 门禁/build 全绿） ｜ 依据：主方案 `docs/plans/plan-kb-chunking-profile-2026-11-20.md` §9 刀 3 ｜ 回写：提交后复取 §5 读数

> **2026-11-22 追加（产品决策：不做上传前预览，强化已有读数）**：后端 `node_document_split.py` 的 `step_5b_collect_summary` 增 `effective_config`（本次生效策略/标签/块大小/重叠）+ `warnings`（超长表格降级告警），`step_2_split_by_lines` 收集告警；前端 `kb.ts` 的 `KbTaskStatus.summary` 增两字段，`KbUpload.vue` 读数卡片显示"本次按 X 执行"+ ⚠ 告警行。复测：KS 单测 536 passed（+5，含必填参数断言），web lint/tokens/ui-consistency/build 全绿。`step_5b_collect_summary` 的 `effective_config`/`warnings` 为**必填参数**（2026-11-22 收紧：前后端同批发布、无旧调用方，漏传由 TypeError 暴露而非静默给空）；前端 `?.`/`?? []` 保留是处理"任务未切分时 summary 为空"的正常态，不是版本兼容。

## 0. 范围（主方案 §9 刀 3）

**做**：
1. 切分设置编辑放在左侧栏（库管理区）——切分规则下拉 + 每片字数 + 重叠比例，保存到库配置
2. 上传页移除原 12 个元数据字段的"高级选项"，改为只读展示当前库切分配置
3. 同名覆盖提示（F-5）：选中的文件与库内已有文档同名（去后缀）时提示将被覆盖
4. 上传后读数保留（已有），刀 1/2 后它已能反映新切分

**不做**（已在主方案登记）：
- 上传前切分预览（F-6 砍掉，只留上传后读数）
- 预设快捷按钮（用户口径：默认填好、要改自己改）
- 测试集维护（开发侧）

## 1. 改动文件与要点

| 文件 | 改动 |
|---|---|
| `web/src/api/kb.ts` | `KbUploadForm` 精简为仅 `knowledgeId`；`uploadKbDocuments` 只 append files/tenant_id/knowledge_id（切分参数不随上传提交——KS resolver 读库配置兜底 F-7）；新增 `KbChunkConfig` 类型 + `DEFAULT_KB_CHUNK_CONFIG`；`KbKnowledgeBase` 加 `chunk_config?`；新增 `updateKbChunkConfig()`（PATCH body 仅 chunk_config） |
| `web/src/components/KbUpload.vue` | 删除高级选项 12 字段 + `DIALECT_OPTIONS` import；新增 `chunkConfig` prop + 只读配置展示 + `STRATEGY_LABEL` + `overwriteNames`（同名检测）；上传表单只用 knowledge_id |
| `web/src/components/KnowledgeBaseSidebar.vue` | 每库加"设置"按钮 + 内联切分编辑器（规则/大小/重叠），前端范围预检 + `updateKbChunkConfig` 保存，成功后 emit changed 同步上传页只读展示 |
| `web/src/components/KnowledgeWorkspace.vue` | `refreshTree` 并取 `listKnowledgeBases` 构建 `chunkConfigById`，传 `chunk-config` 给 KbUpload |
| `web/src/styles/base.css` | `.kb-sidebar__item` 加 `flex-wrap: wrap`；新增 `.kb-config-editor` 样式 |

## 2. 关键设计说明

- **切分参数不随上传提交**：后端刀 1 的 resolver 在未显式传参时读 `kb_collections.chunk_config`（F-7），所以前端只需在库设置页改配置，上传时无需带 chunk 参数——把"靠前端记得带"变成机制保证（P3）。
- **编辑只在库设置页**（F-12 配套）：上传页只读展示，不存在"单次上传临时改参数"，与"配置只挂库级"一致。
- **单位标"字符"**：UI 文案每片字数/重叠比例，重叠按百分比输入（0–50%），与后端 `chunk_overlap_ratio` 对应（服务端换算字符数）。

## 3. 验证（evidence-format §1 五字段）

- **rev**：`0f3a26b0`（未提交工作区；提交后复取）。
- **typecheck**：`cd web && npm run typecheck`（vue-tsc --noEmit）→ rc=0，无输出。
- **lint**：`cd web && npm run lint`（eslint）→ rc=0，0 errors 0 warnings（已 autofix 属性换行告警）。
- **check:tokens**：`node scripts/check-tokens.mjs` → ✅ 视觉门禁通过（定义 123 / 引用 123）。
- **check:ui-consistency**：→ ✅ 选中态单一实现 `.is-active`，合成反证已咬。
- **check:events**：→ ✅ 端点成对性 消费 14 / 提供 39 / 缺 0。
- **build**：`cd web && npm run build` → ✓ built in 606ms（60 modules）。
- **未跑**：真浏览器渲染截图确认（P5）——本环境无 Playwright/Puppeteer/CDP 工具，无法做 CDP 截图判据；按 AGENTS.md 事实纪律如实标注，不声称已验。建议后续在有浏览器的环境补一次：建库→设置切分参数→上传→看只读展示与同名提示的渲染。
- **前置**：刀 1/2 后端已在工作区（resolver + 三策略 + /collections chunk_config 接口）。
