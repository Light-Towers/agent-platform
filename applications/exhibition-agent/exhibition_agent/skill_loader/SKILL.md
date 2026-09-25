---
name: exhibition-readonly
description: 当用户需要查询或分析会展招商数据时使用：涵盖项目后端全部只读能力——实体检索与画像（展会/展商/观众/场馆/主办）、概览、业务记录（合同/安全/会议/线索）、场馆五张卡片（辐射/定位/档期/白皮书/推荐）、招商与展会推荐、外部亲和、策略洞察、预测与热度等。也作为 mingyang-warehouse 项目的唯一能力总表（产品 13 个 skill / 48 个 tool 的端点映射）。通过后端只读 GET 端点（基址由环境变量 EXHIBITION_API_BASE_URL 配置）查询，结果须尊重 data_readiness 标注（画像/推荐/预测多为稀疏或合成样本，非满量真实经营数据），不要编造数据。写操作（create/delete lead）可在用户明确要求测试时调用，须遵守 HITL 软删除与 INV-5 红线。
---

# 会展只读查询 Skill（mingyang-warehouse 项目唯一能力总表）

> 版本与变更历史见同目录 **`CHANGELOG.md`**（SKILL.md frontmatter 无 `version` 字段，故单独成文维护）。

一组基于招商会展数仓（`exhibition_ontology` / 168 表）的**只读**查询能力，封装为 HTTP 端点，供你在对话中调用，帮用户查数据、出画像、做推荐与预测。

> 本文件是项目的**唯一**能力总表：产品侧共 **13 个 skill / 48 个 tool**（来源 `ontology/web/backend/tool_catalog.json` v2.1-p1），其只读端点全部列于下方 §端点速查。写操作（2 个 skill）仅作说明，不在本 skill 调用范围。

## 后端地址（需配置，勿写死 IP）

> 基址通过环境变量 **`EXHIBITION_API_BASE_URL`** 提供（例如 `http://localhost:8000/api` 或部署环境内网地址）。**本 skill 内禁止写死 IP/域名**，统一用该变量拼接。

- **Base URL：`{EXHIBITION_API_BASE_URL}`**（FastAPI 后端**根**，连真库 `exhibition_ontology`；实际值与路径由部署环境注入）。**所有端点路径均以 `/api` 开头**，例如 `{EXHIBITION_API_BASE_URL}/api/portrait/exhibition/9`、`{EXHIBITION_API_BASE_URL}/api/leads`。
- 交互文档：`{EXHIBITION_API_BASE_URL}/docs`（即 `{scheme}://{host}:{port}/docs`）
- 完整端点 schema（让 agent 自取）：同上路径的 `/openapi.json`
- 健康检查：`GET {EXHIBITION_API_BASE_URL}/api/health` → `{"status":"ok"}`

> 后端已运行，无需本地启动即可调用。如需本地重启：`cd ontology/web/backend && pip install -r requirements.txt && python main.py`（本地默认监听 0.0.0.0:8000）。

## 调用约定

- 全部为 **GET** 请求（写操作为 POST/DELETE，见 §写操作，本 skill 不调用），base URL 如上
- 用 curl 或 HTTP 工具调用，返回 JSON
- 示例：`GET {EXHIBITION_API_BASE_URL}/api/portrait/exhibition/E2024XXX`

## 能力全景（产品 13 skill 总表）

| # | skill | 域 | readiness | 是否可经本 skill 查询 |
| --- | --- | --- | --- | --- |
| 1 | search_entity | 查询 | PARTIAL | ✅ |
| 2 | get_entity_profile | 查询 | PARTIAL | ✅ |
| 3 | get_overview | 查询 | PARTIAL | ✅ |
| 4 | list_business_records | 查询 | PARTIAL | ✅ |
| 5 | recommend_organizer | 推荐 | SYNTHETIC | ✅（合成，仅链路） |
| 6 | recommend_venue | 推荐 | SYNTHETIC | ✅（合成，仅链路） |
| 7 | recommend_exhibition | 推荐 | SYNTHETIC | ✅（合成，仅链路） |
| 8 | get_external_affinity | 推荐 | PARTIAL | ✅（外部真实，非行为预测） |
| 9 | get_venue_operation | 洞察 | PARTIAL | ✅ |
| 10 | get_strategy_insight | 洞察 | SYNTHETIC | ✅（合成，仅链路） |
| 11 | get_forecast | 洞察 | SYNTHETIC | ✅（合成，仅链路） |
| 12 | create_lead | 执行 | N/A(write) | ✅ 测试用（W1 自动放行） |
| 13 | delete_lead | 执行 | N/A(write) | ✅ 测试用（W3 HITL 软删除） |

