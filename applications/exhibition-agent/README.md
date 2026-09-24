---
updated: 2026-09-21
---

# exhibition-agent

会展行业 AI Agent 平台侧骨架，按《跨项目接口契约 v1.2：直接 REST》接入 `mingyang-warehouse`。

## 项目定位

最小骨架验证 **C1（ExecutionContext）+ C2'（直接 REST + HTTP 状态码映射）+ C4（trace）** 三条契约能落地，
重点是把 **INV-10（指标口径不可绕过）** 变成一条可回归的自动化测试。

平台侧可**不等 warehouse 就绪**就跑通契约链路（全走 mock server）。

## 契约版本 v1.1 → v1.2 变更（F-S1-05 修复，2026-09-21）

> 详见 `docs/plans/plan-fix-f-s1-05-contract-revise-to-rest.md`。

**问题**：v1.1 走 `POST /api/v1/skills/{name}` + 统一信封，但真实 warehouse（mingyang-warehouse，48 个 REST 端点）无该路由，真实调用 404；mock 掩盖此缺口。

**修订**：契约 v1.2 选择直接 REST 方案——exhibition-agent 的 skill 层改成直接调 warehouse REST 端点（`GET /api/venue-schedule` 等），不再走统一信封。

| 项 | v1.1（旧） | v1.2（新） |
| --- | --- | --- |
| 调用方式 | `POST /api/v1/skills/{name}` + 信封 body | 直接 `GET /api/venue-schedule` 等 REST 端点 |
| 响应格式 | 统一信封（readiness/classification/sources/citations） | REST JSON（data_readiness.level 字段） |
| 错误映射 | 信封 error.code → ContractError 子类 | HTTP 状态码 + body.error.code → ContractError 子类 |
| INV-10 落地 | 信封 error.code = METRIC_NOT_VERIFIED → 答"待接入" | 双轨：422 错误码 + 200 data_readiness.level=pending → 答"待接入" |
| C1 ExecutionContext | 保留 | 保留 |
| C4 trace | 保留 | 保留 |

## 目录结构

```
applications/exhibition-agent/
├── pyproject.toml              uv workspace 成员
├── README.md
└── exhibition_agent/
    ├── contract/               C1 上下文模型 + C2' REST 契约（唯一定义处）
    │   ├── execution_context.py    ExecutionContext（字段冻结，C1 保留）
    │   ├── envelope.py             Readiness / Classification / Source / Citation（平台侧自组装用）
    │   └── error_codes.py          错误码表 + HTTP 映射 + INV-10 落地常量
    ├── middleware/             ExecutionContext 解析与校验（C1 保留）
    │   ├── context_codec.py        JWT / base64 编解码
    │   └── execution_context_middleware.py  C1 校验（401/403/400）
    ├── client/                warehouse REST 客户端（HTTP，v1.2 直接 REST）
    │   ├── contract_errors.py      错误码 → 异常映射
    │   └── warehouse_client.py     httpx + get_rest/post_rest + HTTP 状态码映射
    ├── skills/                只读 skill（v1.2 直接 REST + 自组装 SkillResult）
    │   ├── base_skill.py           BaseSkill / SkillResult / SkillContext
    │   └── venue_schedule_query.py venue.schedule.query（直接调 GET /api/venue-schedule，INV-10 双轨落地）
    ├── graph/                 最小 Supervisor 图（LangGraph）
    │   ├── state.py                ExhibitionAgentState
    │   ├── nodes.py                select_skill → run_skill → emit_trace
    │   └── supervisor.py           build_graph / run_supervisor
    ├── observability/         trace 记录（C4）
    │   └── trace.py                TraceRecord（11 字段）+ InMemoryTraceRecorder
    ├── mock_server/           warehouse REST 假实现（9 场景，v1.2 REST 端点）
    │   └── warehouse_mock.py       FastAPI mock（GET /api/venue-schedule 等 + X-Mock-Scenario 切换）
    ├── skill_loader/          SKILL.md 解析 + Web 调试界面（动态加载 48 个端点）
    │   ├── parser.py               SKILL.md → Endpoint 列表
    │   ├── app.py                  FastAPI Web 界面 + 代理调用
    │   └── SKILL.md                mingyang-warehouse 能力总表副本
    ├── model_router.py        §17.5 Model Router 桩（不接真模型）
    ├── config.py              pydantic-settings 配置
    ├── server.py              FastAPI demo 入口
    └── testing_helpers.py     测试公共工具
```

