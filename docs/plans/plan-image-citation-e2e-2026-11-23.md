# 图片与引用回显端到端（image-citation E2E）——治本方案：单一富回答契约 + 结构化证据不丢失

> 状态：Accepted / 实施中（用户 2026-11-23 拍板「按推荐执行」= D1 选 a 结构从源头不丢、D2 切分预览默认显示） ｜ 依据：本文"事实"均 2026-11-23 实取代码（路径:行号） ｜ 触发：用户 2026-11-23「把图片相关没做完的能力彻底完成」+「从治本思路解决」+ 确认 chat.html 等老页无人使用
> **实施期修正（subagent 深挖数据流后）**：D1 从「改 `rag_query` 返回类型」修正为「函数体内旁路进请求级 `EvidenceSink`」——前者会被 `ToolResultCompressionMiddleware` 吃掉结构并撞既有测试，后者在压缩链之前导出、跨 task 安全；`rich` 事件走 router 直发而非新增 `StreamEventType` 字面量（避免 SSE 带大 payload + 联邦双轨同步）。详见 §2.2/§2.3。
> 关联：图片摘要生产开关（IMG_SUMMARY_ENABLED + Qwen3-VL-8B，另案已拍板执行）｜ 设计原则：`docs/principles/README.md` P3（单一实现 + 全局装配 + 门禁强制）

## 0. 病根（实取，不是猜）

先厘清**活链路**（用户实际在用的）与**死链路**（遗留），否则会治错地方。

### 0.1 活链路：Vue → agent_server → 共享 Milvus 集合

- Vue `sse.ts:315` 发 `fetch('/query')`（相对路径、同源，vite 代理到 agent_server），**不走 KS 的 `/query`**。
- agent_server `/query`（`query_router.py:29`）经 graph/planner 调 `rag_query`（`subagents/rag.py:25`），它经 `get_document_store()`（`rag/backend.py:98`）检索 **Milvus 集合 `platform_doc_v3_bge_m3`**。
- KS 上传写的是**同一个集合**（`node_import_milvus.py:24` 的 `CHUNKS_COLLECTION`，生产实取 = `platform_doc_v3_bge_m3`；部署硬约束见 `.env.example:232`）。
- ⇒ **带 `![摘要](MinIO URL)` 的切片 content 确实进了 Vue 问答的检索结果**。

### 0.2 死链路：KS 自带 query 体系（无人用，用户已确认）

| 组件 | 消费者 | 状态 |
|---|---|---|
| `/chat.html`、`/import.html` 静态页 | 用户确认无人用 | 死（路由仍在 `main.py:112`，但无活消费者） |
| KS 私有 `SSEEvent.FINAL.image_urls` | 只喂 chat.html（`chat.html:457-517`） | 死 |
| Mongo history 的 `image_urls`（`mongo_history_utils.py:47-48`） | KS `/history` 端点不返回它 | 死（写入但无人读） |
| KS `/query`、`/stream/{session}` | 用户确认 Vue 不走 | 死（federation 的 `/api/v1/retrieve` 是另一条 retrieve 路由，与本链路无关） |

**结论：治本方案完全不需要碰 KS。** 上一版"保住 chat.html"的理由作废——它是遗留调试页，不是架构约束。

### 0.3 富信息到底丢在哪（精确位置）

| 丢失点 | 代码 | 丢的是什么 |
|---|---|---|
| `rag_query` 把证据拍平 | `subagents/rag.py:65-67`：`f"[来源: {c['source']} / {c['heading']}] {c['content']}"` 返回 `list[str]` | `source`/`heading`/`content`/`doc_id` 的**结构化形状**丢了，只剩字符串；图片链接埋在 content 字符串里 |
| 会展 citations 不进 Answer | `venue_schedule_query.py:241-261` `_format_answer` 只写"引用 N 条"；结构化 `SkillResult.citations` 留在 state（`nodes.py`），未映射进平台 Answer | **结构化引用**丢了 |
| 无统一富回答模型 | `shared_schemas/query.py:40-49` `QueryResponse` 无 citations/sources/images；`protocol.py:44` `StreamEventType` 无富回答事件 | 没有"单一契约"可供各端对齐 |

