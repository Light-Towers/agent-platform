# 知识库文档切分参数配置化（切分规则 / 块大小 / 重叠，milvus 单后端）

> 状态：已施工待提交（刀 1/2/3 ✅、刀 4 🟡 环境无关部分完成；2026-11-20 定 P-1/P-4/P-5，2026-11-21 补定 P-5=重新上传幂等覆盖、三种策略首版全量上线、默认值 `title`/2000/10% 与块大小范围 500–2000，经三轮审核修订 F-1~F-19 + M-A~D/L-A~E 全部处置；工作区 32 文件未提交） ｜ 依据：本地 KS 单测 537 passed / agent_server 264 passed / 前端全门禁绿 / 全量回归 9-10 session 绿（§11）；golden 真实重标+基线重取待 126 环境（§11 runbook） ｜ 回写：提交后复取读数绑新 HEAD

## 0. 背景与问题（用户视角）

用户上传文档时，界面上那 12 个"高级选项"没有一个是他真正关心的问题——**"我的文档会被怎么切"**。切分直接决定检索质量上限，但当前切分参数完全硬编码在代码里，用户既看不到也调不了。按用户 2026-11-20 的明确诉求，上传/知识库侧应当像 Dify 那样**直接配置三件事**：按什么规则切分、切块大小是多少、上下重叠多少。

按 `docs/principles/README.md` 纲要（产品功能设计必须站在用户视角）及 P1（修类不修点）、P2（配置与代码分离且可热变更）、P3（全局统一靠机制）、P5（事实先于方案），本方案要解决的是**一整类问题**：切分参数应当外置、可见、可改，而不是散落在代码里的常量。

本方案对应设计文档 `docs/plans/plan-roles-kb-datasource-console-2026-11-11.md` §14.9 K2 登记的**触发条件已出现**（"首次出现按文档类型差异化切分的真实需求"），按该条纪律重新评审，不是自由施工。

### 范围界定（用户 2026-11-20 口径）

- **后端**：以 **milvus 为向量库**，方案只覆盖 KS 的 milvus 链路；**pgvector 暂不维护**（现状保留、不纳入本方案，详见 §1.1）。用户明确"维护双后端成本大"，故不做多后端对齐、不新增 pgvector 适配。
- **上游**：不覆盖外部系统（Confluence/wiki、Jira 等）的批量/增量采集——用户明确"暂不考虑外网知识库接入场景"。本文从"文档已到手（Markdown）"起算。
- **配置形态**：用户**直接填切分参数**（规则/大小/重叠），不引入"模板"中间层，也**不设预设按钮**（用户 2026-11-21 口径：默认值直接填好，用户要改就自己改数字，不必先点一个按钮去套用默认值）。
- **上传页元数据**：上传页那 12 个高级选项对应的 Form 字段全部从界面移除（含 `exhibition_id/venue_id/datasource_type`），仅保留切分设置；不做 general 通用知识库兜底设计。`exhibition_id/venue_id` 恒空导致 PUBLISHED 校验不可用的后果，登记为已知限制 R-3（见 §8）。

### 字段数量的统一口径（F-17 处置）

全文只用一个口径：**界面上 12 个高级选项**（`KbUpload.vue` 高级区可见项）。派生量另注：`KbUploadForm` 接口 13 个字段（多 `knowledgeId`，来自左栏选库、不在高级区）；`FormData` append 14 个键（`api/kb.ts:84-97`，再多 `tenant_id` 空串占位）。三者是同一批字段的不同计数，勿混用。

## 1. 事实基线（实取，非猜测）

### 1.1 后端取舍：milvus 单一链路

平台上传按 `DOC_BACKEND` 分流（`applications/agent_server/api/kb_router.py:81, :106-124`），当前存在两条切分实现：

| 链路 | 入口 | 切分实现 | 当前参数 | 本方案 |
|---|---|---|---|---|
| **milvus（KS 管线）** | `POST /kb/uploads` → KS `/upload` | `applications/knowledge-service/knowledge_service/import_process/agent/nodes/node_document_split.py` | `DEFAULT_MAX_CONTENT_LENGTH=2000`（:21）、`MIN_CONTENT_LENGTH=500`（:23）、`chunk_overlap=0`（:175）；按 Markdown 标题初次切分 → 递归字符二次切分 | ✅ **本方案唯一目标** |
| pgvector（agent_server 本地直写） | `kb_router.py:164` `_local_ingest` | `rag/chunker.py:16` `split_markdown` | 默认 `max_chars=400`、`overlap=60`（:194 无参调用） | ❌ 暂不维护，不改、不测、不对齐 |

**决策依据**：切分逻辑本应与存储无关，两套实现是历史形成的两份独立代码、`DOC_BACKEND` 是部署级单一配置。用户明确以 milvus 为向量库、pgvector 暂不维护 ⇒ **多后端对齐这一整类问题消解**。pgvector 路径保留现状（代码不动），将来若复活再单独立项。

### 1.2 配置存储现状

- 知识库是一等实体：`applications/knowledge-service/knowledge_service/utils/kb_collections.py:117-120` 的 `create_collection` 只写 `tenant_id / knowledge_id / name / owner / status / doc_count / created_at / updated_at`，**无任何配置字段**；唯一键 `(tenant_id, knowledge_id)`（:45）。KS 的 `/collections` CRUD 在 `import_router.py:589`（POST）/`:606`（PATCH），平台代理在 `kb_router.py:428`/`:438`。
- 导入状态 `applications/knowledge-service/knowledge_service/import_process/agent/state.py` **没有切块大小 / 重叠字段**。`node_document_split.py:46-47` 的注释"有则用状态中的配置，无则用全局默认值"**与代码不符**——代码恒取常量。
- 上传请求白名单 `import_router.py:150-167` 只透传既有 metadata key，无切分参数。
- 文档级登记 `upsert_by_upload(..., metadata=metadata)` 已存在（每库一行），但**不用它做单文档配置**（见 §3.1）；重新上传的幂等按 Milvus 切片的 `(tenant_id, knowledge_id, source_doc)` 粒度处理（见 §3.4）。

### 1.3 既有评测机制（开发侧自检要用，不是新造）

- 平台侧：`eval/golden.jsonl`（15 条，问题 + 期望能力 + 关键词），`eval/run_eval.py:88/113` 阈值 0.8，`make eval` 是 CI 门禁。
- 知识库侧：`applications/knowledge-service/eval/golden_queries.jsonl`（56 条，`qid/query/relevant_chunk_ids/grade/tags`），跑 Recall@10 / MRR / nDCG@10（`eval/README.md:26-39`）；`run_eval.py:252-257` 自动归档 badcase，归因类别第一条即"切分劈答案"；`compare_runs.py` 做 baseline vs candidate 逐指标回归门禁。
- **严重前提（F-14）**：`eval/README.md:38-39/:81` 诚实声明——`golden_queries.jsonl` 的 `relevant_chunk_ids` 是**假设性标注**（`c_101` 等构造编号），用它在真实集合上跑 Recall 全 0 属预期。仓库另有 `golden_queries.real.jsonl` + `remap_golden_ids.py`（真实重标工具）。⇒ 自检必须用绑定真实 chunk_id 的 golden，否则 compare_runs 门禁空转。详见 §6。
- 纪律：`eval/README.md:6-7` 明写 golden 为构造/脱敏样例、禁止预填评测结果。本文同样**不预填任何评测读数**。