## 运行方式

### 跑测试（全走 mock，不依赖网络 / 真实 warehouse）

```bash
cd applications/exhibition-agent
uv run --extra dev pytest tests/ -v
# 114 passed, 1 skipped
```

### 起 demo server + mock warehouse

```bash
# 终端 1：mock warehouse（端口 9100，v1.2 REST 端点）
uv run --extra dev uvicorn exhibition_agent.mock_server.warehouse_mock:create_mock_app --port 9100

# 终端 2：exhibition-agent（端口 9000）
EXHIBITION_AGENT_WAREHOUSE_BASE_URL=http://127.0.0.1:9100 \
  uv run --extra dev uvicorn exhibition_agent.server:app --port 9000

# 终端 3：查询（需带 X-Execution-Context 头）
curl -X POST http://localhost:9000/api/query \
  -H "Content-Type: application/json" \
  -H "X-Execution-Context: <JWT 或 base64 编码的 ExecutionContext>" \
  -d '{"query": "查询 SIAL 广州 2026 场馆档期", "params": {"venue_id": "vn-001"}}'
```

### 接真实 warehouse（192.168.100.241:8000）

```bash
EXHIBITION_AGENT_WAREHOUSE_BASE_URL=http://192.168.100.241:8000 \
  uv run --extra dev uvicorn exhibition_agent.server:app --port 9000
```

### mock / real 切换

| 项 | mock | real |
| --- | --- | --- |
| `EXHIBITION_AGENT_WAREHOUSE_BASE_URL` | `http://127.0.0.1:9100`（mock） | `http://192.168.100.241:8000` |
| `EXHIBITION_AGENT_CONTEXT_MODE` | `jwt`（默认）或 `base64` | 同左 |
| `EXHIBITION_AGENT_EXECUTION_MODE` | `DEV`（不验签，校验恒开） | `STRICT`（验签，需 `CONTEXT_JWT_SECRET`） |
| `EXHIBITION_AGENT_CONTEXT_JWT_SECRET` | 空 | HS256 密钥 |

mock 场景通过请求头 `X-Mock-Scenario` 切换（9 场景见下表）。

## 执行档位（契约 v1.2 §C1，保留）

| 档位 | 身份来源 | 验签 | 401/403 | scope 下推 |
| --- | --- | --- | --- | --- |
| `STRICT`（生产） | IAM / 网关 JWT | ✅ | ✅ | ✅ |
| `DEV`（本地/测试/mock） | `PLATFORM_LOCAL` 适配器 | ❌ | ✅ **仍执行** | ✅ **仍执行** |

> 🔴 **不设 `OFF` 档** —— 校验在所有环境统一执行，环境差异仅限「身份来源 + 是否验签」。
> 角色延后：本次只按 `scopes[]` 判定，`roles[]` 保留可留空、不参与判定。

## 契约版本对齐

| 项 | 值 |
| --- | --- |
| 契约版本 | **1.2**（直接 REST，修订自 v1.1 统一信封） |
| 主本 | `mingyang-warehouse/docs/superpowers/specs/2026-09-20-cross-project-interface-contract.md` |
| 副本 | `agent-platform/docs/architecture/cross-project-interface-contract.md` |
| 本包实现 | `exhibition_agent/contract/`（唯一定义处） |
| 修订方案 | `docs/plans/plan-fix-f-s1-05-contract-revise-to-rest.md` |

## mock server 9 场景（v1.2 REST 端点）

| X-Mock-Scenario | 期望 |
| --- | --- |
| `normal_200` | 200 + REST JSON（data_readiness.level=complete + citations 齐全） |
| `missing_context` | 401 AUTH_CONTEXT_MISSING（C1 中间件校验） |
| `scope_denied` | 403 SCOPE_DENIED |
| `knowledge_not_published` | 404 + {"error":{"code":"KNOWLEDGE_NOT_PUBLISHED"}} |
| `metric_not_verified` | 422 + {"error":{"code":"METRIC_NOT_VERIFIED"}} |
| `metric_blocked` | 422 + {"error":{"code":"METRIC_BLOCKED"}} |
| `data_not_connected` | 200 + {"data_readiness":{"level":"pending"}}（INV-10 200 路径） |
| `data_not_connected_422` | 422 + {"error":{"code":"DATA_NOT_CONNECTED"}}（INV-10 422 路径） |
| `missing_readiness` | 200 + 无 data_readiness 字段（skill 层默认 READY） |