**病根一句话**：agent_server 内部证据管线在 `rag_query` 处把结构化数据拍平成字符串、会展 citations 被降级成计数文本，且 shared-schemas 里**根本没有富回答契约**——于是图片/引用即使检索到了，也在 SSE 出口前被丢弃。前端 `MarkdownText.vue` 零 v-html 不支持图片，只是最后一层表现。

## 1. 目标 / 非目标

**目标（治本）**：建立全平台唯一的富回答契约；让结构化证据（source/heading/doc_id/content）从检索到 SSE **全程不丢失**；用一个 adapter 把 RAG 证据 + 会展 citations + 图片链接归一成 `RichAnswer`；前端只认这一套；用 lint 门禁防第二套定义/再次拍平。

**非目标**：多模态推理（让 LLM 读懂图再答题，能力盘点标 ❌）· 改上传链路 · 改摘要字数（另案）· 清理 KS 死代码（另案登记，见 §6）。

## 2. 治本架构（四层，P3 三件套齐全）

### 2.1 单一真相源：shared-schemas 新增 `rich_answer.py`

全平台唯一定义，KS/agent_server/前端都对齐这一套形状：

```python
class Source(BaseModel):
    type: Literal["knowledge", "table", "api", "web"]
    name: str                      # 文档名 / 表名 / 端点名
    source_doc: str | None = None  # 知识库文档粒度
    as_of: str | None = None

class Citation(BaseModel):
    source: Source
    chunk_id: str | None = None
    heading: str | None = None
    snippet: str | None = None     # 命中证据片段（引用卡片悬浮用）

class ImageRef(BaseModel):
    url: str                       # 必须过白名单（§2.5）
    source_doc: str | None = None
    caption: str | None = None     # Markdown alt 文本（摘要）

class RichAnswer(BaseModel):
    answer: str
    sources: list[Source] = []
    citations: list[Citation] = []
    images: list[ImageRef] = []
```

**兼容**：`QueryResponse`（`query.py:40-49`）增可选字段 `rich: RichAnswer | None`（**刀 1 已落地**）；`rich` SSE 事件走 **router 直发**（`query_router._sse({"type":"rich", ...})`，与 `cache_hit`/`done` 同族），**不新增** `StreamEventType` 字面量、不动 `serialize_stream_event`——这样 SSE 只承载已过滤的小 payload，原始大 chunks 走旁路 sink，且无需 app+联邦双轨同步。旧消费者不读就是 None/忽略，向后兼容；前端 `check-events.mjs` 会从 router 的 `"type": "rich"` 字面量自动派生出新事件并要求前端同步（见 §2.6）。

### 2.2 结构化证据不丢失：请求级 `EvidenceSink` 旁路（实施期修正）

**为什么不是"改 `rag_query` 返回契约"**（subagent 实取推翻）：
- `ToolResultCompressionMiddleware`（`middleware.py:145-149`，opts-in）会把 capability 返回值 `json.dumps` 成字符串、超阈值截断——结构活不到 router；
- `_run_capability`（`deterministic.py:341-344`）对 dict 只取 `result.get("evidence")`，会展 citations 在此被丢；
- 既有测试 `test_subagents.py:101-105` 钉死 `rag_query` 返回字符串，改返回类型会撞断言。

**改法（治本且改动最小）**：新增 `applications/agent_server/evidence_sink.py`——app 层 `ContextVar[EvidenceSink]`，内持 `rag_chunks` / `exhibition_citations` / `exhibition_sources` 三个可变 list：
- `query_router._stream()` 入口 `set(sink)`、`finally` `reset(token)`（跨 task 安全：子 task `asyncio.gather` 复制的是**同一 pool 对象引用**，写入改对象内部状态，父 task 可见；刻意规避 Python 3.11「子 task `var.set()` 不回传」语义）；
- `rag_query`（`subagents/rag.py:53-67`）在 `await store.retrieve()` 之后、`list[str]` 拍平之前 `sink.rag_chunks.extend(chunks)`——在压缩链**最内层之前**导出；
- `_exhibition_query`（`capabilities.py:402-407`）在 `resp.json()` 之后把 `citations`/`sources` 追加进池；
- router 在 `async for` 结束后、缓存写与 `done` 之前从 sink 取数喂 adapter。
- **chunk 结构实取**：`{id, source, heading, content, score}`（无 `doc_id`；`document_store.py:374` 请求了 `chunk_id` 但返回 dict 只取 `hit["id"]`）——adapter 以 `id` 作 chunk_id。
- 闸口：sink 只在 `chunks` 非空时写入，降级字符串（`KNOWLEDGE_NO_HIT` 等）不进池，`has_real_evidence` 判据不变。

