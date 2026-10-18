"""DataAgentContext：管线上下文（lifespan 创建单例）。"""

from typing import Any

from nl2sql_service.clients.embedding_client_manager import BaseEmbedder
from nl2sql_service.repositories.pgvector.column_repository import ColumnRepository
from nl2sql_service.repositories.pgvector.metric_repository import MetricRepository
from nl2sql_service.repositories.pgvector.value_repository import ValueRepository


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
        table_stats: list[dict[str, Any]] | None = None,
        value_resolver: Any = None,
        datasources: Any = None,
        load_guard: Any = None,
    ) -> None:
        self.embedding_client = embedding_client
        self.column_repository = column_repository
        self.metric_repository = metric_repository
        self.value_repository = value_repository
        self.meta_repository = meta_repository
        self.dw_repository = dw_repository
        # 漂移检测（P0-3）产出的表行数估值，供生成期聚合引导；无则不引导
        self.table_stats = table_stats or []
        # 取值只读探针单入口（P0-9）；None = 未配置 dw 池，不做源侧取值匹配
        self.value_resolver = value_resolver
        # 数据源注册表（P1-3/P1-4/P1-6）：请求 datasource_id → 方言/口径标签。
        # None = 未装配（老部署/测试），QueryService 回落单源默认。
        self.datasources = datasources
        # 负载隔离（P1-5/S-6）：并发闸 + 限流。None = 关闭（全 0 配置）。
        self.load_guard = load_guard
