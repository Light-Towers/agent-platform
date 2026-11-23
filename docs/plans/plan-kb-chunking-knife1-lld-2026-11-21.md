# 刀 1 施工清单（LLD）：切分配置模型 + KS resolver + 校验 + 幂等清理改造

> 状态：✅ 已施工（2026-11-21，HEAD=0f3a26b0 工作区未提交；KS 单测 500 passed/7 skipped，lint/图边界/doc-sync rc=0，详 §6 读数） ｜ 依据：主方案 `docs/plans/plan-kb-chunking-profile-2026-11-20.md` §9 刀 1 ｜ 回写：提交后复取 §6 读数（绑新 HEAD）；R-4 结论见 §6

## 0. 本刀范围与边界

**做**（对应主方案 §9 刀 1 行）：
1. `chunk_config` 配置模型（库级，存 Mongo）+ KS resolver（含未传参时服务端读库配置兜底）
2. 切分参数的范围 + 交叉校验（默认值已定 `title/2000/10%`，块大小范围 500–2000 已定）
3. `ImportGraphState` 增 3 个切分字段 + 清理 2 个死字段
4. 幂等清理改造：`item_name` 粒度 → `(tenant_id, knowledge_id, source_doc)` 粒度，含转义、轻量只读、空 source_doc fail-safe、存量盘点
5. 清死字段（F-10）

**不做**（属刀 2/3/4）：
- 三种 `split_strategy` 的具体切分实现（刀 2）——本刀只把参数接到 state，分派逻辑刀 2 补
- `_split_long_section:175` 的 overlap 写死 0 改读配置（刀 2）
- 平台代理 Form 透传字段的新增（刀 2）；本刀先在 KS 侧把能力备好
- 前端 UI、golden 重标、config_hash（刀 3/4）

**本刀验收**：缺省回落旧行为（默认策略 `title`、块大小 2000；重叠 0→10% 是已拍板变更非回归）；单测覆盖幂等/特殊字符/空 source_doc/交叉校验；R-4 缓解方案评审有结论。

**PR 切法**：本刀内容偏多，建议拆 2 个 PR（均 <400 行）：
- PR-1a：配置模型 + resolver + 校验 + state 字段（§1–§3）
- PR-1b：幂等清理改造（§4）

## 1. chunk_config 配置模型与存储（KS 侧）

### 1.1 数据形状

```python
chunk_config = {
    "split_strategy": "title",        # title | char | line（本刀只存/校，分派在刀 2）
    "max_content_length": 2000,       # 整数 500–2000
    "chunk_overlap_ratio": 0.10,      # 比例 0.0–0.5；存比例，不存字符数（字符数由块大小动态算）
}
```

落点：`kb_collections` 集合的每条库记录增加 `chunk_config` 子文档。Mongo 无 schema，**免迁移**（无 `chunk_config` 的存量库按全局默认处理）。

### 1.2 改 `kb_collections.py`（`applications/knowledge-service/knowledge_service/utils/kb_collections.py`）

新增两个函数，风格对齐现有 `rename_collection`（:131-147，注入 `collection` 缝、PyMongoError 只 WARNING 不抛）：

- `get_chunk_config(tenant_id, knowledge_id, collection=None) -> dict | None`
  - 调 `_get_collection().find_one({"tenant_id": tid, "knowledge_id": kid, "status": _ST_ACTIVE}, {"chunk_config": 1, "_id": 0})`
  - 返回 `doc.get("chunk_config")` 或 None
- `update_chunk_config(tenant_id, knowledge_id, chunk_config, collection=None) -> bool`
  - `update_one({"tenant_id": tid, "knowledge_id": kid, "status": _ST_ACTIVE}, {"$set": {"chunk_config": cfg, "updated_at": _now_iso()}})`
  - 返回 `matched_count > 0`

`create_collection`（:97-128）与 `ensure_collection`（:51）**不改**（建库时无配置即全局默认；配置设置走独立接口，接口端点刀 2 补）。

### 1.3 测试（`tests/unit/test_kb_collections.py`，现有 50 行 `_FakeCollection` 缝可复用）

补 3 例：① 无配置库返回 None；② get 只读 active 行（deleted 不返回）；③ update 命中写 `chunk_config` + `updated_at`、未命中返回 False、Mongo 失败不抛。

## 2. 参数校验（纯函数，独立可测）