> readiness 说明：`PARTIAL`=主数据真实但指标稀疏/样本；`SYNTHETIC`=合成数据，仅验证链路，禁作业务事实交付（INV-3）。端点返回还会带 `is_sample` / `data_readiness` 字段，须如实呈现。

## 端点速查（只读 GET，按 skill 分组）

### 查询域（PARTIAL）
**search_entity**
- `GET /api/portrait/exhibitions?q=&limit=20`
- `GET /api/portrait/exhibitors?q=&limit=20`
- `GET /api/portrait/audiences?q=&limit=20`
- `GET /api/exhibition` / `GET /api/venue` / `GET /api/exhibitor`
- `GET /api/organizer-project-map`
- `GET /api/timeslot/exhibitions`

**get_entity_profile**
- `GET /api/portrait/exhibition/{exhibition_id}`
- `GET /api/portrait/exhibitor/{exhibitor_id}`
- `GET /api/portrait/audience/{audience_id}`
- `GET /api/venue-dimension?venue_id=`
- `GET /api/venue-exhibition-profile?venue_id=`
- `GET /api/venue_party?venue_id=`
- `GET /api/organizer` / `GET /api/audience`

**get_overview**
- `GET /api/overview` / `GET /api/business-overview` / `GET /api/profile`

**list_business_records**
- `GET /api/contract` / `GET /api/safety` / `GET /api/safety_monthly` / `GET /api/meeting` / `GET /api/clue`

**get_external_affinity**（外部真实数据，非行为预测）
- `GET /api/external-affinity-recommend?entity=&entity_type=&industry=&city=&year=&top_k=`

### 推荐域（SYNTHETIC — 合成数据，仅链路实验，禁作业务事实）
- `GET /api/venue-organizer-recommend?venue_id=&top_k=20`（recommend_organizer）
- `GET /api/organizer-venue-recommend?sponsor_id=&top_k=10`（recommend_venue）
- `GET /api/exhibitor-exhibition-recommend?exhibitor_id=&top_k=15`（recommend_exhibition / profile_match）
- `GET /api/exhibitor-exhibition-schedule?exhibitor_id=&top_k=15`（recommend_exhibition / schedule）
- `GET /api/exhibition-cf-recommend?exhibitor_id=&top_k=15`（recommend_exhibition / collaborative）

### 洞察域
**get_venue_operation**（PARTIAL，除 project_fit 为合成）
- `GET /api/venue-audience-radiation`（radiation）
- `GET /api/venue-positioning`（positioning）
- `GET /api/venue-schedule`（schedule；空置率/利用率算不出时返回结构化「待接入」，不得用 0 掩盖）
- `GET /api/venue-cf-recommend?venue_id=&top_k=10`（project_fit，合成）
- `GET /api/venue-whitepaper?venue_id=`（部分合成）

**get_strategy_insight**（SYNTHETIC）
- `GET /api/venue-recruit-strategy?venue_id=&top_k=20`
- `GET /api/organizer-risk-signal?venue_id=&top_k=20`
- `GET /api/organizer-retention?venue_id=&top_k=20`
- `GET /api/venue-retention-risk?venue_id=&top_k=20`

**get_forecast**（SYNTHETIC）
- `GET /api/exhibition-forecast?exhibition_id=`
- `GET /api/venue-forecast?venue_id=`
- `GET /api/timeslot/predictions?exhibition_id=`
- `GET /api/timeslot/macro`
- `GET /api/exhibition-heat`

