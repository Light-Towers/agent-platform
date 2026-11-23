# 刀 2 施工清单（LLD）：三种切分策略 + overlap 生效 + 合并截断 + 快照 + /collections 接口

> 状态：✅ 已施工（2026-11-21，HEAD=0f3a26b0 工作区未提交；KS 单测 514 passed/7 skipped、agent_server 264 passed、lint/图边界/doc-sync rc=0，详 §7 读数） ｜ 依据：主方案 `docs/plans/plan-kb-chunking-profile-2026-11-20.md` §9 刀 2 ｜ 回写：提交后复取 §7 读数（绑新 HEAD）；P-2 三选一若改选见 §7 偏离登记

## 0. 范围与前置

**前置**：刀 1（配置模型 + state 字段 + resolver + 幂等）已合入。本刀的 `state["split_strategy"|"max_content_length"|"chunk_overlap"]` 三键已存在（刀 1 加进 `ImportGraphState`，否则 LangGraph 静默丢弃）。

**做**（主方案 §9 刀 2 行）：
1. 三种 `split_strategy`（title/char/line）切分实现 + 按 state 分派
2. `_split_long_section:175` overlap 写死 0 → 读 state 的 `chunk_overlap`（title 策略二次切分带 10% 重叠）
3. 合并阶段加 max 上限截断（按 P-2 取证结论）
4. 切片参数快照落 `index_registry.chunk_params`（F-12）
5. 平台代理 `/kb/uploads` 增 3 个 Form 字段透传
6. 三处 `/collections` 接口改动（GET 投影 / PATCH / POST）

**不做**：前端 UI（刀 3）、golden 重标 / config_hash（刀 4）、P-2 交叉约束本体的校验（刀 1 已做）。

**P-2 硬前置**：块大小范围/默认已定（500–2000/2000），但**重叠范围与三条交叉约束仍在取证**（主方案 §8 P-2）。其中"合并越界的三选一"（合并阶段 max 截断[推荐]／MIN 参数化 ≤max/2／仅抬下限）**必须先有结论**，本刀 §3 才能定——结论由评审给出，写入主方案 §8 P-2 后再施工。

**验收**：三参数透传与兜底、非法值 400、三种策略各自产出（含表格保整、title 二次切分带 10% 重叠）、合并产物不超 max、三处 /collections 生效。

**PR 切法**：拆 2–3 个 PR（均 <400 行）：
- PR-2a：三策略实现 + overlap 生效 + 合并截断（§1–§3，KS 切分核心）
- PR-2b：平台代理透传（§4）
- PR-2c：/collections 三接口 + 快照（§5–§6）

## 1. 切分策略抽象与分派

### 1.1 现状骨架（`node_document_split.py`，入口 `node_document_split` :436+）

当前流程固化：`step_1_get_inputs`（取 max_len）→ `step_2_split_by_titles`（按标题初切）→ `step_3_handle_no_title`（无标题兜底）→ `step_4_refine_chunks`（二次切 + 合并 + 父标题兜底）→ step_5/5b 统计。

`step_1_get_inputs`（:26-50）当前从 state 取 `md_content`/`file_title`，max_len 恒取 `DEFAULT_MAX_CONTENT_LENGTH`（:47，注释谎称"从 state 取配置"）。刀 1 已把三字段入 state——本刀让 step_1 真正读出来。

### 1.2 改造：step_1 读三参数

`step_1_get_inputs` 改为返回 `(content, file_title, cfg)`，其中 cfg = `{"split_strategy", "max_content_length", "chunk_overlap"}` 从 state 取（刀 1 已保证字段在 schema 且有默认值）。`node_document_split` 主流程相应解包。

### 1.3 分派点：按 `split_strategy` 选择初切策略

在 `step_2`（标题初切）位置分派——三种策略的**差异在"如何把全文切成初始章节/块"**，后续二次切 + 合并 + 兜底可复用（title/line 走完整 refine；char 可跳过短块合并）：

| 策略 | 初切实现 | 复用 refine |
|---|---|---|
| `title` | 现有 `step_2_split_by_titles`（:53-114），不变 | 是（含二次切 overlap + 合并 + 父标题兜底） |
| `char` | 新 `step_2_split_by_chars(content, cfg)`：直接把全文当作一个"无标题章节"，靠 `step_4_refine_chunks` 的递归字符切分器按 max/overlap 切成多块；或直接在初切阶段用 RecursiveCharacterTextSplitter 切全文 | 跳过短块合并（char 不按父标题合并，见主方案 §3.2.1） |
| `line` | 新 `step_2_split_by_lines(content, ...)`：按行/结构化单元切，**Markdown 表格整块保留** | 是 |

新增纯函数 `split_by_strategy(content, file_title, cfg) -> (sections, title_count, lines_count)` 做分派，放在 `node_document_split.py`，主流程调它替代 `step_2 + step_3` 的固定调用。

## 2. 三种策略实现要点

