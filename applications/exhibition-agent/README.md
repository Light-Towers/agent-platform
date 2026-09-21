---
updated: 2026-09-21
---

# exhibition-agent

会展行业 AI Agent 平台侧骨架，按《跨项目接口契约 v1.1》接入 `mingyang-warehouse`。

## 项目定位

最小骨架验证 **C1（ExecutionContext）+ C2（统一信封 + 错误码）+ C4（trace）** 三条契约能落地，
重点是把 **INV-10（指标口径不可绕过）** 变成一条可回归的自动化测试。

平台侧可**不等 warehouse 就绪**就跑通契约链路（全走 mock server）。

## 目录结构

```
applications/exhibition-agent/
├── pyproject.toml              uv workspace 成员
├── README.md
└── exhibition_agent/
    ├── contract/               C1 上下文模型 + C2 信封 / 错误码（唯一定义处）
    │   ├── execution_context.py    ExecutionContext（字段冻结）
    │   ├── envelope.py             Readiness / Classification / 信封模型
    │   └── error_codes.py          错误码表 + HTTP 映射 + INV-10 落地常量
    ├── middleware/             ExecutionContext 解析与校验
    │   ├── context_codec.py        JWT / base64 编解码
    │   └── execution_context_middleware.py  C1 校验（401/403/400）
    ├── client/                warehouse 契约客户端（HTTP）
    │   ├── contract_errors.py      错误码 → 异常映射
    │   └── warehouse_client.py     httpx + 信封解析 + 缺 readiness 判 fail
    ├── skills/                只读 skill
    │   ├── base_skill.py           BaseSkill / SkillResult / SkillContext
    │   └── venue_schedule_query.py venue.schedule.query（INV-10 落地）
    ├── graph/                 最小 Supervisor 图（LangGraph）
    │   ├── state.py                ExhibitionAgentState
    │   ├── nodes.py                select_skill → run_skill → emit_trace
    │   └── supervisor.py           build_graph / run_supervisor
    ├── observability/         trace 记录（C4）
    │   └── trace.py                TraceRecord（11 字段）+ InMemoryTraceRecorder
    ├── mock_server/           warehouse 契约假实现（9 场景）
    │   └── warehouse_mock.py       FastAPI mock（X-Mock-Scenario 切换）
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
# 99 passed
```

### 起 demo server + mock warehouse

```bash
# 终端 1：mock warehouse（端口 9100）
uv run --extra dev uvicorn exhibition_agent.mock_server.warehouse_mock:create_mock_app --port 9100

# 终端 2：exhibition-agent（端口 9000）
EXHIBITION_AGENT_WAREHOUSE_BASE_URL=http://127.0.0.1:9100 \
  uv run --extra dev uvicorn exhibition_agent.server:app --port 9000

# 终端 3：查询（需带 X-Execution-Context 头）
curl -X POST http://localhost:9000/api/query \
  -H "Content-Type: application/json" \
  -H "X-Execution-Context: <JWT 或 base64 编码的 ExecutionContext>" \
  -d '{"query": "查询 SIAL 广州 2026 场馆档期", "params": {"exhibition_id": "ex-001"}}'
```

### mock / real 切换

| 项 | mock | real |
| --- | --- | --- |
| `EXHIBITION_AGENT_WAREHOUSE_BASE_URL` | `http://127.0.0.1:9100`（mock） | `https://<warehouse-host>` |
| `EXHIBITION_AGENT_CONTEXT_MODE` | `jwt`（默认）或 `base64` | 同左 |
| `EXHIBITION_AGENT_EXECUTION_MODE` | `DEV`（不验签，校验恒开） | `STRICT`（验签，需 `CONTEXT_JWT_SECRET`） |
| `EXHIBITION_AGENT_CONTEXT_JWT_SECRET` | 空 | HS256 密钥 |

mock 场景通过请求头 `X-Mock-Scenario` 切换（9 场景见下表）。

## 执行档位（契约 v1.1 §C1）

| 档位 | 身份来源 | 验签 | 401/403 | scope 下推 |
| --- | --- | --- | --- | --- |
| `STRICT`（生产） | IAM / 网关 JWT | ✅ | ✅ | ✅ |
| `DEV`（本地/测试/mock） | `PLATFORM_LOCAL` 适配器 | ❌ | ✅ **仍执行** | ✅ **仍执行** |

> 🔴 **不设 `OFF` 档** —— 校验在所有环境统一执行，环境差异仅限「身份来源 + 是否验签」。
> 角色延后：本次只按 `scopes[]` 判定，`roles[]` 保留可留空、不参与判定。