## 2. 目标 / 非目标

**目标**

1. 用户在知识库上直接配置切分参数——**切分规则、切块大小、重叠**——库内文档上传即继承；不再面对一堆无关元数据字段。
2. 库内确有异质文档要换切法时，直接**重新上传同名文档**即按当前库配置幂等覆盖（§3.4）；改完能看到该文档实际的切分读数（上传后读数，见 §3.3 的 F-6 处置）。
3. 切分参数的每次改动由开发侧用绑定真实 chunk_id 的 golden 测试集做一次自检 + 基线重取（§6），不产生"改完说不清变好还是变差"的账——纯开发内部动作。

**非目标**

- **不改动 pgvector 链路**（`rag/chunker.py`、`_local_ingest`），不做多后端对齐、不新增适配。
- 不覆盖外部系统（Confluence/wiki、Jira 等）的批量/增量采集；本文从"文档已到手（Markdown）"起算。
- 不承诺 OCR / 版面解析的新能力（现有 MinerU 解析链不在本方案范围）。
- **不做无边界输入**：切块大小/重叠是数字输入，但服务端做**范围 + 交叉校验**（见 §3.1），拒绝非法值——这是护栏，不是用预设把用户的选择权收走。
- **golden 测试集不进界面、不由用户维护**：测试集含 `query/context/answer/reference/human.faithfulness/human.correctness` 等字段，需从真实语料自举、标注分级相关性 `grade`、人工判分，由开发/评测侧用 `gen_golden.py`、`make_adjudication_ui.py` 等工具维护。用户既理解不了、也不该维护它。
- 不自动重切存量文档（见 §5 迁移策略）；改用"重新上传同名文档即幂等覆盖"来让老文档应用新配置（P-5 已定，§3.4），不做单文档配置、不做重建按钮。
- 本轮不改动生命周期/ACL/会展字段的**后端语义**；但**上传页的 12 个高级选项字段全部从界面移除**（P-4 已定；后端 Form 契约保留取默认值，不删字段、不改后端代码）。不做 general 通用知识库兜底；`exhibition_id/venue_id` 恒空导致 PUBLISHED 校验不可用，登记为已知限制 R-3。
- **不做上传前切分预览**（F-6 处置）：服务端切分在 KS Python 侧，前端复刻会双实现漂移（违反 P1/P3），新增 `POST /preview` + 代理 + 门禁成本另算。首版用已有的**上传后读数**（`node_document_split.py:331-344` 的 md_lines/chunk_count/first_title/previews，经 task summary 上屏）承担"所见即所发生"；如后续确需上传前预览，另立方案补 dry-run 端点。

## 3. 方案设计

### 3.1 配置项、校验与存储（用户直接填参数）

**三个用户可配置项**（存为一组 `chunk_config` 对象）：

| 配置项 | 字段 | 取值 | 默认值 |
|---|---|---|---|
| 切分规则 | `split_strategy` | `title`（按 Markdown 标题，现状）/ `char`（按字符数递归切分）/ `line`（按行，含表格保整） | `title` |
| 切块大小 | `max_content_length` | 整数，范围 **`500–2000`**（字符，用户 2026-11-21 拍板，参考主流折算值） | **`2000`**（用户 2026-11-21 拍板） |
| 重叠 | `chunk_overlap` | 字符数，UI 按**百分比**输入，服务端换算：`round(max_content_length × ratio)`（如 2000×10%=200）。百分比范围拟 `0–50%`（P-2 取证后回写） | **`10%`**（≈200 字符，用户 2026-11-21 拍板） |

- **默认值变更的影响（必须知情）**：新默认 `title / 2000 / 10%` 与今天的 `2000 / 0` 相比**只有重叠变了**（0→10%）。处置：① 存量库及之后的所有新上传，凡无 `chunk_config` 时均按**新默认** `title / 2000 / 10%` 处理（不只是重传老文档）；② 存量切片**不自动重切**（§5），只有重传才按新默认；③ 三种策略的 golden 基线一律按新默认重取（§6）。因默认值变化本就要做 golden 自检，此项不额外增加工作。
- **重叠的生效范围（更正原 F-19 结论）**：经复核 `node_document_split.py:138-201`，重叠作用于"把一个长文本切成多块"时的相邻块之间——`title` 策略的超长章节二次切分（`_split_long_section:173-178`）就是这种场景，其 `chunk_overlap` 现状写死 0（:175），**刀 2 改为读配置后 `title` 同样有 10% 重叠**。唯一不生效的情况是"章节未超长=单块"（没有相邻块），这不是 `title` 特有。`char`/`line` 同理。⇒ 默认 10% 在三种策略下都生效（前提是确实切出了多块），UI 不必按策略禁用重叠字段（§3.3 已更正）。
- **服务端校验（F-2）**：除逐字段枚举/范围白名单（块大小 500–2000）外，必须加**交叉约束**，否则下限会踩中已知陷阱（以下行号均已核实）：
  1. `chunk_overlap < max_content_length`：百分比换算成字符数后必须 `< max`（10% 天然满足），否则 LangChain `RecursiveCharacterTextSplitter` 在 `langchain_text_splitters/base.py:79-84`（校验 :79、抛错 :84）抛 ValueError；
  2. **`max_content_length > MIN_CONTENT_LENGTH`（现状 500）并不能根治合并越界**：`_merge_short_sections`（`node_document_split.py:204-252`）在 `step_4_refine_chunks:277` 于"切到 max_len 之内"之后执行，合并判据只有 `len < min_length`（:227）与同父标题（:228），**合并时无 max 上限**（:237 直接拼接）。所以两个各 `<min` 的块合并后产物可达约 `2×min−1`，仍会超过 max——例：max=800、min=500，两块各 499 字合并后 ≈1000 > 800。**本方案块大小下限已抬到 500、默认 2000，但 max=500 时 min=500 仍相等、合并照样越界**。"max>min" 只避免"单个块从一开始就超限"，挡不住"合并把两个合规小块撑成大块"。根治要靠**在合并阶段直接加 max 上限截断**（合并前判断 `len(current)+len(next)+2+overlap <= max` 才合并，否则各自成块——**注意把重叠字符计入上限**，因带重叠切出的相邻子块 A 尾 200 字符 = B 头 200 字符，A 触发合并时这段会重复一次），或把 MIN_CONTENT_LENGTH 一并参数化并令其 ≤ max/2；
  3. 长标题兜底：`available_len = max_length - len(prefix) ≤ 0` 时 `_split_long_section` 直接返回原章节（`node_document_split.py:160-164`），下限 500 时长标题仍可能超限——取证时需决定是把 MIN_CONTENT_LENGTH 一并参数化，还是把下限抬到 > 最长可接受标题。
  - P-2 的取证（§8 现值：**默认值与块大小范围 500–2000 已定稿；仅重叠百分比范围与三条交叉约束取证中**）**必须把这三条列为必答取证项**；其中第 2 条的取证书选项为：{合并阶段加 max 上限截断（根治，推荐）／MIN_CONTENT_LENGTH 一并参数化且 ≤ max/2／仅抬下限（不根治，须登记边界）}。取不到就不开放**对应的重叠范围与切分实现**（块大小 500–2000 已定稿，不存在"不开放"）。
