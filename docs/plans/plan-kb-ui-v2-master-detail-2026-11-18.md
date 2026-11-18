# 知识库页 v2 重构方案（master-detail 主从结构）

> 状态：**已实现 + 真环境验证通过**（2026-11-18，rev=6961dd5c）。触发：用户要求参考成熟知识库平台（Dify/RAGFlow/Coze/飞书知识库）的范式：知识库可创建/编辑/删除，选中库后展示该库文档，文档可上传/删除。当前页面是"平铺上传+历史+管理"五段式，缺主从结构与独立建库/改名能力。

## 真环境取证（2026-11-18 19:07，绑 rev=6961dd5c）

- 部署：平台 `4d96efa1` / KS `bb76c5d5` 三节点一致；GIT_REV=6961dd5c；health 200；openapi 含 `POST /kb/knowledge-bases` + `PATCH/DELETE /kb/knowledge-bases/{id}`；v2 前端产物在位。
- **全链路闭环**：新建库 → `kb_e601ed5e20f5`（kb_ 前缀全局唯一 ID）→ 改名"v2改名后"（列表回读确认）→ 上传文档 PUBLISHED → 对话检索命中 8899 → 下线文档后 8899 不再召回 → 删库 200。[PASS-V2]
- **存量库补登**：P1 之前的 4 个存量库（verify-kb-*）幂等补进 kb_collections，管理页现可显示（1 个已存在跳过）。
- 测试账号取证期临时提权 admin（kb.publish），验后已降回 viewer。
- 漂移门禁台账更新到 v2 rev/digest，verify_basis_drift rc=0。

### 视觉/功能真实浏览器检查（2026-11-18 晚，用户要求"自己测一遍"）

用 Chrome headless + CDP（Remote Debugging）真实渲染页面并截图，发现门禁（typecheck/lint）查不出的样式问题并修复：
- **class 核对脚本**（node 提取模板 class vs base.css 定义）抓到 `.kb-sidebar` 用了但未定义 → 补定义。
- **CDP 截图**（port-forward 18080 + 登录注入 sessionStorage + 点侧栏菜单）确认：主从布局 grid 生效、4 库显示、空态引导；但发现库名显示成文件名（补登 name=filename）、右栏空态只占顶部一小条、长名折行 ✎× 溢出 → 修：补登 name 改 knowledge_id、空态 min-height 320、库名单行省略（commit f260c9d0）。
- **CDP CSS 探针**（本地 vite dev 注入长名假 DOM 测量）确认 × 按钮不再溢出（delRight≤itemRight）、ellipsis/nowrap 生效、grid 布局、空态撑满（commit 185c4e01，含 width:100% 的长名兜底）。
- **教训**：视觉问题只有真浏览器渲染能发现；typecheck/lint/class 门禁只查结构不查渲染。本次把"CDP 截图 + DOM 探针"作为前端改动的补充验证手段。

> 注：最后的 width:100% 长名兜底（185c4e01）本地探针验证通过但未随新镜像部署——线上真实库名均为短 ID（verify-kb-*），既有截图确认无溢出；该微调留待下次镜像重建一并上线。

## 目标

一个「知识库」页，master-detail 布局：
- **左栏（master）**：知识库列表 + 「+ 新建知识库」；每项可重命名、删除
- **右栏（detail）**：选中库后的文档列表（文件名/状态/时间 + 上传 + 删除）+ 上传区；未选中库时提示"请选择知识库"

## 后端能力缺口（需补）

| 能力 | 现状 | 需补 |
|---|---|---|
| 创建知识库 | 仅上传时 ensure_collection 隐式建 | `POST /collections`（name → 生成 knowledge_id 或用 name）|
| 编辑知识库名 | 无 | `PATCH /collections/{id}`（改 name，不改 knowledge_id 主键）|
| 删库 | ✅ DELETE /collections/{id}（409 前置）| — |
| 列库 | ✅ GET /collections | — |
| 列文档（按库）| GET /documents 全量，前端过滤 | 前端按 knowledge_id 过滤即可（≤100）|
| 上传文档 | ✅ /kb/uploads（knowledge_id 必填）| — |
| 删文档 | ✅ DELETE /kb/documents/{id}（软删 REVOKED）| — |

## 前端结构

- 新增组件 `KnowledgeBasePanel.vue`（左栏：库列表 + 新建 + 重命名 + 删除）
- 改造 `KbUpload.vue` 为右栏 detail：接收选中的 knowledge_id，上传时自动带入；文档列表按该库过滤；保留上传历史/切片读数（作为文档详情的展开）
- 或两组件放一个页面容器，用 provide/inject 或 props 传递选中库

## 最终设计（用户 2026-11-18 拍板）

- **master-detail 主从**：左栏知识库列表（新建/重命名/删除），右栏选中库的文档列表（上传/删除）。
- **knowledge_id 生成**：用户输入显示名 name，系统生成 `kb_<uuid4hex12>` 全局唯一 ID（写进 chunk 的锚点），name 单独存储、可改。
- **清爽页面**：右栏只放文档列表；上传历史/切分读数不在主列表堆砌，点单个文档才展开详情（参考 Dify/RAGFlow 点文档看 chunk 的交互）。
- **存量库补登**：P1 之前的库幂等补进 kb_collections（本次一起做）。
- 上传时在选中库上下文自动带 knowledge_id，无需手填。

## 待拍板设计点（已全部拍板，留档）

1. knowledge_id 怎么生成：用户填的 name 直接当 knowledge_id（简单，但需校验唯一）vs 系统生成 UUID + name 作显示名（规范，但用户看不到 ID 的含义）
2. 未选中库时：显示空态引导 vs 默认选中第一个库
3. 上传历史/切片读数（现有能力）放哪：保留在右栏详情区（点文档展开）vs 单独一个"处理记录"tab
4. 存量库补登缺口（kb_collections 只登记 P1 后上传的库）：这次一起补登吗