### 2.3 一等 adapter：唯一转换点

建 `agent_server/rich_answer_adapter.py`（单一实现），职责唯一——把三路输入归一成 `RichAnswer`：

```
sink.rag_chunks          ─┐
sink.exhibition_citations─┼─→ to_rich_answer(...) → RichAnswer ─→ router 直发一个 "rich" 事件
图片: 解析 chunk.content 里的 ![alt](url) ─┘
```

- 图片来源：从 `chunk.content` 正则提取 `![](url)`（就是导入时写回的 MinIO 链接），带 `source_doc`/`caption`。
- 引用来源：RAG `chunks` → `Citation{source:{type:"knowledge",name:source_doc},chunk_id,heading,snippet}`；会展 `SkillResult.sources/citations` 经 `envelope.py` 的 `to_rich()` 映射到同一模型（会展应用层 import shared-schemas，依赖方向合法）。
- `query_router.py` 的流式循环（:353-362）在拿到 `answer` 后调 adapter 生成一个 `rich` 事件并 `yield`——**router 不再自己拼任何图片/引用逻辑**。
- 前端 `StreamSnapshot` 增 `rich`，只渲染 `rich.images` / `rich.citations`。

### 2.4 citation 归一（消除三套形状）

- 会展 `envelope.py:56-69` 的 `Source`/`Citation` 改为 import shared-schemas 同名模型（或保留但提供 `to_rich()`）——由 adapter 统一消费。
- 平台 RAG 的 `{source,heading,content,doc_id}` 在 adapter 里统一映射。
- 前端只认 `RichAnswer.citations`，不再有"会展/RAG"分支。

### 2.5 安全（强制，非可选）

- `ImageRef.url` 白名单：adapter 构造时用 `is_allowed_image_url()`（只允许 KS MinIO 域 + 配置可信域，拒 `javascript:`/`data:`/任意外域）；**前端渲染二次校验**（双保险，符合"服务端断言"纪律）。
- `<img>` 走 Vue `:src` + `referrerpolicy="no-referrer"` + `loading="lazy"`，**零 v-html 不变**（`MarkdownText.vue` 的 XSS 纪律保留）。
- 门禁不变量："`ImageRef` 只能由白名单函数构造" + 治理用例（遵守 `evidence-format.md §4` 非空转反证：合成违规能咬、真面参与判决）。

### 2.6 前端（只认一套）

- `api/sse.ts`：`StreamSnapshot` 增 `rich: RichAnswer | null`；handler 表（:169-239）加 `"rich"` 分支。
- `CitationList.vue`（新）：可点来源卡片；`ImageStrip.vue`（新）：白名单校验后的缩略图。
- `KbUpload.vue`：把切分预览 `previews`（数据已在 `kb.ts:99-113`、当前无消费）渲染成缩略图（**D2 默认显示**）。

## 3. 影响面

| 层 | 文件 |
|---|---|
| 契约（单一真相源） | `shared_schemas/rich_answer.py`（新）、`query.py`（+rich 可选字段） |
| 结构化证据 | `agent_server/evidence_sink.py`（新，ContextVar sink）、`subagents/rag.py`（旁路写 chunks）、`capabilities.py`（旁路写会展 citations） |
| adapter（单一实现） | `agent_server/rich_answer_adapter.py`（新）、`api/query_router.py`（set/reset sink + 调 adapter + 直发 rich） |
| citation 归一 | 会展 `contract/envelope.py`（`to_rich()` 映射）；不修改会展 HTTP 契约 |
| StreamEvent | 不改 `agent_runtime/planner/protocol.py`；`rich` 是 router 直发事件 |
| 前端 | `sse.ts`、`CitationList.vue`/`ImageStrip.vue`（新）、`KbUpload.vue`、`styles/` |
| 安全门禁 | `scripts/lint_architecture.py` + `tests/governance/test_image_url_allowlist.py`（新） |
| 测试 | shared-schemas 契约、adapter 转换、前端行为、CI 全量 |

## 4. 验收标准