### 2.1 title（现状 + overlap 生效）
- 初切 `step_2_split_by_titles` 不动
- **`_split_long_section:173-178` 改**：`chunk_overlap=0` → `chunk_overlap=state_cfg.chunk_overlap`（刀 1 存的字符数，默认 200）。函数签名加 `overlap: int = 0` 参数，`step_4_refine_chunks` 传入。
- 注意：带 overlap 切出的子块，组装时仍带标题前缀（:188）+ 剥重复标题（:166-169）——overlap 字符会带前缀重复，属预期（主方案 §3.1 F-2 约束 2 注记）。

### 2.2 char（新）
- 新函数用 `RecursiveCharacterTextSplitter(chunk_size=max_content_length, chunk_overlap=chunk_overlap, separators=现有优先级)` 直接切全文 body
- 每块包成 `{"title": f"chunk-{idx}", "content": text, "file_title": file_title}`（无父标题前缀）
- 主流程对 char 跳过 `step_4` 的短块合并阶段（不改 `_merge_short_sections`，只在 char 分支不调用它）

### 2.3 line（新，表格保整）
- 按行扫描，识别 Markdown 表格块（连续以 `|` 开头的行 + 表头分隔行），表格**整块**作为一个 section
- 非表格行按聚合到 max_content_length 成 section
- 表格 section 内部不切、不加 overlap；块之间 overlap 由后续通用逻辑处理（或在 line 分支内按字符数给相邻 section 补重叠——按主方案 §3.2.1，重叠单位按字符数，与另两策略统一）
- **显式验收项**：一张带表头的 Markdown 表格，切分后表头与所有数据行在同一 section（不跨块）

## 3. 合并阶段 max 上限截断（F-2 根治）

`_merge_short_sections`（:204-252）当前合并判据只有 `len < min_length` + 同父标题（:227-230），无 max 上限。按主方案 §3.1 F-2 三选一结论（**待 P-2 评审确认，推荐"合并阶段加 max 截断"**）：

- 给 `_merge_short_sections` 加 `max_length: int` 与 `overlap: int` 参数
- 合并判据增：`len(current.content) + len(next_content) + 2 + overlap <= max_length`（含重叠字符，防带重叠子块合并超限）
- 不满足则各自成块（走现有 :242-245 else 分支）
- **测试钉**：两块各 499 字、max=800、min=500 → 不合并（产物不超 800）——即上一版评审 F-2 举的那个越界场景

## 4. 平台代理透传（agent_server）

`applications/agent_server/api/kb_router.py` 的 `kb_upload`（:81-162）：
- 函数签名增 3 个 Form（与 KS 侧同名同默认）：`split_strategy: str = Form("")`、`max_content_length: int = Form(0)`、`chunk_overlap_ratio: str = Form("")`
- 转发 `data` dict（:134-148）增这 3 键，milvus 分支透传；pgvector 分支 `_local_ingest`（:164-216）**不接**（主方案不维护 pgvector）
- 顶部注释 `:84` 的"13 Form 字段"更新为 16

**测试**（`applications/agent_server/tests/test_kb_router.py`，现有 :175 断言 `url == "http://ks:8900/upload"`）：补一例——上传带三参数时，转发 data 含这三键且值正确。

## 5. 切片参数快照（F-12）—— 不新增 Milvus 字段的关键决策

**核实发现**：Milvus 集合 schema 固定（`node_import_milvus.py:180-193`），集合名版本化为 `{prefix}_{schema_version}_{embedding}`，加字段需升 `schema_version` → 新集合 → 全量重灌（代价极大）。

**决策**：参数快照写进 `index_registry` 的 `chunk_params` 字段——`register_index` 已支持（`index_registry.py:98-127`，`chunk_params` 参数，当前是占位值 `{"max_len": None, "merge_short": True}`，`node_import_milvus.py:447`）。改造：
- `step_5_register_index`（:428-455）调 `register_index` 时，`chunk_params` 传入真实生效的 `{"split_strategy", "max_content_length", "chunk_overlap", "chunk_overlap_ratio"}`
- 函数签名加 state/cfg 参数；`register_index` 本身不改

**已知局限（登记，不隐瞒）**：`index_registry` 是**按集合**登记的，而一个集合里可能有多个 knowledge_id、各自不同 chunk_config ⇒ registry 只能记"本次导入的快照"，不是"每片的配置"。若要"每片可查"，需另立字段（届时才升 schema_version）。本刀先满足"导入批次级归因"，逐片归因登记为后续项。

## 6. /collections 三处接口改动（F-8）

`applications/knowledge-service/knowledge_service/api/import_router.py`：

1. **GET `/collections`（:548-586）**：items（:575-585）是字段白名单，Mongo 加 `chunk_config` 不会自动带出 ⇒ 投影加 `"chunk_config": r.get("chunk_config")` 或规范化后的值。前端 P-1 读取路径依赖此字段。
2. **PATCH `/collections/{id}`（:606-616）**：现仅取 `name` ⇒ 请求体支持可选 `chunk_config`；非空时调刀 1 的 `update_chunk_config`，做范围/交叉校验（复用 `normalize_chunk_config`），非法 400。
3. **POST `/collections`（:589-603）**：请求体支持可选初始 `chunk_config`；有则校验后写入 `create_collection` 结果。