新增模块 `applications/knowledge-service/knowledge_service/utils/chunk_config_utils.py`（新建，纯函数、零外部依赖）：

```python
DEFAULT_CHUNK_CONFIG = {"split_strategy": "title", "max_content_length": 2000, "chunk_overlap_ratio": 0.10}
VALID_STRATEGIES = {"title", "char", "line"}
MAX_MIN = 500   # 对应 node_document_split.py:23 MIN_CONTENT_LENGTH
MAX_MAX = 2000  # 用户拍板上限

def normalize_chunk_config(raw: dict | None) -> dict:
    """缺省补全 + 逐字段校验 + 交叉校验。非法抛 ValueError（带具名原因）。"""
```

校验规则（对应主方案 §3.1 F-2，缺省一律走 `DEFAULT_CHUNK_CONFIG`）：
1. `split_strategy` ∈ {title, char, line}，否则 ValueError
2. `max_content_length` 为 int 且 500 ≤ x ≤ 2000，否则 ValueError
3. `chunk_overlap_ratio` 为数值且 0 ≤ x ≤ 0.5（范围上限 P-2 取证后可收紧），否则 ValueError
4. 交叉：`round(max_content_length × ratio) < max_content_length`（即 ratio < 1.0，当前范围天然满足；保留断言防未来放宽）

**测试**（新建 `tests/unit/test_chunk_config_utils.py`）：缺省补全、三字段各自非法值被拒、边界值 500/2000 通过、ratio 0/0.5 通过。

## 3. ImportGraphState 字段 + /upload 透传 + resolver

### 3.1 state 字段（`import_process/agent/state.py`）

**关键约束（已核实）**：`main_graph.py:33` 用 `StateGraph(ImportGraphState)`，而 LangGraph 对 schema 未声明的键**静默丢弃**（见 `tests/unit/test_graph_state_boundary.py` 头注）。⇒ 3 个字段必须进 schema，否则 resolver 算出的值在图边界消失。

- `ImportGraphState`（:7-61）在"切块相关"区补：`split_strategy: str`、`max_content_length: int`、`chunk_overlap: int`（**注意：state 存字符数 overlap，由 ratio×max 算出**，与 chunk_config 存比例不同）
- `graph_default_state`（:66-101）补默认：`"split_strategy": "title"`、`"max_content_length": 2000`、`"chunk_overlap": 200`
- **清死字段（F-10）**：删 `is_normal_split_enabled`、`is_advanced_split_enabled`（:21/:23 声明 + :70/:72 默认值）——全仓 grep 仅此 4 处、无消费点。保留 `is_silicon_flow_api_enabled`、`is_vllm_enabled`（未证实为死字段，本刀不动）。

### 3.2 `/upload` 增 Form 字段（`api/import_router.py`）

- 函数签名（:203-221）增三个可选 Form（**空默认值 = 未显式传**，触发兜底）：
  - `split_strategy: str = Form("")`
  - `max_content_length: int = Form(0)`（0 = 未传）
  - `chunk_overlap_ratio: str = Form("")`（空 = 未传；用 str 便于区分"未传"与"传 0"）
- metadata dict（:244-259）增这三个键。
- 白名单（:148-167 run_graph_task 注入）增三键——**否则进不了 state**。
- **resolver（F-7 服务端兜底）**：在 metadata 聚合处（:243 附近）判定——若三参数均为"未传"，调 §1.2 的 `get_chunk_config(tenant_id, knowledge_id)` 取库配置；仍无则 `normalize_chunk_config(None)` 取全局默认。把结果（比例→字符数 `round(max×ratio)`）写入 metadata 的三个键。显式传参优先：部分传参时，未传的字段用库配置/默认补全。
- **非法值 400**：`normalize_chunk_config` 抛 ValueError → 转 HTTP 400（带具名原因），在文件保存/MinIO 之前拦下（与 :237 knowledge_id 校验同期）。

**测试**（新建 `tests/unit/test_upload_chunk_config.py`，参照 `test_upload_requires_knowledge_id.py` 的直接调 `upload_files` 风格）：显式传参优先、未传走库配置兜底、库也无配置走全局默认、非法值 400、比例换算成字符数正确。

**reimport 不改**：`/reimport` 复用原文重跑，状态逻辑独立（import_router.py:423+），本刀不注入 chunk_config。

## 4. 幂等清理改造（PR-1b）