## INV-10 回归测试（最关键验收，v1.2 双轨）

`tests/test_inv10_no_sql.py`：
- **422 路径**：`METRIC_NOT_VERIFIED` / `METRIC_BLOCKED` / `DATA_NOT_CONNECTED` → 回答 **"该指标待接入"**
- **200 路径**：`data_readiness.level=pending` → 回答 **"该指标待接入"**（v1.2 新增）
- 断言 `sql_statements == []`（全程未生成任何 SQL，禁止 L3 text2sql 自算）
- 断言 trace.error_code 记录对应错误码
- 断言 trace.model 不是 cloud 模型（出域不得降级）

## 红线遵守

| 红线 | 遵守 |
| --- | --- |
| 不直连 MySQL（INV-6） | ✅ 只有 httpx HTTP，无任何 DB 连接串 / 驱动 |
| 不 vendor / copy warehouse 代码 | ✅ 全部自写，无拷贝 |
| 不改平台内核 | ✅ 仅在根 pyproject workspace members 加一行，未改 agent-core / agent_federation / agent_server |
| 不引入 LangChain 全家桶 | ✅ 只用 langgraph（平台已有），无 langchain Chain/Retriever/Agent |
| 不实现写操作与 HITL 执行 | ✅ 只有只读 skill，HITL 未实现（留接口位） |
| 不接真实 LLM / 真模型 | ✅ Model Router 是桩，不接真模型 |
| 不设"测试环境跳过校验"开关 | ✅ 执行档位 STRICT/DEV 只切验签，401/403/scope 恒开，无 OFF 档 |
| 真实 warehouse 可直连（v1.2 修复） | ✅ 直接调 GET /api/venue-schedule 等 REST 端点，不再走 POST /api/v1/skills/{name}（F-S1-05 闭环） |

### 架构红线豁免披露（F-S1-05 已修复，2026-09-21）

本应用**显式不依赖** `shared-schemas` / `agent-runtime`，自带 Skill / ExecutionContext 实现（`contract/__init__.py`）。

**F-S1-05 已修复**：契约 v1.1 → v1.2 修订（直接 REST），exhibition-agent 的 skill 层从 `POST /api/v1/skills/{name}` + 信封改成直接调 warehouse REST 端点。详见 `docs/plans/plan-fix-f-s1-05-contract-revise-to-rest.md`。

豁免理由（保留登记）：
- **跨项目独立交付**：exhibition-agent 按跨项目接口契约（对端 mingyang-warehouse）独立交付，ExecutionContext 是**跨项目对外契约**，与联邦内部契约（shared-schemas）是另一套口径，复用 shared-schemas 会把内部契约泄漏给外部项目；
- 豁免范围仅限 contract/skills/self-contained 中间件，observability 已复用 agent-core（`agent_core.tracing`）。

### 契约回提声明

本 README 所述「契约 v1.2」的修订结论目前仅在仓库内实现侧落地，**尚未回提至契约主本**（主本在 mingyang-warehouse 侧仓库）。两份文本存在漂移风险，回提后本节同步移除。

## v1.1 → v1.2 修订落地清单

| # | v1.1 | v1.2 落地 |
| --- | --- | --- |
| 1 | WarehouseClient.invoke(skill, params) → POST /api/v1/skills/{skill} + 信封 | WarehouseClient.get_rest(path, params) → GET /api/venue-schedule + REST JSON |
| 2 | SkillSuccessEnvelope 信封解析（readiness/classification/sources/citations） | skill 层自组装 SkillResult（readiness 从 data_readiness.level 映射） |
| 3 | mock_server 实现 POST /api/v1/skills/{skill} | mock_server 实现 GET /api/venue-schedule 等 REST 端点 |
| 4 | INV-10 走信封 error.code = METRIC_NOT_VERIFIED | INV-10 双轨：422 错误码 + 200 data_readiness.level=pending |
| 5 | envelope.py 含 SkillRequest/SkillSuccessEnvelope/SkillErrorEnvelope | envelope.py 移除信封模型，保留 Readiness/Source/Citation 等枚举 |
| 6 | C1 ExecutionContext / C4 trace | 保留不动 |
