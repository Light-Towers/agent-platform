# agent-platform — Agent 上下文文件

> 统一生产级 Agent 平台，本仓库为 **monorepo**（9 个独立 `pyproject.toml` 工程：根 + app + agent_federation + agent-core + shared-schemas + kefu-service + wenda-data-agent + zhanggui-zhiku + dialogue-framework）。
> 根 `app/` 是一套单进程 Supervisor 平台；`agent_federation/` 是并行的联邦网关编排系统（两者非上下级）。
> **演进方向（Plan-F）**：双轨正收敛为「单 Runtime + 多 Planner」——共享 `agent-runtime/` 承载运行时中间件（admission/coordinator/checkpoint/tracing/cache/rate_limit 等），Planner 策略（deterministic/agentic）可插拔，不统一 Agent 只统一 Runtime。详见 `docs/plan-f-single-runtime-multi-planner.md`。
> 各包经 `agent-core` / `shared-schemas` 共享内核与契约。
> 详细人类阅读指南见 `README.md`（含完整目录结构），本文件面向 AI agent，仅列要点。

## 目录结构

| 目录 | 定位 | 入口 |
|------|------|------|
| `app/` | 单进程 Supervisor 平台（统一 Agent 平台，本 README 主描述对象） | `app/main.py` |
| `agent_federation/` | 联邦网关 + 3 子服务编排中枢（与 `app/` 并行，详见 `agent_federation/README.md`；原名 `deepagents/`，2026-08-19 为消除与 PyPI 依赖包 `deepagents` 同名冲突而改名） | `python -m api.server` |
| `agent-core/` | 零依赖运行时内核：tracing / guardrails / sql 守卫 / llm / memory | — |
| `shared-schemas/` | 联邦 4 服务共享 Pydantic 契约（QueryResponse / ThreadState 等） | — |
| `agent-runtime/` | Plan-F 运行时中间件层（admission/coordinator/cache/circuit_breaker/revert/mcp_client/otel/tracing/db，Phase 0 已全部迁入；`app/infra/` 已退役仅剩空包占位） | — |
| `kefu-service/` | kefu 迁移版（deepagents + LangGraph），已实现且 CI 通过，已接入联邦网关（Agent Protocol 兼容 `/invoke`，返回 `QueryResponse`；`KEFU_USE_ADAPTER=false` 默认直连） | — |
| `wenda-data-agent/` | Text-to-SQL 数据分析垂直场景（已直连联邦契约，无需 adapter） | — |
| `zhanggui-zhiku/` | 掌柜智库：RAG 知识库导入 + 多路检索问答（:8900） | `zhanggui-zhiku` 脚本 |
| `dialogue-framework/` | LLM 对话系统框架基础设施 | `dialogue_framework.cli:main` |
| `tests/` | `app/` 单元测试 | `pytest -q` |
| `eval/` | `app/` 评测门禁（12 条 golden） | `python -m eval.run_eval` |
| `docs/` | 设计文档 | — |

## 运行方式

```bash
pip install -e ".[dev]"          # 安装
make ci                           # CI 唯一门禁：根 pytest（收集 tests/ + agent-core/tests + agent_federation/tests/unit + kefu-service/tests）
python -m eval.run_eval           # 评测门禁
DATABASE_URL= uvicorn app.main:app --port 8000  # 零依赖冒烟
```

## 技术栈

- Python 3.11+（所有包的 `requires-python` 均为 `>=3.11`；根 `pyproject.toml` 同）
- FastAPI · LangGraph · pgvector · sqlglot · pydantic v2
- 共享内核：`agent-core`（零依赖运行时内核）· `shared-schemas`（联邦契约）

## 禁止行为

- **勿提交真实 `.env` 文件**：所有 `.env` 已被 `.gitignore` 忽略，使用前按 `.env.example` 填值
- **勿提交大二进制资产**：模型权重、数据集均未入库，需本地自备
