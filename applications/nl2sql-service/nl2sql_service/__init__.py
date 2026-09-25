"""nl2sql_service - 通用 Text-to-SQL 数据分析服务。

12 节点 LangGraph 管线：NL → 关键词 → 表/列/指标/值召回 → SQL 生成 → 只读守卫 → 执行 → 纠正循环。
元知识（表/列/指标/值定义）参数化，可经配置文件或 API 入参注入，不硬编码特定业务表结构。
技术栈：FastAPI / LangGraph / pgvector / sqlglot / pydantic v2 / langchain 生态。
"""

__version__ = "0.1.0"