## 契约版本对齐

| 项 | 值 |
| --- | --- |
| 契约版本 | **1.1** |
| 主本 | `mingyang-warehouse/docs/superpowers/specs/2026-09-20-cross-project-interface-contract.md` |
| 副本 | `agent-platform/docs/architecture/cross-project-interface-contract.md` |
| 本包实现 | `exhibition_agent/contract/`（唯一定义处） |

## mock server 9 场景

| X-Mock-Scenario | 期望 |
| --- | --- |
| `normal_200` | 成功信封（readiness/classification/sources/citations 齐全） |
| `missing_context` | 401 AUTH_CONTEXT_MISSING |
| `scope_denied` | 403 SCOPE_DENIED |
| `knowledge_not_published` | 404 KNOWLEDGE_NOT_PUBLISHED |
| `metric_not_verified` | 422 METRIC_NOT_VERIFIED |
| `metric_blocked` | 422 METRIC_BLOCKED |
| `data_not_connected` | 422 DATA_NOT_CONNECTED（答"待接入"，并入 INV-10） |
| `knowledge_missing_citations` | 200 但 sources 含 knowledge 无 citations（GroundednessError 拒绝展示） |
| `missing_readiness` | 200 但缺 readiness（客户端判 fail） |

## INV-10 回归测试（最关键验收）

`tests/test_inv10_no_sql.py`：
- `METRIC_NOT_VERIFIED` / `METRIC_BLOCKED` / `DATA_NOT_CONNECTED` → 回答 **"该指标待接入"**
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
| 不设"测试环境跳过校验"开关 | ✅ 执行档位 STRICT/DEV 只切验签，401/403/scope 恒开，无 OFF 档（grep 确认无 if testing/skip/bypass 路径） |

### 架构红线豁免披露（审核建议 1）

本应用**显式不依赖** `shared-schemas` / `agent-runtime`，自带 Skill / 信封 / ExecutionContext 实现（`contract/__init__.py`），实质偏离仓库架构红线 4/5（"能力收口到内核/运行时，不重复实现"）。豁免理由：

- **跨项目独立交付**：exhibition-agent 按跨项目接口契约 v1.1（对端 mingyang-warehouse）独立交付，信封 / ExecutionContext 是**跨项目对外契约**，与联邦内部契约（shared-schemas）是另一套口径，复用 shared-schemas 会把内部契约泄漏给外部项目；
- 豁免范围仅限 contract/skills/self-contained 中间件，observability 已复用 agent-core（`agent_core.tracing`）；
- 该豁免需架构负责人登记确认后长期有效，收敛方向见 debt-diagnosis F-S1-05。

### 契约回提声明（审核建议 2）

本 README 所述「契约 v1.1」的澄清结论（§0.5 歧义反馈等）目前仅在仓库内实现侧落地，**尚未回提至契约主本**（主本在 mingyang-warehouse 侧仓库）。两份文本存在漂移风险，回提后本节同步移除。

## 歧义 / 反馈清单

v1.0 实现反馈的 7 项歧义，**契约 v1.1 §0.5 已全部给出结论**，本实现已按 v1.1 补丁全部落地：

| # | v1.0 反馈点 | v1.1 结论 | 本实现落地 |
| --- | --- | --- | --- |
| 1 | 目录布局 src/ vs flat | 采用 flat layout | ✅ flat layout |
| 2 | 自报 tenant_id 位置未定义 | body `params.tenant_id` | ✅ middleware 检测 `params.tenant_id` |
| 3 | 资源级判定未定义 | 路径含 `/exhibition/`/`/venue/` 或 skill 前缀 `exhibition.`/`venue.` | ✅ `_is_resource_level(path, skill)` |
| 4 | DATA_NOT_CONNECTED mock 缺失 | 补 mock 场景，答"待接入"，并入 INV-10 | ✅ mock + skill + 测试 |
| 5 | error_code 必填性张力 | 仅出错时必填，其余 10 恒必填 | ✅ TraceRecord error_code 可选 |
| 6 | JWT 验签密钥注入未定义 | mock 不验签，生产待决 | ✅ STRICT/DEV 档位，DEV 不验签 |
| 7 | 知识类响应判定未定义 | sources 含 type=knowledge → citations 必填 | ✅ client `_check_groundedness` |
| 8 | 权限校验让测试难做 | STRICT/DEV 档位，校验恒开，无 OFF | ✅ `execution_mode_to_verify_signature` + DEV 仍 401/403 测试 |

**v1.1 实现无新增歧义。**
