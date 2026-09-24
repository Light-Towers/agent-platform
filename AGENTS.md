# agent-platform — Agent 上下文文件

> 统一生产级 Agent 平台，本仓库为 **monorepo**（根 + `packages/` 3 个共享包 + `applications/` 6 个应用工程，各含独立 `pyproject.toml`）。
> **演进方向（Plan-F）**：双轨正收敛为「单 Runtime + 多 Planner」——共享 `agent-runtime/` 承载运行时中间件（admission/coordinator/checkpoint/tracing/cache/rate_limit 等），Planner 策略（deterministic/agentic）可插拔，不统一 Agent 只统一 Runtime。详见 `docs/plans/plan-f-single-runtime-multi-planner.md`。
> **V3 企业执行平台（Phase 2-4 + 3.4 代码已接线；P0-1 并发门控已修（submit 实际入队 + claim_token fencing）；端到端双实例物理故障转移验收未达）**：主执行链路 `Admission → Scheduler submit → Planner → Execute → Forensic/CostGov`；`scheduler_enabled` 默认 False（渐进式开启，待验收达标后翻转）；**未接线半成品**（P1-7 已标注）：human_task / execution_recovery / state_migration / payload_externalization / skill_router(exhibition)。架构真相源：`docs/plans/plan-enterprise-platform-skeleton-2026-09-23.md` + `docs/plans/plan-v3-execution-platform-final-architecture-2026-09-22.md` + `docs/plans/arch-audit-2026-09-24.md`。
> 各包经 `agent-core` / `shared-schemas` 共享内核与契约。
> 详细人类阅读指南见 `README.md`（含完整目录结构），本文件面向 AI agent，仅列要点。

## 目录结构

| 目录 | 定位 | 入口 |
|------|------|------|
| `applications/agent_server/` | 单进程 Supervisor 平台（统一 Agent 平台；V3 Phase 2-4 已接入 Scheduler/ControlPlane/CostGov/Forensic，`api/` 含 `callback.py` + `control.py`；2026-08-19 由根 `app/` 改名迁入） | `agent_server.main:app`（uvicorn） |
| `applications/agent_federation/` | 联邦网关 + 3 子服务编排中枢（与 agent_server 并行，详见其 README；原名 `deepagents/`，为消除与 PyPI 依赖包 `deepagents` 同名冲突而改名） | `python -m api.server` |
| `packages/agent-core/` | 零依赖运行时内核：tracing / guardrails / sql 守卫 / llm / memory（含 MemoryStore 统一门面 + CapabilityReport） / events（EventBus 多 sink 扇出） / config（KernelConfig + 类型化 env） / intent（L1 分类器） / resilience（CircuitBreaker + retry + timeout） | — |
| `packages/agent-runtime/` | Plan-F 运行时中间件层 + V3 企业执行平台：admission/coordinator/cache/circuit_breaker/revert/mcp_client/otel/tracing/db + **execution_scheduler/execution_status/awaitable_task/control_plane/cost_governance/forensic/human_task/effect_contract/execution_recovery/state_migration/payload_externalization**（V3 Phase 2-4） + planner/（protocol/agentic/agentic_bridge/registry/policy/mode_selector/context_manager/execution_graph/graph_compose/durability/durability_pg）+ skills/（registry/function/agent/remote/workflow/mcp/sandbox/middleware/composition/dag） + sandbox（双后端代码执行） + memory 体系（episodic/semantic/procedural/working/decay/recall/seed/sink） | — |
| `packages/shared-schemas/` | 联邦 4 服务共享 Pydantic 契约（QueryRequest/Response · ErrorResponse · KNOWLEDGE_STATUS · ThreadState 等） | — |
| `applications/kefu-service/` | kefu 迁移版（deepagents + LangGraph），已接入联邦网关（Agent Protocol 兼容 `/invoke`，返回 `QueryResponse`；`KEFU_USE_ADAPTER=false` 默认直连） | — |
| `applications/nl2sql-service/` | Text-to-SQL 数据分析通用服务（元知识参数化，已直连联邦契约） | — |
| `applications/knowledge-service/` | 通用知识库服务：RAG 导入 + 多路检索问答（:8900，Metadata 参数化 + 生命周期 + 多租户 ACL） | `knowledge-service` 脚本 |
| `applications/exhibition-agent/` | 会展行业 AI Agent（skill_loader + warehouse REST 集成） | `uvicorn exhibition_agent.skill_loader.app:app` |
| `tests/` | agent_server 单元测试（根套件） | `pytest -q` |
| `applications/agent_server/tests/` | agent_server 应用层集成测试（GraphPlanner × runtime，2026-09-21 F-S1-01 迁入） | `pytest applications/agent_server/tests -q` |
| `eval/` | agent_server 评测门禁（15 条 golden；`run_eval.py` 启发式 + `run_planner_eval.py` 双 Planner 基线） | `python eval/run_eval.py` |
| `docs/` | 设计文档 | — |