- **存储（单一库级配置）**：在 `kb_collections` 文档增加 `chunk_config` 对象字段（Mongo 无 schema，免迁移），存上述三个值。配置只挂在**库级**，存 Mongo，用户改完下次上传即生效（满足 P2 热变更，无需发版）。
- **不做单文档配置覆盖**：`kb_documents` 的主键是 `(tenant_id, knowledge_id)`（每库一行、每次上传 upsert 覆盖，`kb_registry.py:11-12, :94-100`），没有单文档粒度可挂配置；也不新增单文档配置实体。异质文档要换切法，走 §3.4 的"重新上传覆盖"。
- **切片留参数快照（F-12）**：实际生效的 `chunk_config` 写进每个切片的 metadata（复用现成的 `chunk_version` 字段所在结构，`node_import_milvus.py:365-366` 附近的 `_enrich_chunk_metadata`），供事后归因和评测追溯。UI 的切分设置**只在知识库配置页可改**（F-12 配套），上传页只读展示当前库配置——不存在"单次上传临时改动"，与"配置只挂库级"一致。

### 3.2 KS（milvus）链路打通（核心工程改动）

1. `POST /upload` Form 增 `chunk_config_*`（切分规则/大小/重叠三个值，无文档级覆盖对象——单文档覆盖改走 §3.4 重新上传）→ 加入 `import_router.py:150-167` 白名单 → `ImportGraphState` 增 `split_strategy / max_content_length / chunk_overlap` 三字段 → `node_document_split.py:47` 改为从 state 取值（缺省回落现有常量）→ 按 `split_strategy` 分派到对应切分实现。
2. **配置读取路径（P-1，按 F-7 加固）**：前端从已有 `GET /kb/knowledge-bases`（`kb_router.py:350`）拿到库的 `chunk_config`，上传时经 `/kb/uploads` 代理随 Form 带回 KS；服务端做校验（§3.1），**不信任客户端传的值**。此外——**KS `/upload` 在没显式传 `chunk_config_*` 时，服务端读 `kb_collections.chunk_config` 兜底**（显式传参优先，完全兼容已拍板的 P-1 路径）。理由：不这么做时，旧前端、脚本（`import_exhibition_corpus.py` 直接 POST /upload 不带配置）、curl 都会回落全局默认而非库配置，用户"设了没生效"——正是 §5.3 要避免的场景。把"靠前端记得带"变成机制保证（P3）；刀 1 本就做 resolver，顺势扩展即可。
3. **策略首版全量上线**：`title / char / line` 三种切分策略首版全部实现并上线，不做渐进放量。三种策略在交付界面可选之前，各自都要跑 §6 的 golden 自检（显著退化则回头调实现/补用例），自检是**开发侧发版质量检查**，不是用户运行时门禁，也不拦用户随时改配置。默认策略仍是 `title`，与今天一致；但**整组默认 `title / 2000 / 10%` 与今天的 `2000 / 0` 不同——重叠 0→10% 是已拍板的行为变更（§3.1），不是回归**。
4. **接线 ≠ 可用**：默认策略与切块大小与今天一致、重叠默认 10% 为已拍板变更（§3.1，非回归）；三种策略都通过上述自检后才对外可选（AGENTS.md 红线：不把"接线"当"启用"）。用户侧的选/改配置不受此约束。

#### 3.2.1 三种策略的行为规范（F-3 处置）

每种策略都要明确"输入 → 输出 → 边界行为"，不能只写"分派到对应实现"。首版最小规范：

| 策略 | 切法 | 标题上下文 | 短块合并 | 关键边界 |
|---|---|---|---|---|
| `title` | 按 Markdown 1–6 级标题分节，超长章节用递归字符二次切（`node_document_split.py` 现状） | 保留标题前缀、剥重复标题 | 同父标题短块合并（现状） | 二次切分器（`_split_long_section:173-178`）的 `chunk_overlap` 由现状写死 0 **改为读配置**（默认 10%）——超长章节切出的子块之间因此有重叠。未超长章节单块返回（:150-151），无相邻块、无重叠属正常。若带重叠的短块触发合并，产物中重叠字符会重复一次（检索冗余、非错误），合并上限判断须计入 overlap（§3.1 F-2 约束 2） |
| `char` | 忽略标题结构，按 `max_content_length` 用递归分隔符切全文 | 无标题前缀 | 不做父标题合并 | 相邻块按配置的 overlap 重叠 |
| `line` | 按行/结构化单元切；**Markdown 表格整块保留，不按行劈开、表头随块携带** | 初切 section 无标题前缀（M-C 偏离，见下） | 同父标题短块合并 | "表格保整"是显式验收项（表格按行硬切会让数据行脱离表头，检索质量崩塌；与 RAGFlow deepdoc 等一致）。**同样支持 10% 重叠**：仅超长行组经 step_4 二次切分时产生相邻块重叠；表格块作为原子单元内部不切、无块内重叠。**M-C 账面偏离登记（2026-11-22）**：原设计所述"保留所属标题前缀"与"正文行组之间、正文与表格块之间的块间重叠"**未实现**——`step_2_split_by_lines` 的 section title 恒空、初切行组不互相重叠；line 语义已如实化为"表格保整 + 其余交递归字符切"，标题前缀/块间重叠对 line 价值有限，故登记偏离而非补实现（对应刀 2 LLD 偏离登记）。重叠单位仍按 `round(max × ratio)` 字符数 |

#### 3.2.2 选型论证（F-18 处置）

**主流方案对标（官方文档核准，2026-11-21 取数）**

