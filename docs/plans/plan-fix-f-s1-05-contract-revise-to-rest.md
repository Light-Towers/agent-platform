---
updated: 2026-09-21
---

# F-S1-05 修复方案：修订契约 v1.1 → 直接 REST

> **状态**：已敲定，待实施
> **决策来源**：2026-09-21 用户显式决策——否决路径 1（让 warehouse 加 `POST /api/v1/skills/{name}` 适配路由），采路径 2（修订契约本身，exhibition-agent 改直接调 warehouse REST 端点）
> **债务登记**：`docs/analysis/2026-09-21/02-debt-diagnosis.md` F-S1-05（P2，红线 4）

## 1. 目标

将 exhibition-agent 与 mingyang-warehouse 的集成从「契约 v1.1 统一 skill invoke + 信封」改成「直接调 warehouse REST 端点」，使真实 warehouse（48 个 REST 端点已跑在 192.168.100.241:8000）能直接被 exhibition-agent 调通，不再因 warehouse 缺 `POST /api/v1/skills/{name}` 路由而 404。

**修订契约本身，不是豁免 exhibition-agent 偏离架构**：契约 v1.1 的 C2（统一信封 + skill invoke）被替换为 C2'（直接 REST），C1（ExecutionContext）/ C4（trace）/ INV-10（不生成 SQL）保留。

## 2. 当前架构（契约 v1.1）与新架构（契约 v1.2）对比

### 2.1 当前调用链（v1.1）

```
server.py /api/query
  → run_supervisor → build_graph → select_skill → run_skill → emit_trace
  → VenueScheduleQuerySkill.run(params, ctx)
  → ctx.warehouse_client.invoke(skill_name, params, ...)
  → POST /api/v1/skills/{skill}  + 信封 body {request_id, skill, params, options}
  → 解析 SkillSuccessEnvelope {request_id, data, readiness, classification, sources, citations, warnings}
  → mock_server 实现 POST /api/v1/skills/{skill}（9 场景）
```

**问题**：真实 warehouse 无 `POST /api/v1/skills/{name}` 路由，只有 48 个 REST 端点（`GET /api/portrait/...` 等），真实调用 404。mock 掩盖此缺口。

### 2.2 新调用链（v1.2：直接 REST）

```
server.py /api/query
  → run_supervisor → build_graph → select_skill → run_skill → emit_trace
  → VenueScheduleQuerySkill.run(params, ctx)
  → ctx.warehouse_client.get_rest("/api/venue-schedule", params, ...)
  → GET /api/venue-schedule  + X-Execution-Context 头
  → 直接返回 REST JSON（data_readiness / data / citations 等字段由 warehouse 标注）
  → skill 层组装 SkillResult（readiness 从 data_readiness.level 映射）
  → mock_server 实现 GET /api/venue-schedule 等 REST 端点（保留 X-Mock-Scenario 切换错误场景）
```

**结果**：exhibition-agent 直接调 warehouse 已有的 REST 端点，无需 warehouse 改造。

## 3. 影响面

### 3.1 必改文件（exhibition-agent 内）