## 运行方式

```bash
uv sync --all-packages --extra dev   # 安装（workspace 全量包 + dev 工具）
make ci                              # CI 唯一门禁：lint + 10 个 pytest session（见 Makefile test 目标）+ 启发式 eval
make test                            # 9 session pytest（根 / shared-schemas / agent-runtime / agent-server / 联邦 / kefu / exhibition / knowledge-service / nl2sql-service）
make eval                            # 评测门禁（启发式，CI 可达）
DATABASE_URL= uvicorn agent_server.main:app --port 8000  # 零依赖冒烟
```

## 验证策略（分层，避免每次跑全量 10 session）

> `make test`（10 个 pytest session）是 **CI 门禁**，不是每次小改动的必跑项。按改动范围分层收敛，先 lint 快速拦截再决定是否跑测试。

| 改动范围 | 验证步骤 |
|---------|---------|
| 单包内小改 | `make lint` + 受影响子集 `uv run pytest <改动目录>/tests -q` |
| 跨 2~3 包 | lint + 相关 session（取 Makefile `test` 目标对应行）|
| 声称完成/可提交前 | `make test` 对齐 CI；必要时 `make eval` |
| 修一轮失败后迭代 | `uv run pytest <目录> --lf -q`（只跑上次失败）或 `--ff`（失败优先）|

**收窄手段**：`-k "test_auth"` 按名过滤 · `-m "not slow"` 按 marker 排除 · `--lf`/`--ff` 失败优先 · `-n auto` 并行（需 pytest-xdist）。

**conftest 守卫识别**（来源：经验 `2026-09-21-gate-external-test-adoption-decision-flow`）：读 conftest docstring 与跳过守卫（如 `ZHIKU_INTEGRATION=1`、缺 OTel SDK），区分「每次 PR 必跑」vs「Nightly/手动/缺环境自动 skip」；后者本地缺环境跳过属设计意图，非失败。

**红线**：测试红时修产品代码到契约要求，**禁止删用例/收窄断言/放宽前置条件凑绿**。

**Windows 注意**：本机无 `make`，直接用 `uv run pytest ...` / `uv run --with ruff ruff check .` 等价命令。

**文档防漂移**：`scripts/check_doc_sync.py` 在 CI 单独跑（非 `make lint`），校验 AGENTS.md/ARCHITECTURE.md 路径存在 + Makefile session 数一致。改目录结构后须保证其通过。

## 技术栈

- Python 3.11+（所有包的 `requires-python` 均为 `>=3.11`）
- FastAPI · LangGraph（仅作执行实现）· deepagents · pgvector · sqlglot · pydantic v2
- 共享内核：`agent-core`（零依赖运行时内核）· `agent-runtime`（运行时中间件 + Planner/Skill 协议）· `shared-schemas`（联邦契约）

## 禁止行为

- **依赖方向单向（红线 1）**：`agent-runtime` / `agent-core` 不得反向 import `applications/`（含 `agent_server.*`）；依赖方向必须是 `application → agent-runtime → agent-core`，单向。共享包测试需具体 Planner 实现时用 mock/协议替身，不得引入应用层 import。
- **勿提交真实 `.env` 文件**：所有 `.env` 已被 `.gitignore` 忽略，使用前按 `.env.example` 填值
- **勿提交大二进制资产**：模型权重、数据集均未入库，需本地自备
- **根测试/共享代码统一用 `agent_server.*`**：各应用子包已有独立 Python 包名（`knowledge_service` / `nl2sql_service` / `agent_server` 等），无遮蔽风险
- **所有代码优化/重构必须先制定方案**：除非方案已敲定（有文档/issue 记录并经确认），**禁止直接动手改代码**；方案需包含目标、影响面、迁移策略、验收标准，并在文档/issue 中记录