| 方案 | 块大小默认值 | 重叠表达 | 单位 | 出处 |
|---|---|---|---|---|
| AWS Bedrock | 默认分块约 300 token；固定分块可自定 | 固定分块用**重叠百分比**；层级分块用绝对 overlap token | token | AWS Bedrock Knowledge Bases「How content chunking works」官方文档 |
| Dify | 当前英文文档按**字符**；旧文档/中文资料常见 500 token（上限 4000） | 示例 50 字符（绝对值） | 字符/token 两版本并存 | Dify Docs「Configure the Chunk Settings」 |
| LlamaIndex | SentenceSplitter 默认 1024 | 20（约 2%） | token | LlamaIndex 官方 basic strategies 文档 |
| RAGFlow | general 默认 512 token（上限 2048） | — | token | RAGFlow 文档 / GitHub issue #10354 |

- **重叠用百分比 —— 与主流一致**：Bedrock 固定分块就是用 overlap percentage 表达，与本方案 UI 输入 10% 一致；Dify 用绝对字符（50）也是主流之一。两种都成立，本方案选择站得住。
- **上传前预览 —— 本方案偏离主流，需知情**：Dify 官方提供 Preview（上传前预览切分结果），是标配能力；本方案按 F-6 处置**砍掉上传前预览**，只用已有上传后读数。理由（JS 复刻切分算法会双实现漂移、新增 `POST /preview` + 代理 + 门禁成本）成立且已登记"后续另立方案"（§2 非目标），但这是与主流的能力差距，后人不得误以为本方案功能对齐 Dify。
- **表格保整 —— 与主流一致**：Bedrock 对解析出的表格/图片，检索时以整表/整页内容替换命中块返回（≤10000 字符）；RAGFlow 用 deepdoc 做表格结构化。印证 `line` 策略"表格整块保真"方向正确（§3.2.1 已列显式验收项）。
- **为什么字符单位而非 token（偏离主流的取舍，需知情）**：现状常量就是字符（2000/500），沿用可保证存量行为基本不变；中文下字符与 token 的换算偏差需在 UI 标注"字符数，非 token"。主流默认多在 300–1024 token（折中文约 300–1000 字符），**本方案默认 2000 字符（≈1300–2000 token）明显偏大，比 Bedrock 默认（约 300 token）大约 4–6 倍**——这是延续项目现状的取舍，**不是行业标配**，后人不得据此以为 2000 是主流值。改用 token 会改变所有既有基线，不纳入本轮；如后续 golden 自检发现召回/精度问题，可据实测把默认值下调（取证项见 §8 P-2）。
- **为什么不选语义切分（SemanticChunker）**：Bedrock 有此模式，但依赖 embedding/基础模型计算、成本高，且与现有 BGE 向量化链路叠加，收益未验证——本轮否决，非永久排除。
- **为什么不做 parent-child 大小块检索**：Dify（Parent-child 模式）与 Bedrock（Hierarchical）都有此能力；切片已有 `parent_title` 字段具备基础，但属检索侧改造、超出本方案（切分配置）范围——登记为后续可选项，不在本轮。

### 3.3 前端改造

- **知识库设置**：增加"切分设置"区，三个字段直接可填——切分规则（下拉）、切块大小（数字+单位提示）、重叠（数字+单位提示）；显示默认值并标注"留空按默认"。范围提示跟随 P-2 取证结果（§3.1）。
- **重叠字段对所有策略可见（更正原 F-19 结论）**：原审核 F-19 称"title 下 overlap 无意义"，经复核代码（`node_document_split.py:138-201`）该结论不准确——`title` 策略的超长章节二次切分用的就是 `RecursiveCharacterTextSplitter`，其 `chunk_overlap` 现状写死 0（:175），改为读配置后子块之间即有重叠。唯一"无相邻块、重叠不生效"的情况是章节未超长（单块），这不是 `title` 特有。⇒ **三种策略都显示重叠输入**，不做按策略禁用。（重叠参数生效的落点是刀 2 把 `_split_long_section:175` 的写死 0 改为 state 取值。）
- **上传页**：移除 12 个高级选项字段的暴露；后端 `/upload` Form 契约保留、按默认值登记（不删字段、不改后端代码）。`高级选项`区改为"切分设置：当前库配置（规则 X / 大小 Y / 重叠 Z）"，**只读展示**（编辑只在知识库设置页，见 §3.1 的 F-12 配套）。**不做上传前切分预览**（F-6 处置见 §2 非目标）。
- **同名覆盖提示（F-5）**：上传确认时提示"将覆盖同名文档 X"；UI 文案明示"以文件名去后缀为标识（见 `node_entry.py:57` 的 `file_title`）——改名即视为新文档"。版本化命名（如 `手册v2.md`）不会被识别为覆盖，这是既定语义，需在文案里讲清，避免用户误以为会覆盖旧版。
- 上传后"最近一次上传处理"读数（已有）补充实际生效的三个参数与参数快照，做到"所见即所发生"。**2026-11-22 增强（产品决策：不做上传前预览，改为强化已有读数）**：`step_5b_collect_summary` 的 task summary 增 `effective_config`（本次生效的策略/中文标签/块大小/重叠）与 `warnings`（超长表格已按字符切等切分期告警）；`step_2_split_by_lines` 超长表格降级时把告警写入 warnings；前端 `KbTaskStatus.summary` 增这两字段并在读数卡片显示"本次按 X 执行"+ 告警行。三者让"所见即所发生"落地——用户改完配置上传后能直接核对规则是否生效，无需上传前预览（F-6 已砍）。`step_5b_collect_summary` 的 `effective_config`/`warnings` 为必填参数（前后端同批发布、无混跑场景，漏传由 TypeError 暴露）；前端 `?.`/`?? []` 是处理"任务未切分时 summary 为空"的正常态，非版本兼容。

### 3.4 重新上传即覆盖（幂等）——替代"重建切片"与单文档覆盖

用户决策：不做单文档配置覆盖、不做独立的"重建切片"按钮；**文档要换切法或改内容，就直接重新上传同名文档，系统按幂等覆盖旧切片**。这样库级配置改了之后，想让某文档生效，重传它一次即可。

