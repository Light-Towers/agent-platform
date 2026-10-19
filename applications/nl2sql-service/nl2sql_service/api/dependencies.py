"""依赖注入：lifespan 初始化 Postgres/pgvector 客户端 + DataAgentContext 单例。

连接池一律走 `agent_runtime.pool_factory.create_pool`（2026-10-18 上移的共享件，
方案 §5.12.2）：显式 min/max/timeout/statement_timeout，不再用 psycopg_pool 默认值
（`max_size=None` ⇒ 无限新建后端，天花板交给 PG `max_connections`）。
业务数仓池额外开启连接级只读。
池实例登记在 `app.state.pools`（name → pool），供 `GET /api/pools` 出可观测快照，
关闭时按同一份登记逐个 close。
"""

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
    registry: dict = {}

    if settings.meta_db_enabled:
        from agent_runtime.pool_factory import create_pool

        from nl2sql_service.clients.embedding_client_manager import build_embedder
        from nl2sql_service.clients.pgvector_client_manager import PgvectorClientManager
        from nl2sql_service.repositories.pgvector.column_repository import ColumnRepository
        from nl2sql_service.repositories.pgvector.example_repository import ExampleRepository
        from nl2sql_service.repositories.pgvector.metric_repository import MetricRepository
        from nl2sql_service.repositories.pgvector.value_repository import ValueRepository
        from nl2sql_service.repositories.postgres.meta.meta_repository import MetaRepository

        meta_pool = create_pool(
            dsn=settings.meta_db_dsn,
            name="meta",
            min_size=settings.meta_db_pool_min_size,
            max_size=settings.meta_db_pool_max_size,
            timeout=settings.meta_db_pool_timeout,
            statement_timeout_ms=settings.meta_db_statement_timeout_ms,
            read_only=False,  # 元知识库有构建入口要写
        )
        await meta_pool.open()
        registry["meta"] = meta_pool
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
            # 范例库（A 方案 Stage ②）：004 未应用时向量查询会炸——与 table_stats
            # 同构静默降级（缺表不是启动故障，只是没有 few-shot）。
            example_repository=ExampleRepository(pgvector_client),
            meta_repository=MetaRepository(pool=meta_pool, table_prefix=settings.table_prefix),
        )

    if settings.dw_db_enabled:
        from agent_runtime.pool_factory import create_pool

        from nl2sql_service.repositories.postgres.dw.dw_repository import DwRepository

        dw_pool = create_pool(
            dsn=settings.dw_db_dsn,
            name="dw",
            min_size=settings.dw_db_pool_min_size,
            max_size=settings.dw_db_pool_max_size,
            timeout=settings.dw_db_pool_timeout,
            statement_timeout_ms=settings.dw_db_statement_timeout_ms,
            # 连接级只读（可关）：这个池上跑的是 LLM 生成的 SQL。DwRepository 每次
            # 执行还有一道事务级 SET LOCAL（#119，退出即撤）——本开关置 false 时
            # 语句级仍生效，但只剩它 + 账号 GRANT SELECT 兜底，勿轻易关。
            read_only=settings.dw_db_connection_read_only,
        )
        await dw_pool.open()
        registry["dw"] = dw_pool
        dw_repository = DwRepository(pool=dw_pool)
        ctx.dw_repository = dw_repository
        # 取值只读探针（P0-9 单入口）：只在 dw 池就绪时装配
        from nl2sql_service.services.value_resolver import (
            LinkablePolicy,
            ValueResolver,
            ValueResolverConfig,
        )

        ctx.value_resolver = ValueResolver(
            dw_repository=dw_repository,
            config=ValueResolverConfig(
                enabled=settings.value_probe_enabled,
                probe_limit=settings.value_probe_limit,
                statement_timeout_ms=settings.value_probe_timeout_ms,
                concurrency=settings.value_probe_concurrency,
                cache_ttl_seconds=settings.value_probe_cache_ttl_seconds,
                snapshot_sql=settings.source_snapshot_sql,
                partition_column=settings.dw_partition_column,
                latest_partition_sql=settings.dw_latest_partition_sql,
                partition_required=settings.dw_partition_required,
            ),
            linkable=LinkablePolicy(allowlist=settings.linkable_columns),
        )

    app.state.pools = registry

    # 数据源注册表（P1-3/P1-4/P1-6）：单源部署按 dw DSN 建默认源；方言按
    # scheme 探测（mysql:// → mysql）。未配 dw 时不建（QueryService 回落默认）。
    if settings.dw_db_enabled:
        from nl2sql_service.services.datasource import build_default_registry, detect_dialect

        dialect = settings.datasource_dialect or detect_dialect(settings.dw_db_dsn)
        ctx.datasources = build_default_registry(
            datasource_id=settings.datasource_id,
            dialect=dialect,
            label=settings.datasource_label,
        )

    # 表统计（P0-3 副产物 → 生成期聚合引导）：002 未应用时静默跳过——
    # 缺表不是启动故障，只是没有聚合引导（不猜表大小）。
    if ctx.meta_repository is not None:
        try:
            ctx.table_stats = await ctx.meta_repository.list_table_stats()
        except Exception:  # noqa: BLE001 - 表未建/库不可用都不该阻断启动
            logger.info("table stats unavailable（002 未应用？），聚合引导关闭", exc_info=True)

    app.state.llm = llm
    app.state.graph = graph
    app.state.context = ctx
    app.state.query_service = QueryService(graph=graph, context=ctx, llm=llm)
    app.state.settings = settings

    # 负载隔离（P1-5/S-6）：全 0 配置 = 不建闸（LoadGuard 内部按 0 短路）。
    from nl2sql_service.services.load_guard import LoadGuard, LoadGuardConfig

    ctx.load_guard = LoadGuard(
        LoadGuardConfig(
            max_concurrency=settings.query_max_concurrency,
            rate_limit_per_min=settings.query_rate_limit_per_min,
            acquire_timeout=settings.query_acquire_timeout,
        )
    )
    logger.info(
        "nl2sql-service 就绪 host=%s port=%d llm=%s meta_db=%s dw_db=%s pools=%s",
        settings.host,
        settings.port,
        llm.enabled,
        settings.meta_db_enabled,
        settings.dw_db_enabled,
        {name: f"{p.min_size}-{p.max_size}" for name, p in registry.items()},
    )
    yield
    for pool in registry.values():
        await pool.close()
