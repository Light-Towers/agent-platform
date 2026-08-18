---
updated: 2026-08-13
---

# dialogue-framework

> LLM 驱动的对话系统框架基础设施。

## 来源

生产化改造自 `courses/zhanggui-kefu/legacy/`（尚硅谷课程快照，类 Rasa 架构，LangGraph 重写）。
课程快照保持 `courses/` 原样（gitignore 忽略），本目录为受 git 跟踪的生产化版本。

## 定位

对话系统框架基础设施（框架层），与 `kefu-service/`（业务层，客服业务精简应用）分层。
本规格不强制 `kefu-service` 复用，两者分层不冲突。

## 技术栈

- Python 3.11+（与全仓 `requires-python = ">=3.11"` 一致）
- FastAPI · LangGraph · pgvector · pydantic v2 · pydantic-settings
- langchain 生态（langchain-openai>=0.3）
- Postgres（psycopg）· JSON Store（开发零依赖）

## 模块

| 模块 | 职责 |
|------|------|
| `agent/` | LangGraph 异步 5 节点图（understand/policy/action/guard/response） |
| `dialogue_understanding/` | 命令系统/Flow 引擎/对话栈/生成器 |
| `core/` | Tracker/Domain/Slot/Store（JSON+Postgres 可插拔） |
| `policies/` | FlowPolicy/EnterpriseSearchPolicy/PolicyEnsemble |
| `retrieval/` | pgvector 检索 + Neo4j 可插拔图检索接口 |
| `nlg/` | NLG 生成器/响应重写/模板 |
| `training/` | 训练管线对齐 eval |
| `api/` | FastAPI 异步 server |
| `channels/` | REST/SocketIO/Console/inspect 多渠道 |
| `shared/` | config/llm/constants/exceptions/yaml_loader |
| `cli/` | init/run/train/export/inspect/shell 子命令 |

## 运行方式

```bash
pip install -e ./dialogue-framework
cp dialogue-framework/.env.example dialogue-framework/.env  # 填值
dialogue-framework run  # 或 python -m dialogue_framework run
```

## 与既有生产服务关系

- **kefu-service/**：业务层精简应用（硬编码关键词意图路由），本框架提供框架级通用对话能力，分层不强制复用。
- **agent-core/**：复用 `agent_core.logging` 日志基础设施。
- **shared-schemas/**：复用 `QueryResponse` 等契约。

## 本地自备资产

- BGE 模型权重（可选，约 390MB）：`EMBEDDING_BACKEND=langchain_huggingface` 时需本地放置到 `models/` 目录；缺省 `langchain_openai` 不需要。