| 文件 | 改动 |
|------|------|
| `exhibition_agent/client/warehouse_client.py` | `invoke(skill, params) → POST /api/v1/skills/{skill}` 改成 `get_rest(path, params) → GET {path}` / `post_rest(path, params) → POST {path}`；保留重试/超时/traceparent 注入/ExecutionContext 透传；返回 `dict`（REST JSON）而非 `SkillSuccessEnvelope` |
| `exhibition_agent/client/contract_errors.py` | 保留异常类，但映射来源从「信封 error.code」改成「HTTP 状态码 + JSON body」；`ReadinessMissingError` / `GroundednessError` 保留（平台侧自检） |
| `exhibition_agent/skills/base_skill.py` | `SkillContext` 不变；`SkillResult` 保留字段（readiness/classification/sources/citations/warnings/error_code——平台侧自组装） |
| `exhibition_agent/skills/venue_schedule_query.py` | 从 `ctx.warehouse_client.invoke(self.name, params)` 改成 `ctx.warehouse_client.get_rest("/api/venue-schedule", params)`；skill 层自组装 `SkillResult`（readiness 从 REST JSON `data_readiness.level` 映射，classification 默认 INTERNAL，sources 从端点路径推导）；INV-10 落地：REST JSON `data_readiness.level in ("pending","sparse_sample","incomplete")` → 答"该指标待接入" |
| `exhibition_agent/mock_server/warehouse_mock.py` | 从实现 `POST /api/v1/skills/{skill}` 改成实现关键 REST 端点（`GET /api/venue-schedule`、`GET /api/portrait/exhibition/{id}`、`GET /api/health` 等）；保留 `X-Mock-Scenario` 头切换错误场景（401/403/404/422/429/502 经 HTTP 状态码 + JSON body 返回，不再走信封错误码） |
| `exhibition_agent/contract/envelope.py` | 保留 `Readiness` / `DataClassification` / `EgressDecision` / `Source` / `Citation`（平台侧自组装 SkillResult 用）；去掉 `SkillRequest` / `SkillSuccessEnvelope` / `SkillErrorEnvelope`（不再走信封） |
| `exhibition_agent/contract/error_codes.py` | 保留 `ErrorCode` 枚举（trace.error_code / SkillResult.error_code 用）；`ERROR_CODE_HTTP_MAP` 保留（平台侧 HTTP 映射用）；`METRIC_PENDING_CODES` / `PENDING_ANSWER_CODES` / `PENDING_ANSWER` 保留（INV-10 落地用） |
| `exhibition_agent/contract/__init__.py` | 同步导出调整 |
| `exhibition_agent/graph/state.py` | `WarehouseClient` 类型引用不变（接口改了但类型名不变） |
| `exhibition_agent/graph/nodes.py` | `run_skill` 不变（skill 接口不变）；`emit_trace` 不变（C4 保留） |
| `exhibition_agent/server.py` | `/api/query` 端点基本不变；`WarehouseClient` 构造不变；响应组装不变（从 `SkillResult` 取字段） |
| `exhibition_agent/skill_loader/parser.py` | 已有，保留（解析 SKILL.md → 48 个 Endpoint） |
| `exhibition_agent/skill_loader/app.py` | 已有，保留（Web 界面 + 动态加载端点列表 + 代理调用） |

### 3.2 测试文件（tests/）

| 文件 | 改动 |
|------|------|
| `tests/conftest.py` | `warehouse_client` fixture 不变（`WarehouseClient` 构造不变） |
| `tests/test_c2_envelope_client.py` | 重命名为 `test_warehouse_client_rest.py`；断言从信封字段改成 REST JSON 字段；`invoke(skill, params)` 调用改成 `get_rest(path, params)` |
| `tests/test_skill_venue_schedule.py` | 断言从 `result.readiness == Readiness.READY`（信封解析）改成 skill 自组装的 readiness；`invoke` mock 改成 `get_rest` mock |
| `tests/test_inv10_no_sql.py` | 保留 INV-10 断言（`sql_statements == []`）；触发方式从 `METRIC_NOT_VERIFIED` 错误码改成 REST JSON `data_readiness.level == "pending"` 字段；`test_inv10_graph_structure_guards_no_sql_node` 不变 |
| `tests/test_warehouse_client_transport.py` | `invoke` 调用改成 `get_rest`；重试/超时/Retry-After 断言不变（传输层逻辑保留） |
| `tests/test_server.py` | 端到端断言更新：`data["readiness"]` 从信封字段改成 skill 自组装；`X-Mock-Scenario` 切换错误场景保留（mock_server 保留该头） |
| `tests/test_supervisor_graph.py` | 断言更新（从信封字段改成 REST JSON） |
| `tests/test_observability.py` | `invoke` 调用改成 `get_rest`；metrics 断言不变 |
| `tests/test_c1_execution_context.py` | **不变**（C1 保留） |
| `tests/test_c4_trace.py` | **不变**（C4 保留） |
| `tests/test_execution_mode.py` | **不变**（执行档位保留） |
| `tests/test_jwt_signature.py` | **不变**（JWT 验签保留） |
| `tests/test_llm_obs.py` | `invoke` 调用改成 `get_rest`（`test_run_supervisor_with_*` 不直接调 invoke，走 supervisor，无需改） |

### 3.3 文档文件

| 文件 | 改动 |
|------|------|
| `applications/exhibition-agent/README.md` | 移除「契约 v1.1 §C2 信封」描述；新增「直接 REST」架构说明；mock 场景表更新（从信封错误码改成 HTTP 状态码）；红线遵守表更新 |
| `docs/architecture/cross-project-interface-contract.md` | 修订 §C2：从「统一信封 + skill invoke」改成「直接 REST + 平台侧自组装 SkillResult」；§C1 / §C4 / INV-10 保留；版本升 v1.2 |
| `docs/analysis/2026-09-21/02-debt-diagnosis.md` | F-S1-05 标记已修复（修订契约 v1.1 → 直接 REST） |

### 3.4 不改的文件

