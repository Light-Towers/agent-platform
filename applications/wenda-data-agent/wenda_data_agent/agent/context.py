"""DataAgentContext：管线上下文（lifespan 创建单例）。"""

from typing import Any

from wenda_data_agent.clients.embedding_client_manager import BaseEmbedder
from wenda_data_agent.repositories.pgvector.column_repository import ColumnRepository
from wenda_data_agent.repositories.pgvector.metric_repository import MetricRepository
from wenda_data_agent.repositories.pgvector.value_repository import ValueRepository


class DataAgentContext:
    """管线上下文：持有所有客户端和仓储单例。"""

    def __init__(
        self,
        embedding_client: BaseEmbedder | None = None,
        column_repository: ColumnRepository | None = None,
        metric_repository: MetricRepository | None = None,
        value_repository: ValueRepository | None = None,
        meta_repository: Any = None,
        dw_repository: Any = None,
    ) -> None:
        self.embedding_client = embedding_client
        self.column_repository = column_repository
        self.metric_repository = metric_repository
        self.value_repository = value_repository
        self.meta_repository = meta_repository
        self.dw_repository = dw_repository