### 4.1 现状（已核实）

- `node_import_milvus.py:93-94`：入库流程 step_3 调 `step_3_clean_old_data(client, chunks_json_data)`（:267-301），按 `item_name` 删旧；NER 关闭时切片无 item_name → :292-294 跳过 → 重传堆积。
- `kb_delete.py`：`read_chunks`（:34-45）、`_delete_chunks`（:63-75）按 `(tenant_id, knowledge_id[, source_doc])` 删，是 f-string 直接拼接**无转义**（:39-41/:71-73）。
- `escape_milvus_string`（`utils/escape_milvus_string_utils.py:2-24`）是正确的转义工具（反斜杠/双引号/换行），`node_import_milvus.py:330` 有正确用法先例。
- `source_doc` 来自 `node_entry.py:57` 的 `file_title`（文件名去后缀），入库时 setdefault（`node_import_milvus.py:368-371`）。

### 4.2 改造内容

新增轻量幂等函数（放 `kb_delete.py`，或 `node_import_milvus.py` 内联私有函数），签名：

```python
def clear_chunks_for_reupload(client, collection, tenant_id, knowledge_id, source_doc) -> int:
    """按 (tenant, kid, source_doc) 删旧切片；转义、只读 chunk_id、空 source_doc 失败保护。"""
```

要点（逐条对应主方案 §3.4 的 F-1/F-9/F-11/F-13）：
1. **转义**：`source_doc`/`tenant_id`/`knowledge_id` 全部过 `escape_milvus_string` 再拼 filter（F-1）
2. **轻量只读（F-9）**：`client.query(..., filter=expr, output_fields=["chunk_id"], limit=...)`——不读 `_READ_FIELDS` 里的向量；拿到 id 后用 `client.delete(filter=same_expr)` 或按 id 删
3. **空 source_doc fail-safe（F-11）**：`source_doc` 为空/纯空白时**不删**、WARNING 告警、返回 0（绝不执行 `source_doc == ""` 的删除，否则误删全库空 source_doc 切片）
4. **顺带修复跨租户删除（F-13）**：filter 必须含 tenant_id + knowledge_id 谓词（现有 `_clear_chunks_by_item_name:331` 只有 item_name，跨租户误删）

替换 `node_import_milvus.py:94` 的 `step_3_clean_old_data` 调用：从 state 取 `knowledge_id`/`tenant_id`/`source_doc`（= state["file_title"]，见 :57/:370），调新函数；保留 `step_3_clean_old_data` 函数体不删（其他调用点/测试可能引用，本刀只改调用点）。

**存量盘点（F-11）**：本刀附一条一次性只读盘点脚本/runbook——统计生产集合里 `source_doc == ""` 的切片数与分布（按 knowledge_id），供上线前判断 fail-safe 的影响面。脚本可临时（本机/一次性），但盘点结论须登记进主方案 §8。

### 4.3 测试（新建 `tests/unit/test_reupload_idempotency.py`）

