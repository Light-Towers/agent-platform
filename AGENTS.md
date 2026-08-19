# agent-platform — Agent 上下文文件

> 统一生产级 Agent 平台，本仓库为 **monorepo**（根 + `packages/` 3 个共享包 + `applications/` 6 个应用工程，各含独立 `pyproject.toml`）。
> **演进方向（Plan-F）**：双轨正收敛为「单 Runtime + 多 Planner」——共享 `agent-runtime/` 承载运行时中间件（admission/coordinator/checkpoint/tracing/cache/rate_limit 等），Planner 策略（deterministic/agentic）可插拔，不统一 Agent 只统一 Runtime。详见 `docs/plan-f-single-runtime-multi-planner.md`。
> 各包经 `agent-core` / `shared-schemas` 共享内核与契约。
> 详细人类阅读指南见 `README.md`（含完整目录结构），本文件面向 AI agent，仅列要点。

## 目录结构

| 目录 | 定位 | 入口 |
|------|------|------|
| `applications/agent_server/` | 单进程 Supervisor 平台（统一 Agent 平台；2026-08-19 由根 `app/` 改名迁入） | `agent_server.main:app`（uvicorn） |
| `applications/agent_federation/` | 联邦网关 + 3 子服务编排中枢（与 agent_server 并行，详见其 README；原名 `deepagents/`，为消除与 PyPI 依赖包 `deepagents` 同名冲突而改名） | `python -m api.server` |
| `packages/agent-core/` | 零依赖运行时内核：tracing / guardrails / sql 守卫 / llm / memory / typed 记忆 | — |
| `packages/agent-runtime/` | Plan-F 运行时中间件层：admission/coordinator/cache/circuit_breaker/revert/mcp_client/otel/tracing/db + planner/（Planner 协议、PlannerRuntime、skill_guard）+ skills/（SkillRegistry + Function/Agent/Remote/Workflow 四执行器） | — |
| `packages/shared-schemas/` | 联邦 4 服务共享 Pydantic 契约（QueryResponse / ThreadState 等） | — |
| `applications/kefu-service/` | kefu 迁移版（deepagents + LangGraph），已接入联邦网关（Agent Protocol 兼容 `/invoke`，返回 `QueryResponse`；`KEFU_USE_ADAPTER=false` 默认直连） | — |
| `applications/wenda-data-agent/` | Text-to-SQL 数据分析垂直场景（已直连联邦契约，无需 adapter） | — |
| `applications/zhanggui-zhiku/` | 掌柜智库：RAG 知识库导入 + 多路检索问答（:8900；**注意包名仍为 `app`**，sys.path 上会遮蔽旧 app 名，勿在根测试中 import `app`） | `zhanggui-zhiku` 脚本 |
| `applications/dialogue-framework/` | LLM 对话系统框架基础设施 | `dialogue_framework.cli:main` |
| `tests/` | agent_server 单元测试 | `pytest -q` |
| `eval/` | agent_server 评测门禁（12 条 golden；`run_eval.py` 启发式 + `run_planner_eval.py` 双 Planner 基线） | `python eval/run_eval.py` |
| `docs/` | 设计文档 | — |

## 运行方式

```bash
uv sync --all-packages --extra dev   # 安装（workspace 全量包 + dev 工具）
make ci                              # CI 唯一门禁：lint + 根 pytest（tests/ + packages/*/tests + applications/agent_federation/tests/unit + applications/kefu-service/tests）+ 启发式 eval
make test                            # 三套件 pytest（根 / 联邦 / kefu）
make eval                            # 评测门禁（启发式，CI 可达）
DATABASE_URL= uvicorn agent_server.main:app --port 8000  # 零依赖冒烟
```

## 技术栈

- Python 3.11+（所有包的 `requires-python` 均为 `>=3.11`）
- FastAPI · LangGraph（仅作执行实现）· deepagents · pgvector · sqlglot · pydantic v2
- 共享内核：`agent-core`（零依赖运行时内核）· `agent-runtime`（运行时中间件 + Planner/Skill 协议）· `shared-schemas`（联邦契约）

## 禁止行为

- **勿提交真实 `.env` 文件**：所有 `.env` 已被 `.gitignore` 忽略，使用前按 `.env.example` 填值
- **勿提交大二进制资产**：模型权重、数据集均未入库，需本地自备
- **勿在根测试/共享代码中 `import app`**：`applications/zhanggui-zhiku/app/` 包名仍为 `app`，会遮蔽；统一用 `agent_server.*`