## 写操作 / 测试用途（create_lead、delete_lead 及其确认桥）

产品侧另有 2 个**执行域 skill**（写操作）。默认不在本 skill 范围；**当用户明确要求"测试"时才可调用**，须严格遵守下方 HITL 与 INV 红线。

### create_lead（W1 自动放行，低危险）
- `POST {EXHIBITION_API_BASE_URL}/api/leads`
- 入参（JSON body）：`sponsor_id`(必填,str)、`lead_date`(默认 today)、`source_readiness`(**必填**, enum `SYNTHETIC`/`REAL_EVENT`，守 INV-3)、`idempotency_key`(可选,重放幂等)、`context`(可选)
- 出参：`lead_id` / `status` / `created_at` / `idempotent` / `created`
- 行为：落独立 SQLite `agent_skill_lab.db`（与分析仓 168 表隔离）；W1 自动放行。
- 测试示例：
  `curl -X POST {EXHIBITION_API_BASE_URL}/api/leads -H 'Content-Type: application/json' -d '{"sponsor_id":"TEST001","source_readiness":"SYNTHETIC","context":"skill 测试"}'`

### delete_lead（W3 强制 HITL，软删除）
- `DELETE {EXHIBITION_API_BASE_URL}/api/leads/{lead_id}`（query 可选 `delete_reason`）
- 行为：DB 置 `pending_delete`（软删除待确认），**不真正删除**（可恢复）；返回 `202`。
- ⚠ **响应标签 bug（已核实 `leads.py:177-184`）**：该端点返回的 `status` 误写为 `"pending_approval"`，但**数据库实际存的是 `pending_delete`**。不要被响应标签误导——它等同于"待删"，下一步 `confirm` 会真正删除。

### confirm_lead / reject_lead（人工确认桥，完成真实状态变更）
- `POST {EXHIBITION_API_BASE_URL}/api/leads/{lead_id}/confirm`（body **必填**但可传 `{}` 或 `{"delete_reason":"..."}`；`LeadConfirmRequest` 仅 `delete_reason` 一个可选字段，无 JSON body 会 422）
  - 语义按 **DB 实际状态** 分支（非响应标签）：DB=`pending_delete` → `deleted`（填 `deleted_at`+`delete_reason`）；DB=`pending_approval`（仅 W1 在 `all` 策略创建时才有）→ `active`。
- `POST {EXHIBITION_API_BASE_URL}/api/leads/{lead_id}/reject`（body 不需要）
  - 语义：DB=`pending_delete` → `active`（软删除恢复）；DB=`pending_approval` → `deleted`（驳回创建）。
- ⚠ 这两个端点**完成真实删除/恢复动作**；**INV-5 红线：不得由 Agent 自主调用，须用户显式确认后才执行**。

### 测试协议（推荐 round-trip）
1. `POST /api/leads` 带 `source_readiness=SYNTHETIC` 创建测试线索 → 拿到 `lead_id`（无 ExecutionContext 时会回退 `mock-user`，但线索行仍落库，仅身份为 mock）。
2. `DELETE /api/leads/{lead_id}` → DB 置 `pending_delete`（响应误标 `pending_approval`，未真正删，可恢复）。
3. 若要验证完整删除，再 `POST /api/leads/{lead_id}/confirm`（body `{}`，**须用户确认**）→ DB 转 `deleted`（填 `deleted_at`）。
4. **落库核验**：`main.py` 未暴露 `GET /api/leads/{id}`，须直接查 SQLite `ontology/data/agent_skill_lab.db` 的 `t_agent_lead`，核对 `status='deleted'` 且 `deleted_at IS NOT NULL`（`leads.get_lead()` 函数可测但无 HTTP 端点）。
5. 测试结束务必清理：`reject` 可把 `pending_delete` 恢复为 active，或 confirm 后彻底删除，避免遗留测试数据。
> 全程用 `SYNTHETIC` 标记，绝不把测试线索伪装成真实事件（INV-3）。

