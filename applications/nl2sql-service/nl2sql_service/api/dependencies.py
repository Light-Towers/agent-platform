"""依赖注入：lifespan 初始化 Postgres/pgvector 客户端 + DataAgentContext 单例。"""

from contextlib import asynccontextmanager

from agent_core.logging import get_logger
from fastapi import FastAPI

from nl2sql_service.agent.context import DataAgentContext
from nl2sql_service.agent.graph import build_graph
from nl2sql_service.agent.llm import build_llm
from nl2sql_service.conf.settings import get_settings
from nl2sql_service.services.query_service import QueryService

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    llm = build_llm()
    graph = build_graph()
    ctx = DataAgentContext()
    pools: list = []

    if settings.meta_db_enabled:
        from psycopg_pool import AsyncConnectionPool

        from nl2sql_service.clients.embedding_client_manager import build_embedder
        from nl2sql_service.clients.pgvector_client_manager import PgvectorClientManager
        from nl2sql_service.repositories.pgvector.column_repository import ColumnRepository
        from nl2sql_service.repositories.pgvector.metric_repository import MetricRepository
        from nl2sql_service.repositories.pgvector.value_repository import ValueRepository
        from nl2sql_service.repositories.postgres.meta.meta_repository import MetaRepository

        meta_pool = AsyncConnectionPool(settings.meta_db_dsn, open=False)
        await meta_pool.open()
        pools.append(meta_pool)
        pgvector_client = PgvectorClientManager(pool=meta_pool)
        embedder = build_embedder(
            settings.embedding_backend,
            api_key=settings.embedding_api_key,
            model=settings.embedding_model,
            base_url=settings.embedding_base_url,
        )
        ctx = DataAgentContext(
            embedding_client=embedder,
            column_repository=ColumnRepository(pgvector_client),
            metric_repository=MetricRepository(pgvector_client),
            value_repository=ValueRepository(pgvector_client),
            meta_repository=MetaRepository(pool=meta_pool, table_prefix=settings.table_prefix),
        )

    if settings.dw_db_enabled:
        from psycopg_pool import AsyncConnectionPool

        from nl2sql_service.repositories.postgres.dw.dw_repository import DwRepository

        dw_pool = AsyncConnectionPool(settings.dw_db_dsn, open=False)
        await dw_pool.open()
        pools.append(dw_pool)
        ctx.dw_repository = DwRepository(pool=dw_pool)

    app.state.llm = llm
    app.state.graph = graph
    app.state.context = ctx
    app.state.query_service = QueryService(graph=graph, context=ctx, llm=llm)
    app.state.settings = settings
    logger.info(
        "nl2sql-service 就绪 host=%s port=%d llm=%s meta_db=%s dw_db=%s",
        settings.host,
        settings.port,
        llm.enabled,
        settings.meta_db_enabled,
        settings.dw_db_enabled,
    )
    yield
    for pool in pools:
        await pool.close()
