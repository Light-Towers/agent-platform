# agent-platform — Agent 上下文文件

> 统一生产级 Agent 平台，本仓库为 **monorepo**（10 个独立 `pyproject.toml` 工程）。
> 根 `app/` 是一套单进程 Supervisor 平台；`deepagents/` 是并行的联邦网关编排系统（两者非上下级）。
> 各包经 `agent-core` / `shared-schemas` 共享内核与契约。
> 详细人类阅读指南见 `README.md`（含完整目录结构），本文件面向 AI agent，仅列要点。

## 目录结构

| 目录 | 定位 | 入口 |
|------|------|------|
| `app/` | 单进程 Supervisor 平台（统一 Agent 平台，本 README 主描述对象） | `app/main.py` |
| `deepagents/` | 联邦网关 + 3 子服务编排中枢（与 `app/` 并行，详见 `deepagents/README.md`） | `python -m api.server` |
| `agent-core/` | 零依赖运行时内核：tracing / guardrails / sql 守卫 / llm / memory | — |
| `shared-schemas/` | 联邦 4 服务共享 Pydantic 契约（QueryResponse 等） | — |
| `kefu-adapter/` | atguigu_ai REST → 统一契约适配层（:8002）；经 `KEFU_API_URL`(默认 :5005) 桥接**外部** atguigu_ai（仓库内无此代码）。迁移计划要求废弃但**尚未执行**（kefu-service 未升级 Agent Protocol 且 atguigu_ai 未下线，暂不能删） | `main.py` |
| `kefu-service/` | kefu 迁移版（deepagents + LangGraph），已实现且 CI 通过，但尚未接入网关（迁移需升级 Agent Protocol + 补齐 QueryResponse，非改 URL） | — |
| `wenda-adapter/` | wenda 老系统 SSE → JSON 适配层（:8001） | `main.py` |
| `wenda-data-agent/` | Text-to-SQL 数据分析垂直场景 | — |
| `zhanggui-zhiku/` | 掌柜智库：RAG 知识库导入 + 多路检索问答（:8900） | `zhanggui-zhiku` 脚本 |
| `dialogue-framework/` | LLM 对话系统框架基础设施 | `dialogue_framework.cli:main` |
| `tests/` | `app/` 单元测试（40 用例） | `pytest -q` |
| `eval/` | `app/` 评测门禁（12 条 golden） | `python -m eval.run_eval` |
| `docs/` | 设计文档 | — |

## 运行方式

```bash
pip install -e ".[dev]"          # 安装
pytest -q                         # 单元测试
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