- **mingyang-warehouse**：不改（warehouse 48 个 REST 端点已可用）
- `exhibition_agent/contract/execution_context.py`：C1 保留
- `exhibition_agent/middleware/`：C1 中间件保留（ExecutionContext 解析与校验）
- `exhibition_agent/observability/`：C4 trace / OTel / metrics 保留
- `exhibition_agent/model_router.py`：Model Router 桩保留
- `exhibition_agent/config.py`：配置保留（可能微调描述）

## 4. 迁移策略

### 4.1 WarehouseClient 接口变更

```python
# 旧（v1.1）
async def invoke(self, skill: str, params: dict, *, execution_context_header, request_id, ...) -> SkillSuccessEnvelope:
    url = f"/api/v1/skills/{skill}"
    body = {"request_id": request_id, "skill": skill, "params": params, "options": options}
    resp = await client.post(url, headers=headers, json=body)
    return self._parse_response(resp, request_id)  # 解析信封

# 新（v1.2）
async def get_rest(self, path: str, params: dict | None = None, *, execution_context_header, request_id, ...) -> dict:
    # path 如 "/api/venue-schedule"
    resp = await client.get(path, headers=headers, params=query_params)
    return self._parse_rest_response(resp, request_id)  # 返回 REST JSON dict

async def post_rest(self, path: str, body: dict | None = None, *, execution_context_header, request_id, ...) -> dict:
    resp = await client.post(path, headers=headers, json=body)
    return self._parse_rest_response(resp, request_id)
```

**保留**：重试（UpstreamError/RateLimitedError）、超时、traceparent 注入、ExecutionContext 透传、重试总预算、Retry-After 解析、上游 body 截断。

**`_parse_rest_response`**：按 HTTP 状态码映射异常（401→AuthError，403→ScopeDeniedError，404→KnowledgeNotPublishedError，422→按 body 区分 MetricPendingError/DataNotConnectedError，429→RateLimitedError，502→UpstreamError），2xx 返回 `resp.json()`。

### 4.2 skill 层组装 SkillResult

```python
# VenueScheduleQuerySkill.run
async def run(self, params, ctx) -> SkillResult:
    try:
        data = await ctx.warehouse_client.get_rest(
            "/api/venue-schedule",
            params={"venue_id": params.get("venue_id")},
            execution_context_header=ctx.execution_context_header,
            request_id=ctx.execution_context.request_id,
            context_mode=ctx.context_mode,
            extra_headers=ctx.extra_headers,
        )
    except MetricPendingError as exc:
        return _pending_result(exc.code.value, exc.message)
    # ... 其他异常处理保留

    # INV-10 落地：REST JSON data_readiness.level 判断
    readiness_level = (data.get("data_readiness") or {}).get("level", "complete")
    if readiness_level in ("pending", "sparse_sample", "incomplete"):
        return _pending_result("DATA_NOT_CONNECTED", f"data_readiness.level={readiness_level}")

    # 自组装 SkillResult
    return SkillResult(
        answer=self._format_answer(data),
        readiness=_map_readiness(readiness_level),
        classification=DataClassification.INTERNAL,
        sources=[Source(type="table", name="t_venue_schedule", as_of=data.get("as_of"))],
        citations=[],  # REST 端点不返回 citations
        warnings=[] if readiness_level == "complete" else [f"data_readiness={readiness_level}"],
        data=data,
    )
```

### 4.3 mock_server 改造

从实现 `POST /api/v1/skills/{skill}` 改成实现关键 REST 端点：

```python
@app.get("/api/venue-schedule")
async def venue_schedule(request: Request):
    scenario = request.headers.get("X-Mock-Scenario", "normal_200")
    # ... ExecutionContext 校验保留
    if scenario == "data_not_connected":
        return JSONResponse(200, {"data": {}, "data_readiness": {"level": "pending"}})
    if scenario == "metric_not_verified":
        return JSONResponse(422, {"error": "METRIC_NOT_VERIFIED", "message": "..."})
    # ... 其他场景
    return JSONResponse(200, {"venue": "保利世贸博览馆", "date_range": "...", "data_readiness": {"level": "complete"}})

@app.get("/api/portrait/exhibition/{exhibition_id}")
async def exhibition_profile(exhibition_id: str, request: Request):
    # ... 类似
```

**保留**：`X-Mock-Scenario` 头切换场景（测试用）；ExecutionContext 校验（复用 middleware）。

**mock 端点清单**（测试覆盖范围）：
- `GET /api/venue-schedule`（venue.schedule.query skill 主端点）
- `GET /api/portrait/exhibition/{exhibition_id}`（展会画像，可选）
- `GET /api/health`（健康检查）

### 4.4 INV-10 落地方式变更