**测试**（`test_kb_collections.py` + 新建 `tests/unit/test_collections_chunk_config.py`）：GET 带出 chunk_config、PATCH 写入/非法 400、POST 初始配置落库。

## 7. 验证（本刀收尾，evidence-format §1 五字段）

| 项 | 命令 | 期望 |
|---|---|---|
| lint | `uv run --with ruff ruff check .` | rc=0 |
| 单测 | `uv run pytest applications/knowledge-service/tests/unit -q` | 全绿 |
| 代理契约 | `uv run pytest applications/agent_server/tests -q` | 全绿（新 Form 透传用例过） |
| 文档 | `uv run python scripts/check_doc_sync.py` | rc=0 |
| golden 自检（本刀只跑不自检基线重取） | 手动评估三种策略产出 | 表格保整、title 带 overlap、合并不越界；正式 golden 重取在刀 4 |

### 施工读数（2026-11-21，HEAD=0f3a26b0，工作区未提交）

按 evidence-format §1 五字段：

- **rev**：`0f3a26b0`（未提交工作区；提交后复取，AGENTS.md 硬规矩 #6/#9）。
- **KS 全量单测**：`uv run pytest applications/knowledge-service/tests/unit -q` → **520 passed, 7 skipped**（刀 1 后 504，刀 2 +10，第二轮 review 修复 +6：M-1 写失败、M-2 默认值、M-3 表格上限、L-3/L-4 测试盲区——详见刀 1 LLD「第二轮 review 修复」；这些修复的落点多在本刀文件 node_document_split.py / import_router.py）。
- **agent_server 全量**：`uv run pytest applications/agent_server/tests -q` → **264 passed**（含新增 chunk 参数透传用例）。
- **lint**：`uv run --with ruff ruff check .` → rc=0，`All checks passed!`。
- **图边界门禁**：`uv run python scripts/lint_graph_state_boundary.py` → rc=0，违规 0。
- **doc-sync**：`uv run python scripts/check_doc_sync.py` → rc=0，0 警告。
- **未跑**：golden 自检 / 基线重取（刀 4）；真 Milvus/Mongo 端到端（126 环境）；KS 集成测试（ZHIKU_INTEGRATION=1）。
- **前置**：刀 1 已合入工作区（resolver + state 三字段 + 幂等清理）。

### 实现与 LLD 的一处偏离（如实登记）

LLD §1.3 原写"新增 `split_by_strategy` 分派函数"——实现时改为在 `node_document_split` 主流程内联 `if strategy == ...` 分派（更直接，少一层函数），并新增 `resolve_split_config(state)` 读策略/overlap。行为等价，影响面相同（仍在主方案 §4 文件清单内）。

另一处：P-2"合并越界三选一"未正式拍板，实现按**推荐项"合并阶段加 max 截断"**落地（`_merge_short_sections` 的 `max_length` 参数，默认 0=不启用以兼容旧行为；主流程传 `max_len` 启用）。若评审改选其它方案，只需调整 `step_4_refine_chunks` 的调用参数，不动切分算法本体。

第三处（M-C，2026-11-22 第三轮审核）：line 策略的"section 标题前缀"与"正文行组之间 / 正文与表格块之间的块间重叠"**未实现**——`step_2_split_by_lines` 的 section title 恒空、初切行组不互相重叠，仅超长行组经 step_4 二次切分才带重叠。line 语义已如实化为"表格保整 + 其余交递归字符切"，对 line 而言标题前缀/块间重叠价值有限，故**登记偏离、不补实现**；主方案 §3.2.1 line 行已同步更正。

## 8. 影响面汇总

| 文件 | 改动 |
|---|---|
| `node_document_split.py` | step_1 读三参数；新增 `split_by_strategy` 分派 + `step_2_split_by_chars` + `step_2_split_by_lines`；`_split_long_section` overlap 读配置；`_merge_short_sections` 加 max/overlap 截断 |
| `node_import_milvus.py` | step_5_register_index 传真实 chunk_params 快照（不新增 Milvus 字段） |
| `agent_server/api/kb_router.py` | /kb/uploads 增 3 Form + 转发；注释字段数 |
| `api/import_router.py` | /collections GET 投影、PATCH、POST 三处改 chunk_config |
| `tests/unit/test_chunk_strategies.py`（新） | 三策略产出、表格保整、title 带 overlap、合并不越界 |
| `tests/unit/test_collections_chunk_config.py`（新） | 三接口 chunk_config |
| `applications/agent_server/tests/test_kb_router.py` | +Form 透传用例 |
| 主方案 §8 P-2、§9 | 回写三选一结论与状态 |
