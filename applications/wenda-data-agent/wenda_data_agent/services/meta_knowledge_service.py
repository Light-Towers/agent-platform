"""MetaKnowledgeService：元知识构建服务。

DDL + 业务文档 → 列/指标/值信息抽取 + 向量化入 pgvector。
"""

from typing import Any

from agent_core.logging import get_logger

from wenda_data_agent.clients.embedding_client_manager import BaseEmbedder
from wenda_data_agent.repositories.postgres.meta.meta_repository import MetaRepository

logger = get_logger(__name__)


class MetaKnowledgeService:
    """元知识构建服务。"""

    def __init__(self, meta_repo: MetaRepository, embedder: BaseEmbedder | None = None) -> None:
        self._meta_repo = meta_repo
        self._embedder = embedder

    async def build_from_tables(self, tables: list[dict[str, Any]]) -> dict[str, int]:
        stats = {"columns": 0, "values": 0}
        for table in tables:
            for col in table.get("columns", []):
                await self._save_column(table["table_name"], col)
                stats["columns"] += 1
        logger.info("meta knowledge built: %s", stats)
        return stats

    async def build_from_metrics(self, metrics: list[dict[str, Any]]) -> int:
        count = 0
        for metric in metrics:
            await self._meta_repo.save_metric(metric)
            count += 1
        logger.info("metrics saved: %d", count)
        return count

    async def _save_column(self, table_name: str, col: dict[str, Any]) -> None:
        data = {
            "table_name": table_name,
            "column_name": col.get("column_name", ""),
            "column_comment": col.get("column_comment", ""),
            "data_type": col.get("data_type", ""),
        }
        if self._embedder is not None:
            text = f"{table_name} {col.get('column_name', '')} {col.get('column_comment', '')}"
            embedding = await self._embedder.embed_query(text)
            data["embedding"] = embedding
        await self._meta_repo.save_column(data)
