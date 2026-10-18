"""MetaKnowledgeService：元知识构建服务（P0-1 实装 / P0-2 幂等重建）。

DDL/文档 + MetricConfig YAML → 列/指标/值三类 upsert 入 pgvector。

2026-10-18 审计（方案 §5.16-12 / D2）：此前 `build_from_tables` 只给列写
embedding，metric/value 的 embedding 无任何写入方 ⇒ `MetricRepository.recall`
（要求 embedding 非 NULL）对这两类恒空，"指标向量召回"从来没通过。三类
现在都有写入路径，且一律 upsert（重跑不翻倍）。

search_text 契约（001 DDL）：`value_tsvector` 是只从 `search_text` 生成的
列，漏写 = 该行全文路召不到——不是 bug，是契约。分词与召回查询侧同一套
（`Settings.tokenizer`），经 `nl2sql_service.tokenizer` 单源。
"""

from typing import Any

from agent_core.logging import get_logger

from nl2sql_service.clients.embedding_client_manager import BaseEmbedder
from nl2sql_service.conf.settings import get_settings
from nl2sql_service.repositories.postgres.meta.meta_repository import MetaRepository
from nl2sql_service.tokenizer import tokenize

logger = get_logger(__name__)


class MetaKnowledgeService:
    """元知识构建服务：列/指标/值三类写入（全部 upsert，可重复执行）。"""

    def __init__(
        self,
        meta_repo: MetaRepository,
        embedder: BaseEmbedder | None = None,
        tokenizer: str | None = None,
        vector_dim: int | None = None,
    ) -> None:
        self._meta_repo = meta_repo
        self._embedder = embedder
        # 缺省读 Settings：分词与向量维度是部署面决策，不该在调用方各写一份默认值
        settings = get_settings()
        self._tokenizer = tokenizer or settings.tokenizer
        self._vector_dim = vector_dim or settings.vector_dim

    async def build_from_tables(self, tables: list[dict[str, Any]]) -> dict[str, int]:
        """列行写入：table_comment / data_type / embedding。

        embedding 文本 = `{table_name} {column_name} {column_comment}`（与召回
        查询侧同一拼法，写入/查询单源）。
        """
        stats = {"inserted": 0, "updated": 0}
        for table in tables:
            table_name = table.get("table_name", "")
            table_comment = table.get("table_comment", "")
            for col in table.get("columns", []):
                column_name = col.get("column_name", "")
                column_comment = col.get("column_comment", "")
                data: dict[str, Any] = {
                    "table_name": table_name,
                    "table_comment": table_comment,
                    "column_name": column_name,
                    "column_comment": column_comment,
                    "data_type": col.get("data_type", ""),
                }
                if self._embedder is not None:
                    data["embedding"] = await self._embed(f"{table_name} {column_name} {column_comment}")
                if await self._meta_repo.save_column(data):
                    stats["inserted"] += 1
                else:
                    stats["updated"] += 1
        logger.info("column meta built: %s", stats)
        return stats

    async def build_from_metrics(self, metrics: list[dict[str, Any]]) -> dict[str, int]:
        """指标行写入：metric_name / desc / expr + embedding（name+desc+expr）。"""
        stats = {"inserted": 0, "updated": 0}
        for metric in metrics:
            data: dict[str, Any] = {
                "metric_name": metric.get("metric_name", ""),
                "metric_desc": metric.get("metric_desc", ""),
                "metric_expr": metric.get("metric_expr", ""),
            }
            if self._embedder is not None:
                data["embedding"] = await self._embed(
                    f"{data['metric_name']} {data['metric_desc']} {data['metric_expr']}"
                )
            if await self._meta_repo.save_metric(data):
                stats["inserted"] += 1
            else:
                stats["updated"] += 1
        logger.info("metric meta built: %s", stats)
        return stats

    async def build_from_values(self, values: list[dict[str, Any]]) -> dict[str, int]:
        """取值行写入：column_name / value / value_desc + search_text + embedding。

        search_text = 同一套分词后的单空格拼接 token（value_tsvector 的唯一
        输入）；embedding 文本 = `{column_name} {value} {value_desc}`。
        """
        stats = {"inserted": 0, "updated": 0}
        for item in values:
            column_name = item.get("column_name", "")
            value = item.get("value", "")
            value_desc = item.get("value_desc", "")
            data: dict[str, Any] = {
                "column_name": column_name,
                "value": value,
                "value_desc": value_desc,
                "search_text": " ".join(
                    tokenize(f"{column_name} {value} {value_desc}", self._tokenizer)
                ),
            }
            if self._embedder is not None:
                data["embedding"] = await self._embed(f"{column_name} {value} {value_desc}")
            if await self._meta_repo.save_value(data):
                stats["inserted"] += 1
            else:
                stats["updated"] += 1
        logger.info("value meta built: %s", stats)
        return stats

    async def prune(
        self,
        tables: list[dict[str, Any]],
        metrics: list[dict[str, Any]],
        values: list[dict[str, Any]],
    ) -> dict[str, int]:
        """删除源里已不存在的行（按 tenant/workspace/datasource 作用域）。

        与 upsert 合起来才是完整的幂等重建：只 upsert 不 prune，被删的取值
        永远留在索引里（H3 的另一半）。
        """
        column_keys = {
            (t.get("table_name", ""), c.get("column_name", ""))
            for t in tables
            for c in t.get("columns", [])
        }
        metric_keys = {m.get("metric_name", "") for m in metrics}
        value_keys = {(v.get("column_name", ""), v.get("value", "")) for v in values}
        stats = {
            "columns_deleted": await self._meta_repo.prune_columns(column_keys),
            "metrics_deleted": await self._meta_repo.prune_metrics(metric_keys),
            "values_deleted": await self._meta_repo.prune_values(value_keys),
        }
        logger.info("stale meta pruned: %s", stats)
        return stats

    async def _embed(self, text: str) -> list[float]:
        """向量化并校验维度；不等直接抛错，不静默写坏数据。

        001 DDL 的 `vector({{vector_dim}})` 按 `Settings.vector_dim` 建列，
        维度不符的向量 PG 直接拒插——但那是构建跑到一半才炸；这里在建库前
        就炸，错误信息还带"换模型要同步维度并全量重灌"的处置说明。
        """
        if self._embedder is None:  # 调用方已判空，防御性保持契约显式
            raise RuntimeError("embedder 未配置，无法写入 embedding")
        vector = await self._embedder.embed_query(text)
        if len(vector) != self._vector_dim:
            raise ValueError(
                f"embedding 维度 {len(vector)} 与 Settings.vector_dim={self._vector_dim} 不一致；"
                "换模型必须同步 VECTOR_DIM 并全量重灌（001 DDL 的 vector 列维度）"
            )
        return vector