1. **契约唯一**：全仓只有 shared-schemas 定义 Source/Citation/ImageRef/RichAnswer（grep 可证无第二套定义）。
2. **结构不丢**：`rag_query` 在拍平前把 `chunks` 旁路进 sink；门禁保证"retrieve 后有旁路写入"这一形状不被删（真面参与判决）。
3. **单一转换**：KS（无改动）/ RAG / 会展三路输入 → RichAnswer 只在 adapter 一处；lint 钉住 router 不自己拼。
4. **功能**：带图文档上传→切分预览有缩略图；问答命中→回答区有图片 + 可点引用卡片；会展 skill 回答也有引用。
5. **安全反证**：`javascript:`/外域 URL 被服务端 adapter + 前端双拒；门禁变异表证明规则能咬（非空转）。
6. **兼容**：联邦/kefu/nl2sql 不读 rich 仍正常；KS 老页（无人用）不受影响（本方案根本不碰 KS）。
7. **门禁**：`make ci`（10 session）+ web 全门禁 + doc-sync 绿，读数绑 HEAD。
8. **生产 E2E**（DEPLOY，另案）：开摘要后真环境重传带图文档，标题变语义摘要、问答回显图片与引用。

## 5. 拍板结果（已定，2026-11-23）

- **D1（已拍板选 a）**：结构化证据从源头不丢。**实施期按 subagent 深挖修正**：选 a 的"结构不丢"目标不变，但实现从「改 `rag_query` 返回 `EvidenceBundle`」改为「函数体内旁路进请求级 `EvidenceSink`」——后者同样从源头不丢，且不被压缩中间件吃掉、不撞既有字符串断言、跨 task 安全（见 §2.2）。
- **D2（跟随推荐）**：切分预览图片默认显示。

## 6. 另案登记（本方案不做，避免 PR 膨胀）

- **KS 死代码清理**：`chat.html`/`import.html` + 私有 SSE image_urls 提取 + Mongo image_urls 写入，既然无人用，可另立清理 PR（含移除免鉴权 `/stream/` 的 IDOR 面——见 `agent-harness-capability-map.md` 审计条目）。本方案不碰 KS，保持 PR 聚焦。
- **图片摘要字数**：另案（用户已选 A：50 字软约束不动）。

## 7. 刀次（每 PR <400 行）

1. 刀 1（✅ 已交）：契约 `rich_answer.py` + `QueryResponse.rich` + 包导出 + 安全白名单函数与反证测试（55 passed）。
2. 刀 2（实施中）：`evidence_sink.py` + `rag_query` 旁路写入 + `_exhibition_query` 旁路写入 + router set/reset + sink 单测。
3. 刀 3：`rich_answer_adapter.py` 单一实现 + router 调 adapter 直发 `"rich"` 事件 + 安全门禁（`lint_architecture.py` 不变量 + 反证）。
4. 刀 4：前端 4 处事件面同步（events.ts 联合+图例 / sse.ts handler+snapshot / icons.ts / events.css）+ `CitationList`/`ImageStrip` + `KbUpload` 切分预览缩略图 + 前端白名单二次校验。
5. 刀 5：CI 全量（10 session + web 门禁 + doc-sync）+ 文档回写；生产部署与图片摘要开关同批（另案 DEPLOY）。

## 8. 相对上一版的修正

| 项 | 上一版（错/不够） | 本版（修正） |
|---|---|---|
| 病根 | "两套 SSE 跨服务契约冲突" | "agent_server 内部证据被拍平 + shared-schemas 无富回答契约"；KS 那套是死代码，不构成跨服务冲突 |
| adapter 位置决策 | 纠结 a/b、理由是"保住 chat.html" | 无此纠结——不碰 KS；理由变为"改动面小、结构从源头不丢" |
| 图片来源 | KS FINAL.image_urls（死） | 从 RAG `chunk.content` 里的 `![](url)` 提取（活链路） |
| SSE 事件 | 加 images/citations 两个 | router 直发一个 `"rich"`（不改 Literal/serialize，避免双轨同步 + 大 payload） |
| evidence 处理 | 未触及 | 核心改动：`EvidenceSink` 旁路让结构从源头不丢（治本关键点）；实施期从"改返回类型"修正为"函数内旁路"，规避压缩中间件与既有断言 |