| 旧（v1.1） | 新（v1.2） |
|------|------|
| warehouse 返回信封 `error.code = METRIC_NOT_VERIFIED` → `MetricPendingError` → 答"待接入" | warehouse REST 返回 422 + `{"error": "METRIC_NOT_VERIFIED"}` → `MetricPendingError` → 答"待接入" |
| warehouse 返回信封 `error.code = DATA_NOT_CONNECTED` → `DataNotConnectedError` → 答"待接入" | warehouse REST 返回 200 + `{"data_readiness": {"level": "pending"}}` → skill 层自检 → 答"待接入" |
| `sql_statements == []` 断言 | 不变 |

**双轨保留**：422 错误码路径 + 200 data_readiness 字段路径都能触发 INV-10 "待接入"回答。mock_server 同时提供两种场景。

### 4.5 contract/ 简化

- `envelope.py`：去掉 `SkillRequest` / `SkillSuccessEnvelope` / `SkillErrorEnvelope`；保留 `Readiness` / `DataClassification` / `EgressDecision` / `Source` / `Citation`
- `error_codes.py`：全部保留（`ErrorCode` 枚举用于 trace / SkillResult / HTTP 映射）
- `execution_context.py`：不动（C1 保留）

## 5. 验收标准

### 5.1 功能验收

- [ ] `uv run pytest applications/exhibition-agent/tests -q` 全绿（测试数 ≥ 旧 99，允许因信封测试重命名增减）
- [ ] `uv run ruff check applications/exhibition-agent/` 0 error
- [ ] 8 session 全绿：根 / agent-runtime / agent-server / 联邦 / kefu / exhibition / dialogue-framework / zhanggui-zhiku
- [ ] INV-10 回归：`test_inv10_metric_pending_answers_pending_and_no_sql` 通过，`sql_statements == []`
- [ ] C1 回归：`test_c1_execution_context` 全部通过（401/403/400）
- [ ] C4 回归：`test_c4_trace` 全部通过（11 字段）

### 5.2 架构验收

- [ ] `grep -r "api/v1/skills" applications/exhibition-agent/` 零命中（不再走契约 invoke 路由）
- [ ] `grep -r "SkillSuccessEnvelope" applications/exhibition-agent/exhibition_agent/` 仅在 contract/envelope.py 定义处命中（不再被 client/skill 引用）
- [ ] `grep -r "warehouse_client.invoke" applications/exhibition-agent/` 零命中（改成 get_rest/post_rest）
- [ ] `grep -r "get_rest\|post_rest" applications/exhibition-agent/exhibition_agent/client/warehouse_client.py` 命中（新接口已实现）

### 5.3 文档验收

- [ ] README.md 移除「契约 v1.1 §C2 信封」描述，新增「直接 REST」说明
- [ ] `docs/architecture/cross-project-interface-contract.md` §C2 修订为直接 REST，版本升 v1.2
- [ ] `docs/analysis/2026-09-21/02-debt-diagnosis.md` F-S1-05 标记已修复

## 6. 风险与回滚

### 6.1 风险

- **mock_server 端点覆盖不足**：只 mock `GET /api/venue-schedule` 等关键端点，若测试需要其他端点需补 mock。风险低：当前测试只覆盖 venue.schedule.query skill。
- **INV-10 双轨触发**：422 错误码 + 200 data_readiness 字段都能触发"待接入"，需确保两条路径都被测试覆盖。风险低：mock_server 提供两种场景。
- **REST JSON 字段不稳定**：warehouse REST 端点返回的 `data_readiness.level` 字段值可能变化。风险低：skill 层用 `in ("pending","sparse_sample","incomplete")` 集合判断，容错。

### 6.2 回滚

- 本修订是 exhibition-agent 内部 + 契约文档变更，不涉及 warehouse 改造
- 回滚 = `git revert` 单次提交，无外部依赖

## 7. 实施顺序

1. **contract/ 简化**：envelope.py 去掉信封模型；error_codes.py 保留
2. **client/warehouse_client.py**：`invoke` 改成 `get_rest` / `post_rest`；`_parse_response` 改成 `_parse_rest_response`
3. **skills/venue_schedule_query.py**：改成调 `get_rest` + 自组装 SkillResult + INV-10 双轨
4. **mock_server/warehouse_mock.py**：改成实现 REST 端点
5. **tests/**：更新断言（信封 → REST JSON），重命名 test_c2_envelope_client.py
6. **验证**：pytest + ruff + 8 session
7. **文档**：README + 契约文档 + debt-diagnosis
8. **提交**：单次 `refactor(exhibition): F-S1-05 修订契约 v1.1 → 直接 REST`