- **幂等键 = `(tenant_id, knowledge_id, source_doc)`**：重新上传同名文档（`source_doc` 来自文件名去后缀，`node_entry.py:57` → `node_import_milvus.py:368-371` 入库时写入），入库前先删除该粒度的旧切片，再插入新切片。
- **重传删全部历史版本（H-1 决策，修法 b）**：清理 filter **不带 status 条件**——连 REVOKED 旧版一起删。原因：`restore_document` 会把该 source_doc 全部 REVOKED 切片无脑复活；若重传保留 REVOKED 旧版，"下线→重传→再下线→恢复"会让旧版复活与新版并存污染检索。重传 = 用新内容整体替换（含旧下线版），与"主动下线未替换"的 REVOKED 保留语义不冲突。（第二轮 review 推翻了曾短暂采用的修法 a：restore 前置校验挡不住"全 REVOKED"场景。）
- **替换现有 `item_name` 幂等清理**：`node_import_milvus.py:94` 的 `step_3_clean_old_data` 按 `item_name` 删旧，NER 关闭时（切片无 item_name）被跳过（:292-294）⇒ 重传堆积。改用 `(tenant_id, knowledge_id, source_doc)` 后不依赖 NER，幂等稳定成立。**顺带修复（F-13）**：现有 `_clear_chunks_by_item_name` 的 filter 只有 `item_name == "xxx"`（`node_import_milvus.py:331`），无租户谓词，会跨租户误删同名商品切片——切到带 tenant/knowledge 的粒度后该隐患一并消除，这是改造的额外收益。
- **转义必须自己保证（F-1，修正原表述）**：`kb_delete.py` 的 `read_chunks`/`_delete_chunks`（:39-41、:71-73）是 **f-string 直接拼接、无转义**，不能照搬。Linux 文件名可含 `"` 与 `\`，含此类字符的文档重传会因 filter 语法错误导致幂等清理抛 ValueError。⇒ 刀 1 接入时**统一走 `escape_milvus_string`**（工具在 `utils/escape_milvus_string_utils.py`，正确用法见 `node_import_milvus.py:330`），并补"文件名含引号/反斜杠重传"单测。原方案写的"带转义的同名 filter"与代码不符，已更正。
- **幂等清理只读主键、不读向量（F-9）**：`kb_delete.py` 的 `_READ_FIELDS` 含 `dense_vector`/`sparse_vector`（:26-31）、limit 16384（:44）——那是为软删除重插读的。幂等清理无需向量，刀 1 新增专用轻量函数：只按转义后的 filter 读 `chunk_id`（或 count）后删除，别整读向量进上传热路径。
- **空 `source_doc` 的 fail-safe（F-11）**：`source_doc` 是 M2 才补的 setdefault（`node_import_milvus.py:368-371`），M2 前存量切片可能为空；`file_title` 为空时逐 chunk 回落 `parent_title` 或空串 ⇒ 同文档切片 source_doc 碎裂。⇒ 刀 1 先做存量 `source_doc` 覆盖率盘点；**`source_doc` 为空时跳过幂等清理并告警**，绝不执行 `source_doc == ""` 的删除（会误删该库所有空 source_doc 切片）。
- **原子性与并发（F-4，登记为已知限制 R-4）**：`step_3` 删旧 → `step_4` 插新非原子（`node_import_milvus.py:94-96`）。插入失败（如向量维度变化）⇒ 旧已删、新未入 ⇒ 数据丢失；同名文档并发上传 ⇒ 删/插交错。任务间无锁。候选缓解方向：按 `(tenant_id, knowledge_id)` 串行化上传任务，或"先插新后删旧、按 created_at/批次标记区分"。刀 1 至少登记 R-4；具体缓解方案在刀 1 评审时定，不本轮拍死。
- **`dense_vector`/`sparse_vector` 随新配置重算**：重传走完整切分→向量化链路，不是旧切片改名。
- **原"重建切片按钮"取消**：不再需要独立端点（也就绕开了 `/reimport` 的生命周期迁移校验问题）。用户视角：改了库配置 → 想更新哪些文档就重传哪些 → 新配置生效、不产生重复切片。

## 4. 影响面

| 层 | 文件 / 位置 | 改动 |
|---|---|---|
| KS 切分 | `node_document_split.py` | state 取参、按 `split_strategy` 分派（首版三种全实现）、保留常量作缺省；`_split_long_section:175` 的 `chunk_overlap` 由写死 0 改为读配置（默认 10%，三种策略通用）；合并阶段加 max 上限截断（根治 F-2 越界，三选一取证后定，§3.1） |
| KS 幂等 | `node_import_milvus.py`、`utils/kb_delete.py`（或新增轻量函数） | 幂等清理由 `item_name` 改为 `(tenant_id, knowledge_id, source_doc)` 粒度；`escape_milvus_string` 转义；只读主键不读向量；空 source_doc fail-safe（§3.4） |
| KS 状态 | `import_process/agent/state.py` | 增 3 个切分字段；顺带清理死字段 `is_normal_split_enabled`/`is_advanced_split_enabled`（F-10，:21/:23/:70/:72 全仓无消费） |
| KS 接口 | `api/import_router.py` | Form 增字段 + 白名单 + 范围/交叉校验（:150-167）；未传参时服务端读库配置兜底（F-7） |
| KS 存储/接口 | `utils/kb_collections.py`、`api/import_router.py` `/collections` | 库级 `chunk_config` 读写（无文档级覆盖实体）。**三处接口现状必须改（F-8，已核实）**：① `GET /collections` 的 items 是字段投影白名单（:575-585），加 `chunk_config` 到 Mongo 不会自动带出，P-1 前端读取会拿空——投影要加字段；② `PATCH /collections` 现只取 name（:606-616），要支持可选 `chunk_config`；③ `POST /collections`（:589）支持可选初始 `chunk_config` |
| 平台代理 | `applications/agent_server/api/kb_router.py` | `/kb/uploads` Form 同名透传（milvus 分支）；pgvector 分支不动 |
| 前端 | `KbUpload.vue`、知识库创建/编辑组件、`api/kb.ts` | 切分设置直接配置（无预设按钮）+ 元数据字段移除 + 同名覆盖提示 + 上传后读数（不做上传前预览） |
| 评测 | `applications/knowledge-service/eval/*`、`eval/*` | golden 绑真实 chunk_id（×3 策略）、config_hash 纳入 chunk_config、基线重取（§6、刀 4） |
| 文档 | 本文、`docs/plans/plan-roles-kb-datasource-console-2026-11-11.md` §14.9 K2 触发状态、`docs/README.md` §3 索引 | 回写 |

**明确不动**：`applications/agent_server/rag/chunker.py`、`kb_router.py:164-216` 的 `_local_ingest`（pgvector 分支）——用户口径"暂不维护"。

**测试影响**：KS 切分单测（按 state 取参、缺省回落、三种策略各自产出、范围+交叉校验拒绝非法值、`title` 超长章节二次切分带配置的重叠——钉住 `_split_long_section:175` 写死 0 已改为读配置）；KS 幂等单测（同名重传删旧插新不堆积、NER 关闭也成立、文件名含引号/反斜杠、空 source_doc 跳过并告警）；`kb_router` 上传契约测试（新 Form 字段、非法值被拒、未传参时服务端兜底）；golden 自检读数（不预填）。**不写** pgvector 对齐测试。

## 5. 迁移策略

1. **存量库**：无 `chunk_config` 时按全局默认（规则 `title` / 2000 / 10%）；无需数据迁移。与今天相比重叠从 0 变 10%——**超长章节重传后切出的子块会带重叠，切片结果与今天不同**（这是预期的新基线）；未超长的单块文档不受影响。存量切片不自动重切（§5.2），只有重传才按新默认。
2. **存量文档**：已入库切片**不自动重切**。配置改了要生效，按 §3.4 重新上传对应文档（幂等覆盖）——无需单文档配置实体。刀 1 先盘点存量 `source_doc` 覆盖率（F-11）。
3. **顺序**：先做配置模型 + KS resolver + 范围/交叉校验 + 幂等清理改造（刀 1）→ 再接 KS 上传链路 + 三种策略实现 + 参数快照写入（刀 2）→ 再上 UI（刀 3，含元数据字段移除、同名覆盖提示）→ 最后 golden 真实重标（×3）+ config_hash 扩展 + 基线重取 + 文档回写（刀 4）。KS 链路未打通前不开放 UI 配置，避免"设了没生效"。
4. **回滚**：把配置改回默认值（或删掉配置字段）即恢复当前行为；字段是增量键，不删除既有字段。

## 6. golden 自检与基线重取（纯开发侧动作，不进界面）

> **定位**：这是开发在**新增/改动切分规则、或参数默认值变化时**跑的离线评测，用于回答"这次切分改动有没有让检索变差"。它**不是**用户功能、**不在界面出现**、**不随上传触发**、**不拦截用户改配置**——用户随时可以改参数，自检失败只意味着开发要回头调参数或补 golden 用例，与用户操作无关。**绝不每上传一次文档跑一次自检。** 测试集本身也**不由用户维护**（见 §2 非目标），它是受控的构造/脱敏样例，由开发侧工具链生成与判分。

1. **数据文件先选对（F-14）**：自检必须用**绑定真实 chunk_id 的 golden**。仓库的 `golden_queries.jsonl` 是假设标注（`c_101` 等，`eval/README.md:81` 明说 Recall 全 0 属预期），**不能直接用于"显著回归非零退出"门禁**。用 `gen_golden.py` / `remap_golden_ids.py` 产出并维护 `golden_queries.real.jsonl`（`eval/README.md:197/:209`）；此为**刀 4 的显式前置工作项**，不是附注。
2. **每种策略各一套标注（F-14）**：切分策略改变 chunk_id ⇒ `relevant_chunk_ids`/`grade` 随策略而变。三种策略（×3）各需一套按真实 chunk_id 重标的 golden（基准量 56 条 × 3）。工作量为刀 4 显式预算，不可一句"重新标注"带过。
3. 指标：用同一套（按策略的）golden 跑 Recall@10 / MRR / nDCG@10；按 `tags` 分桶看差异，不只看总分。
4. `compare_runs.py` 做 baseline vs candidate 逐指标配对比较，**显著回归非零退出**；平台侧 `make eval` 仍须 ≥ 0.8（切分不应影响路由准确率，此项是防串扰）。
5. **config_hash 扩展（F-15）**：现状 `config_hash = retrieval.yaml + rerank.yaml + 集合名`（`eval/README.md:65`），不含运行时 Mongo 里的 `chunk_config` ⇒ 同 hash + 同 HEAD 下不同切分参数的 run 不可区分（与 AGENTS.md 观测面硬规矩 #9 同族）。⇒ 把当前生效的 `chunk_config` 纳入 `config_hash` 输入，或在 run 目录/`metrics.json` 强制记录当次 `chunk_config` 快照；新基线**绑定 HEAD sha + 件名 + config_hash**（含切分参数）登记；跨 rev 引用须重取。
6. 若出现"切分劈答案"类 badcase（`run_eval.py:257` 归因类别），由开发回头调该策略的切分实现或补 golden 用例，重跑评测——全程开发侧，用户侧不感知、不参与。

## 7. 验收标准

- **用户视角**：建库时直接设置切分规则/大小/重叠（合法值不被改写、非法值被明确拒绝）→ 上传文档 → 上传页只读显示当前库配置与实际生效读数；同名覆盖有确认提示；换切法时重新上传同名文档，旧切片被覆盖、不堆积重复；全过程不需要理解任何评测术语。
- **功能**：milvus 链路下三参数正确透传并生效；非法规则/越界/违反交叉约束的值被服务端 400 拒绝；显式参数优先、未传参时服务端读库配置兜底；三处 `/collections` 接口改动（投影/PATCH/POST）生效；无 `chunk_config` 时回落 §3.1 默认 `title / 2000 / 10%`（该默认已过 §6 自检，重叠 0→10% 是已拍板变更、非回归，**不得按旧口径判为回归**）；pgvector 分支保持原状（无回归）。
- **幂等正确性**：同名重传删旧插新不堆积、NER 关闭也成立、文件名含引号/反斜杠可正常覆盖、空 source_doc 跳过并告警；原子性风险 R-4 已登记且有刀 1 评审结论。
- **开发侧质量自检（非用户功能）**：三种策略各有绑定真实 chunk_id 的 golden 且 Recall 非全 0；golden 指标无显著退化；新基线带 rev + 含切分参数的 config_hash；`make eval` ≥ 0.8；不进界面、不拦用户改配置。
- **工程**：ruff / 单测 / 契约测试通过；`scripts/check_doc_sync.py` rc=0；每条改动按 `docs/operations/evidence-format.md` §1 五字段（rev / 命令 / 读数+分母 / 未跑 / 前置）记录，不预填通过数。
- **完成强度**：本方案落地分为"接线完成"与"启用完成"两档——前者仅是参数打通，**不等于**新策略已可对外使用；新策略交付给界面可选之前由开发完成 §6 的自检（AGENTS.md 红线：不把"接线"当"启用"）。用户侧的选/改配置不受此约束。

## 8. 风险与待拍板格

| 编号 | 事项 | 决定 / 处置 | 状态 |
|---|---|---|---|
| P-1 | 配置读取路径 | 前端带 + 服务端范围/交叉校验；**未传参时服务端读库配置兜底**（F-7） | ✅ 已定（2026-11-20 定，2026-11-21 按 F-7 加固） |
| P-2 | 参数默认值与合法范围 | 默认值用户拍板 **`title`/2000/10%**（2026-11-21）；块大小范围 **`500–2000` 字符**（已定）；重叠百分比范围**拟 0–50%，待取证**；三条交叉约束为必答取证项，其中合并越界三选一——**刀 2 已按推荐项"合并阶段加 max 截断"落地**（默认 0=不启用兼容旧行为，主流程传 max_len 启用）。评审若改选其它项，只需调 `step_4_refine_chunks` 调用参数 | 默认值/块大小范围已定；重叠范围仍待取证；合并越界按推荐项实现（刀 2） |
| P-4 | 上传页 12 个元数据字段是否同步清理 | 全部去掉界面暴露；后端 Form 保留取默认值、不删字段、不改后端代码；不做 general 兜底 | ✅ 已定（2026-11-20 用户拍板） |
| P-5 | 存量文档如何应用新配置 | 重新上传同名文档即幂等覆盖（`(tenant_id, knowledge_id, source_doc)`），不做单文档配置、不做重建按钮 | ✅ 已定（2026-11-21 用户决策） |
| 风险 R-1 | 新策略 golden 基线短期不可比 | 先固定现状基线，新策略单独建基线，不混算 | 登记 |
| 风险 R-3 | 上传页移除 `exhibition_id/venue_id` 后恒空 ⇒ PUBLISHED 发布不可用（DRAFT 上传即入库、检索不受影响，见 plan-upload-import-immediately-2026-11-19）。**另含 `datasource_type` 从前端旧默认 `mysql` 变 KS Form 默认空串（2026-11-22 实现审核 M-A）**——全仓 grep 确认该字段无任何下游消费者，空串为通用中立语义、当前无实害，契约测试钉死口径 | 当前接受；PUBLISHED 复审触发 = 首次需要发布；datasource_type 复审触发 = 出现第一个按数据源类型的过滤/关联消费者 | 登记（用户知情同意） |
| 风险 R-4 | 删旧→插新非原子、同名并发上传（F-4） | **刀 1 评审结论（2026-11-21，见刀 1 LLD §6）：先登记、不实现缓解**——并发窗口在低并发下极小；根治需改调度（串行化）或幂等顺序（先插后删+批次），超出刀 1 定位，另立专项。**H-1 修法 b 的新代价（2026-11-22 M-D 审核 L-D）：重传失败中途连 REVOKED 历史版也丢（原 R-4 只覆盖活跃版），"先插后删"缓解可同时救两者**。复审触发 = 出现一次实际数据丢失或重复 | 已评审（2026-11-21，暂不缓解） |

**本轮深度审核（F-1~F-19）处置落点**：

- 开工前必须修：F-1（§3.4 转义，原表述已更正 + 单测）、F-2（§3.1 交叉校验 + P-2 必答取证）、F-6（§2 非目标砍掉上传前预览、降级上传后读数）、F-7（§3.2 服务端读库配置兜底）。
- 刀 2 前补规范：F-3（§3.2.1 三策略行为规范 + 表格保整验收）、F-18（§3.2.2 选型论证）。
- 刀 1 前补取证：F-11（§3.4 存量 source_doc 盘点 + 空值 fail-safe）。
- 刀 4 前补前置：F-14（§6 golden 绑真实 chunk_id ×3）、F-15（§6 config_hash 纳入切分参数）。
- 随刀处理：F-4（R-4）、F-5（§3.3 同名覆盖提示）、F-8（§4 三处接口改动）、F-9（§3.4 轻量幂等清理）、F-12（§3.1 参数快照 + 编辑只在库设置页）、F-13（§3.4 顺带修复跨租户删除）。
- 低优先：F-10（§4 清死字段）、F-16（§3.1 中块大小范围 500–2000 已由用户定稿、重叠百分比范围仍标"拟"，消除与 P-2 的矛盾）、F-17（§0 字段口径统一）、F-19（**已复核推翻**：原结论"title 下 overlap 无意义"不准确，见 §3.1/§3.3——三种策略均显示重叠输入，刀 2 把 `_split_long_section:175` 写死的 0 改为读配置）。

**已消解（不再列为风险/拍板格）**：

- 原"双后端切分语义差异 R-2"随确定 milvus 单后端、pgvector 暂不维护而消解；原"unify 共享切分器 vs 参数对齐"取舍随之不存在。
- 原 P-3（文档级覆盖存模板 ID 还是参数对象）随"直接填参数"方案消解——直接存参数对象即可，无模板概念。

## 9. 刀次拆分（每 PR < 400 行）

| 刀 | 内容 | 验收要点 | 状态 |
|---|---|---|---|
| 1 | 配置模型 + KS resolver（含未传参兜底）+ 范围/交叉校验 + state 字段 + 幂等清理改造（转义、轻量只读、空 source_doc fail-safe、存量盘点）+ 清死字段 | 缺省回落旧行为；单测覆盖（幂等、特殊字符、空 source_doc、交叉校验拒绝）；R-4 评审结论 | ✅ 已施工（2026-11-21，详见刀 1 LLD） |
| 2 | KS 链路打通（Form → proxy → state → node）+ 三种 `split_strategy` 实现（含 `_split_long_section:175` overlap 写死 0 改读配置）+ 合并阶段 max 截断（按 P-2 取证结论）+ 切片参数快照 + 三处 `/collections` 接口改动 | 三参数透传与兜底、非法值拒绝、三种策略各自产出（含表格保整、title 二次切分带 10% 重叠）、合并产物不超 max、接口投影/PATCH/POST 生效 | ✅ 已施工（2026-11-21，详见刀 2 LLD） |
| 3 | UI（知识库切分设置，无预设按钮 + 元数据字段移除 + 同名覆盖提示 + 上传后读数） | 真浏览器渲染确认（P5），不靠 typecheck；无上传前预览 | ✅ 已施工（2026-11-21，详见刀 3 LLD；typecheck/lint/3 门禁/build 绿，真浏览器截图未跑已如实标注） |
| 4 | golden 真实重标（×3 策略）+ config_hash 扩展 + 基线重取 + 文档回写（含 §4 索引） | 新基线带 rev + 含切分参数的 config_hash；Recall 非全 0；状态行回写本文件 | 🟡 部分施工（2026-11-21）：config_hash 扩展 + run 快照已落地并验证（525 passed）；golden 真实重标 ×3 + 基线重取需真 Milvus/126，未跑留部署步骤，详见刀 4 LLD |

## 10. 开工前置

- 拍板格 P-1 / P-4 / P-5 已定案；P-2 默认值 `title`/2000/10%、块大小范围 500–2000 已由用户拍板（2026-11-21），重叠范围与三条交叉约束取证中（**刀 2 前置**）。策略首版三种全量上线。外部采集场景暂不纳入；pgvector 暂不维护。
- **开工门槛（按深度审核报告修订）**：§8 所列"开工前必须修"四项（F-1/F-2/F-6/F-7）已在本文给出处置——F-1 表述已更正、F-2 交叉约束已入 §3.1、F-6 已砍上传前预览、F-7 已加固 P-1。**§10 原"无待拍板项，可按刀次开工"改为：上述四项处置随刀 1 落地后开工；P-2 范围未取证前不开放对应数值范围，F-14/F-15 的 golden 与 config_hash 工作为刀 4 硬前置。**
- 确认 §14.9 K2 触发条件的登记方式（本方案即回写载体）。
- 本文件入版本控制后，`docs/README.md` §3 索引补登一行（本批未改该文件，避免索引快照数字漂移）。

## 11. 交付前全量回归（2026-11-21，HEAD=0f3a26b0 工作区未提交）

按"声称可提交前跑 make test 对齐 CI"纪律，跑 `make test` 等价 10 session（本机无 make，逐条 uv run pytest）：

| session | 结果 |
|---|---|
| root（`-m "not requires_pg"`） | **7 failed**, 1514 passed, 14 skipped, 29 deselected |
| shared-schemas | 31 passed |
| agent-runtime | 922 passed, 2 skipped |
| agent_server | 264 passed |
| agent_federation | 192 passed, 1 skipped |
| kefu-service | 49 passed |
| exhibition-agent | 380 passed, 1 skipped, 11 warnings |
| knowledge-service | 531 passed, 20 skipped |
| nl2sql-service | 235 passed, 8 skipped |
| observability | 18 passed |

**9/10 session 全绿**；root 的 7 failed 经逐条定位，**全部与本次改动无关**（本批未改这些文件，git status 对它们为空）：

- 2 个 governance 门禁（`test_p8_current_tree_has_zero_violations` / `test_p15_current_tree_is_clean_and_really_judged`）：违规点在 `applications/agent_server/api/health_router.py:112`（异常回显）与 `scripts/reimport_kb_to_milvus.py`（P15 登记为必检签发位但文件无签发符号）——均为既有隔离债/门禁与树漂移，非本批引入。
- 5 个 `tests/skill_live_check/*`：live HTTP 测试，`ConnectTimeout` 到内网 `192.168.100.9:80`（无该服务），环境依赖失败，非本批引入。

**结论**：本批 KB 改动自身零回归（KS 531 / agent_server 264 / 前端全门禁绿）；root 失败为既有债与环境限制，按"不修越界、不拿旧债当已验"纪律如实登记，不在本批处理。

## 12. 第三轮实现审核处置（2026-11-22，M-A~D / L-A~E）

逐行实现审核（非规格对照）发现 4 中 + 5 低，全部核实属实并处置：

- **M-A（中）datasource_type 静默变更**：前端砍掉 metadata 提交后，该字段从旧默认 `mysql` 变 KS Form 默认空串。全仓 grep 确认**无下游消费者**，空串为通用中立语义、当前无实害；已登记进 R-3 同段并补契约测试 `test_datasource_type_defaults_empty_after_frontend_removal` 钉死口径（复审触发 = 出现第一个按数据源类型的消费者）。
- **M-B（中）60000 上限算术不自治**：注释原称"BGE-M3 8192 token 留保守余量取 60000 字符"不成立（60000 中文字符约 36000–60000 token）。**改注释不降上限**——60000 对齐的是 Milvus VARCHAR(65535)，降它会破坏"表格保整"拍板语义；embedding 截断如实标注为已知限制、另行评估。
- **M-C（中）line 策略账面偏差**：`step_2_split_by_lines` 的 section title 恒空、"正文与表格块之间重叠"未实现。**登记偏离**：line 语义已如实化为"表格保整 + 其余递归切"（刀 2 LLD §偏离登记），标题前缀/块间重叠对 line 价值有限，但账面不留缺口（主方案 §3.2.1 line 行注记）。
- **M-D（中）快照缺 ratio 键**：`chunk_params` 只写 3 键、刀 2 LLD 要求 4 键。**补齐**：state 加 `chunk_overlap_ratio` 字段 + resolver → metadata → 白名单 → state 全链路；`node_import_milvus` 快照写第 4 键；`run_eval._read_chunk_config_snapshot` 同步读 4 键。契约测试更新。
- **L-A**：`:609` 注释"缺省 title/overlap=0"漂移 → 改"回落 DEFAULT_CHUNK_CONFIG 换算值 title/200"。
- **L-B**：`KnowledgeWorkspace.refreshTree` 与 `KnowledgeBaseSidebar.refresh` 各调一次 `listKnowledgeBases`（refreshAll 同时触发两次）→ Sidebar 经 `@configs` emit 配置索引给父组件，去掉 Workspace 的重复请求。
- **L-C**：前端范围常量 500/2000/0.5 与后端重复 → 加注释指向后端常量，后端 P-2 收紧后以 400 为准。
- **L-D**：R-4 补"H-1 修法 b 后失败中途损失含 REVOKED 历史版，先插后删可同时救两者"。
- **L-E**：`restore_document` 无条件写整库登记 PUBLISHED（HEAD 既有、非本批引入）——H-1 修法 b 已缩小触发面、暂无实害，仅记观察项不阻塞。

复测：KS 单测 **537 passed**（+1 M-A 契约）、agent_server **264 passed**、ruff / 前端全门禁 / doc-sync 全绿。

## 13. 功能增强开关翻默认（2026-11-22，独立于 KB 切分改造）

用户拍板把 4 个功能增强开关默认值翻 True（代码 `config.py` + 根 `.env.example` 同步口径）。**只翻默认值，不涉及身份 enforce 三开关、V3 调度类**（那两类用户未选）。

| 开关 | 翻后默认值 | 真实现状（实测 `Settings()`） |
|---|---|---|
| `guard_enabled` | True | **真生效**：PII 脱敏（手机/邮箱/身份证/银行卡/IP → 占位符）+ injection 关键词拦截（命中短路返回"输入包含不安全内容"）。⚠ 副作用：会展问数用手机号/身份证当查询条件时脱敏会影响 SQL 生成；可用 `GUARD_BLOCK_INJECTION=false` 只告警不拦（agent-core 层 os.getenv，非 Settings 字段、不在 .env.example 登记，env 模板门禁的"补齐段无未知键"约束）。 |
| `rerank_enabled` | True | `rerank_effective=False`（无 `rerank_api_key`）⇒ 开了不生效，get_reranker 返回 None、检索原序。要真生效须给 key（base_url 默认指向外网 SiliconFlow，内网部署须换 endpoint）。 |
| `mcp_enabled` | True | 无 `mcp_servers` ⇒ 不挂任何工具、不报错。要真生效须给 JSON servers 配置。 |
| `otel_enabled` | True | otel_exporter=otlp 但 endpoint 为空 ⇒ 降级 no-op（日志 `status=DEGRADED`）。要真导出须给 `otel_endpoint`（126 的 Langfuse OTLP 可用）。 |

**测试修正**：`test_health_fields.py::test_guard_enabled_tracks_switch` 原以"无 env=off"为前提（默认 False），默认翻 True 后前提失效——改为显式拨 `GUARD_ENABLED=false/true` 两侧值，保持该文件头注"刻意不断言写死值、拨开关必须跟着变"的本意（非放宽断言）。

**关键认知**：只有 guard 是"翻默认值就真生效"；另三个都需部署 env 里的前置（key/servers/endpoint）——**本机翻默认值不影响 126 旧镜像/旧 env**，上线时须运维在部署清单显式注入。复测：agent_server **267 passed**（含 env 模板门禁），KS **537 passed**，ruff 绿。
