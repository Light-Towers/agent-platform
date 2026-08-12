# agent-platform — Agent 上下文文件

> 统一生产级 Agent 平台。产品代码在 `app/`，测试在 `tests/`，评测在 `eval/`。
> 详细人类阅读指南见 `README.md`，本文件面向 AI agent。

## 目录结构

| 目录 | 定位 | 入口 |
|------|------|------|
| `app/` | **产品主体**（统一 Agent 平台） | `app/main.py` |
| `tests/` | 单元测试（40 用例） | `pytest -q` |
| `eval/` | 评测门禁（12 条 golden） | `python -m eval.run_eval` |
| `docs/` | 设计文档 | — |

## 运行方式

```bash
pip install -e ".[dev]"          # 安装
pytest -q                         # 单元测试
python -m eval.run_eval           # 评测门禁
DATABASE_URL= uvicorn app.main:app --port 8000  # 零依赖冒烟
```

## 技术栈

- Python 3.10+
- FastAPI · LangGraph · pgvector · sqlglot · pydantic v2

## 禁止行为

- **勿提交真实 `.env` 文件**：所有 `.env` 已被 `.gitignore` 忽略，使用前按 `.env.example` 填值
- **勿提交大二进制资产**：模型权重、数据集均未入库，需本地自备