## 平台地基模块（非端点能力，代码位置指针）

以下为后端工程模块（MVP 切片），非用户端点，仅作代码定位参考：
- `datamod/`：`organizer`/`meeting`/`portrait`/`venue`/`external_affinity`/`nl`/`leads` 等数据访问层（真实 168 表，经 `db.py`+`db_config` 双后端）
- F01 `execution_context.py`、F02 `data_egress.py`、F03 `knowledge_lifecycle.py`、F04 `metric_registry.py`(+json)、F05 `evaluation.py`、F06 `production_readiness_gate.py`(+json)、P1 `tool_catalog.json`+`skill_router.py`
- 注意：F01–F06/P1 多为纯逻辑/状态机/数据结构，**未连运行时链路**；identity/security 门 `implemented:false`，属 MVP 切片非生产版。

## 重要边界（务必遵守）

1. **默认只读，测试可写**：本 skill 默认只调 GET 端点。**仅当用户明确要求"测试"时才调用以下写端点**，且须遵守 HITL：
   - `POST /api/leads`（create_lead）：W1 自动放行，低危险；`source_readiness` **必填**（`SYNTHETIC`/`REAL_EVENT`，守 INV-3），落独立 SQLite `agent_skill_lab.db`。
   - `DELETE /api/leads/{lead_id}`（delete_lead）：W3 强制 HITL，DB 置 `pending_delete`（软删除、可恢复），返回 `202` 但响应 `status` 误标 `pending_approval`，**不真正删除**。
   - `POST /api/leads/{lead_id}/confirm`、`POST /api/leads/{lead_id}/reject`：人工确认桥，完成删除/恢复动作；**INV-5：这些不可逆/状态变更动作不得由 Agent 自主执行，须用户显式确认后才调用**。
2. **不编造**：端点返回什么就呈现什么；若返回空或报错，如实告知用户"数据待接入/查询失败"，**不要虚构数据或指标**。
3. **数据来源与可信度（重要）**：后端连 **真库 `exhibition_ontology`（168 表）**，展会主数据（名称/档期/场馆）是真实的；**但画像经营指标（展商/观众数、行业分布、综合价值、达成率、推荐动作）常为稀疏/合成样本，并非满量真实经营数据**（实测：2026华南国际医疗器械展 actual_exhibitor_count=6/预期950、industry_top5=包装工业/半导体/… 与医疗主题偏离）。不要把这些指标表述为确定的经营结论。
4. **`data_readiness` 强制标注（INV-3 红线）**：单展会画像 `/api/portrait/exhibition/{id}` 的返回含 `data_readiness` 字段：
   - `level="sparse_sample"`（稀疏/合成样本）/ `"pending"`（数据待接入）/ `"incomplete"`（部分缺失）→ **必须**在回复中向用户显式标注"该画像为样本/待接入数据，结论仅供参考，禁止据此外推真实经营判断"，且不得把综合价值/达成率/推荐动作当作事实陈述。
   - 仅当 `level="complete"` 时可按完整数据呈现。
   - 推荐/预测类（SYNTHETIC）同理：返回即合成样本，须标注"合成数据，仅供链路演示，非真实经营结论"。
5. **越权隔离未强制**：MVP 切片的路由层未强制多租户隔离。查询默认不隔离租户，生产前需补 F01 ExecutionContext 接入。当前仅供单租户/演示试用。

## 触发场景示例

- "帮我查一下展会 E2024xxx 的画像" → `GET /api/portrait/exhibition/E2024xxx`
- "场馆 V001 的五张卡片" → 依次调 `/api/venue-audience-radiation` 等
- "给这个展商推荐匹配的展会" → `GET /api/exhibitor-exhibition-recommend?exhibitor_id=...`
- "预测下这场展会的火热程度" → `GET /api/exhibition-heat`
- "查一下某主办的风险信号" → `GET /api/organizer-risk-signal?venue_id=...`（注意：SYNTHETIC 合成数据）
- "列一下合同/安全/会议记录" → `GET /api/contract` / `/api/safety` / `/api/meeting`