## 架构决策原则（横切关注点全局优先）

> **框架/架构类问题（横切关注点：错误处理、鉴权、限流、可观测/request_id、审计、依赖守卫等）必须从全局角度出发解决，禁止"每处各自实现"的散点式做法。** 判定口诀：动手前先问——"这件事现在是全局统一处理的，还是每处都写一遍？"

- **三层齐备才算全局解**（缺一层即退化为约定，迟早被破窗）：
  1. **单一实现**：逻辑收敛到 kernel（`agent-core`），不在各 app 复制；
  2. **全局装配**：由构造保证不可漏接（统一 app 工厂 / 统一门面 / 中间件），而非靠每个调用点"记得调一次"——**接线散落 = 反模式**，即便逻辑已共享也不算全局；
  3. **强制门禁**：用不变量 lint（`scripts/lint_architecture.py`：全仓扫描 + 白名单，计入 `make ci`）拦截未来漂移，让违规在 CI 失败而非靠自觉。
- **先实测再动手**：判断"是否已有全局兜底"要靠读代码/跑验证，不凭模式猜。例：FastAPI 未捕获异常其实已被 Starlette `ServerErrorMiddleware` 全局兜底为裸 500（`debug=True` 不开时堆栈不外泄），真正缺的只是统一信封——据此把改动收敛到"补统一 handler"而非"重造防泄露"。
- **范例（2026-09-24 P2）**：入站错误脱敏 handler 从"仅 1/6 应用手写、其余裸默认"收敛为 `agent_core.guardrails.app_factory.build_api_app`（工厂，全部生产 app 经此创建）+ `agent_core.guardrails.errors`（单一实现）+ `lint_architecture.py` 的"裸 `FastAPI(` 即失败"不变量（门禁）。方案见 `docs/plans/plan-p2-unified-exception-handlers-2026-09-24.md`。
- **边界**：全局优先不等于强行统一对外契约——若改写会影响下游消费者（前端/网关解析的错误体形状），须先审计消费者、按"先方案后编码"另行决策，不得为求统一而静默破坏兼容。

## 框架选型规则

- **只用成熟框架，不成熟的宁可手写也不引入**：成熟 = 稳定发布 + 社区活跃 + 文档完善 + 广泛采用
- **能用成熟框架优先引入**：框架的抽象模型与需求契合 + 引入成本 < 自行实现 + 维护 + 出错风险时，优先用框架
- **框架的约束应是"减少犯错"而非"阻碍绕过"**：如果需要大量适配/绕过代码，说明抽象模型不契合，手写更合适
- **简单逻辑手写比引入框架更清晰时不硬套**：如 6 状态 5 转换的状态机，手写比引入 `transitions` 库更清晰
- **当前项目已确定的框架选型**：
  - 引入：**RAGAS** 或 **DeepEval**（RAG 评测通用指标）· **Microsoft Presidio**（PII 脱敏）· **OpenTelemetry**（可观测，已有底座）
  - 保持手写：知识生命周期状态机（太简单）· 数据分级/出域/模型路由（业务逻辑）· Metric Registry（当前规模不需要）· 检索链路（已有 Milvus+RRF+rerank）· SQL 问数（已有 pgvector+sqlglot）
  - 需评估：ExecutionContext 是否迁移到 **PyJWT** + 标准 JWT（契约变更，需谨慎）

## 技术债追踪

> D1-D10 **非全部闭合**（2026-09-24 复核更正）：D2/D3/D6 已完成，D7 已反转为全局豁免（见审计 P0-4），D1/D4/D5/D8 为 Low 优先级**跳过项（未闭合）**。追踪文档：
> - `docs/plans/plan-tech-debt-followup-2026-09-22.md` — D1-D10 完整追踪（D2/D3/D6 已标记完成）
> - `docs/plans/tech-debt-multi-agent-2026-09-23.md` — 多 Agent 缺陷 P0/P1/C/B 修复记录（全部已修/豁免）
> - `docs/plans/skill-consolidation-inventory.md` — Skill 收敛 P0-P5 状态（G1-G6 全部 ✅）
>
> 后续如再遇裸 except / llm_client 散落，按已建立的 agent_core.llm 统一门面与 except 收窄规范处理。