fake Milvus client（注入缝）钉 4 例：① 同名重传删旧（filter 含 tenant+kid+source_doc）；② 文件名含 `"` 与 `\` → filter 已转义、不抛；③ 空 source_doc → 不删 + 告警 + 返回 0；④ 只读 output_fields 含且仅含 chunk_id（不含向量）。

## 5. R-4 评审结论（本刀必须产出）

主方案 §8 R-4（删旧→插新非原子、同名并发）要求刀 1 评审时定缓解方向。本刀产出结论（写入主方案 §8 R-4 行）：
- 选项 A：按 `(tenant_id, knowledge_id)` 串行化上传任务（改调度，代价中）
- 选项 B：先插新后删旧、按 `created_at`/批次标记区分（改幂等顺序，代价中）
- 本刀建议先登记、不实现；评审选定后作为后续刀的工作量。**评审结论须落文档，不得悬空**。

## 6. 验证（本刀收尾，按 evidence-format.md §1 五字段记录）

| 项 | 命令 | 期望 |
|---|---|---|
| lint | `uv run --with ruff ruff check .` | rc=0 |
| 架构门禁 | `uv run python scripts/lint_graph_state_boundary.py` | rc=0（3 字段已进 schema） |
| doc-sync | `uv run python scripts/check_doc_sync.py` | rc=0 |
| 单测 | `uv run pytest applications/knowledge-service/tests/unit -q` | 全绿 |
| 既有测试不回退 | 同上全量 | `test_upload_import_immediately.py`、`test_graph_state_boundary.py`、`test_kb_collections.py` 均过 |

### 施工读数（2026-11-21，HEAD=`0f3a26b0`，工作区未提交）

按 evidence-format §1 五字段记录（rev / 命令 / 读数+分母 / 未跑 / 前置）：

- **rev**：`0f3a26b0`（读数取自未提交工作区；提交后须复取，AGENTS.md 观测面硬规矩 #6/#9）。
- **lint**：`uv run --with ruff ruff check .` → rc=0，stdout `All checks passed!`（分母 = 全仓）。
- **架构门禁**：`uv run python scripts/lint_graph_state_boundary.py` → rc=0，违规 0 项（StateGraph 宿主 9 张 / 注册点 63 处 / 图入参面 9 处 / 已知盲区 3 处）——3 个切分字段已进 `ImportGraphState`，图边界不丢。
- **doc-sync**：`uv run python scripts/check_doc_sync.py` → rc=0，0 警告。
- **新增单测**：`uv run pytest test_chunk_config_utils.py test_reupload_idempotency.py test_upload_chunk_config.py -q` → **25 passed**（分母 25）。
- **全量 KS 单测**：`uv run pytest applications/knowledge-service/tests/unit -q` → **500 passed, 7 skipped**（分母 507；无回退）。
- **既有不回退定向**：`test_kb_collections.py` + `test_graph_state_boundary.py` + `test_upload_import_immediately.py` + `test_graph_state_boundary_gate.py` → **33 passed**；`test_kb_collections.py` 单独 **12 passed**（+3 配置用例）。
- **未跑**：KS 集成测试（`ZHIKU_INTEGRATION=1` 重 LangGraph，按 conftest 守卫设计跳过）；golden 自检（刀 4）；真 Milvus/Mongo 端到端（需 126 环境）。
- **前置**：本刀代码 + 测试；无外部服务依赖（全 fake client / monkeypatch）。
- **Windows 注意**：PowerShell 下 pytest 的 `PytestDeprecationWarning`（asyncio_default_fixture_loop_scope）走 stderr，被 `$ErrorActionPreference` 报成 shell `Exit code 1`——**判据是 pytest 自己的 `passed` 行，不是 shell rc**（AGENTS.md 观测面硬规矩 #7），已设 `$ErrorActionPreference='Continue'` 消除干扰。

### 刀 1 review 修复（2026-11-21，HEAD=0f3a26b0）

对刀 1 改动做代码 review 后修复 4 项（读数已含在上节）：

- **M1（中）保留 REVOKED 历史**：~~`clear_chunks_for_reupload` 的 filter 增 `status != "REVOKED"`~~ —— **此项已被第二轮 review 的 H-1 推翻并撤销**，见下方「第二轮 review 修复」。原因：保留 REVOKED 旧版会在用户点"恢复"时（`restore_document` 无脑复活全部 REVOKED）导致旧版与新版并存污染检索。当前实现恢复为"重传删全部历史版本（含 REVOKED）"。
- **M2（中）Mongo 快失败**：`kb_collections._get_collection` 的 `MongoClient` 加 `serverSelectionTimeoutMS=3000`——避免 Mongo 不可达时默认 30s 拖慢上传热路径的 `get_chunk_config`（失败本就回落默认，快失败符合意图）。
- **M3（中）接线测试**：`test_reupload_idempotency.py` 新增 `test_node_wires_cleanup_with_state_identity`——patch 掉步骤函数，断言 `node_import_milvus` 确实用 state 的 `tenant_id/knowledge_id/file_title` 调了清理，钉住调用点防"接线被改回"。
- **L1（低）文档准确性**：`kb_delete.py` 模块头注「零 KS 硬依赖」改为「仅依赖轻量 logger / 纯转义工具」（新增了两个轻量 KS 内部 import）。
- **L2（低）死字段保留**：`step_3_clean_old_data` 全仓无外部消费者，但按本 LLD §4 的明确决定"保留函数体不删"，不改代码。

修复后复测：KS 全量单测 **504 passed, 7 skipped**（新增接线测试 1 例），ruff `All checks passed`。

### 第二轮 review 修复（2026-11-21，HEAD=0f3a26b0）——含 H-1 决策反转

第二轮代码审查发现的项，本轮处理：

- **H-1（高，修法 b）重传删全部历史版本**：撤销第一轮 M1 的 `status != "REVOKED"` 过滤，`clear_chunks_for_reupload` 的 filter 恢复为 `(tenant, kid, source_doc)` 三谓词、不带 status。原因：`restore_document`（`kb_delete.py:191-198`）会把该 source_doc **全部** REVOKED 切片无脑复活为 PUBLISHED；若重传只删活跃、保留 REVOKED 旧版，则"下线→重传→再下线→恢复"路径下旧版全为 REVOKED、前置校验挡不住 → 旧版复活与新版并存污染检索。修法 b（重传 = 整体替换含旧下线版）是唯一自洽解；报告推荐的修法 a（restore 前置校验）挡不住"全 REVOKED"场景。补测 `test_reupload_deletes_revoked_old_version_too`（断言 filter 无 status 子句）。
- **M-1（中）写失败假成功**：`/collections` POST 初始配置写失败 → 响应 `chunk_config_applied=false` 且不回显假配置；PATCH 先查库存在（404 只用于不存在/已删），改名/配置写失败分别 503，只回显写成功的字段。补测 2 例。
- **M-2（中）默认值单一真相源**：`state.py` 的三个切分默认值改为从 `chunk_config_utils.DEFAULT_CHUNK_CONFIG` 推导（`overlap_chars(max, ratio)`），不再硬编码 200；`resolve_split_config` 兜底同源。补测更新（缺省 overlap=200）。
- **M-3（中）表格硬上限**：新增 `MAX_TABLE_BLOCK_CHARS=60000`；`line` 策略超长表格不设 `no_split`、落常规字符切分并告警，避免撑爆 embedding/Milvus 产生黑洞块。补测 `test_oversized_table_drops_no_split`。
- **L-1（低）重复剥标题**：抽 `_strip_parent_prefix`，合并判断与实际拼接共用同一清洗结果。
- **L-2（低）line 描述偏差**：docstring 改为如实描述"表格保整 + 其余递归切分"，不再宣称"按行组切"。
- **L-3/L-4（低）测试盲区**：补 overlap 计入合并上限、超长表格、reimport 经白名单继承三参数各 1 例。

复测读数（HEAD=0f3a26b0 工作区未提交）：KS 全量单测 **520 passed, 7 skipped**（第二轮 +6），agent_server **264 passed**，ruff `All checks passed`，图边界/doc-sync rc=0。**仍未跑**：真浏览器截图、真 Milvus/Mongo 端到端、golden 自检。

### R-4 评审结论（本刀必产出，已落定）

- **决定**：本刀**先登记风险、不实现缓解**（维持原建议）。删旧→插新非原子 + 同名并发上传的风险窗口在单用户/低并发下极小；真要根治需改任务调度（选项 A 串行化，代价中）或幂等顺序（选项 B 先插后删+批次标记，代价中），二者都超出刀 1 的"参数打通"定位，且会改变全量上传行为、须独立评审。
- **复审触发**：出现一次实际的数据丢失或重复（主方案 §8 R-4 已登记）。触发后再开专项刀做 A 或 B 的选型与回归。

## 7. 影响面汇总

| 文件 | 改动 |
|---|---|
| `knowledge_service/utils/kb_collections.py` | +get/update_chunk_config |
| `knowledge_service/utils/chunk_config_utils.py`（新） | 默认配置 + 校验纯函数 |
| `knowledge_service/import_process/agent/state.py` | +3 字段、+默认值、-2 死字段 |
| `knowledge_service/api/import_router.py` | +3 Form、metadata、白名单、resolver 兜底、非法值 400 |
| `knowledge_service/utils/kb_delete.py`（或 node_import_milvus.py 内联） | +clear_chunks_for_reupload（转义/轻量/空值保护/租户谓词） |
| `knowledge_service/import_process/agent/nodes/node_import_milvus.py` | :94 调用点改新函数 |
| `tests/unit/test_kb_collections.py` | +3 例 |
| `tests/unit/test_chunk_config_utils.py`（新） | 校验用例 |
| `tests/unit/test_upload_chunk_config.py`（新） | 透传/兜底/400 用例 |
| `tests/unit/test_reupload_idempotency.py`（新） | 幂等 4 例 |
| 主方案 §8 R-4、§9 | 回写评审结论与状态 |
