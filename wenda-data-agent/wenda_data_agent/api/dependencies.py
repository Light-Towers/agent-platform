"""依赖注入：lifespan 初始化 Postgres/pgvector 客户端 + DataAgentContext 单例。"""

from contextlib import asynccontextmanager

from agent_core.logging import get_logger
from fastapi import FastAPI

from wenda_data_agent.agent.context import DataAgentContext
from wenda_data_agent.agent.graph import build_graph
from wenda_data_agent.agent.llm import build_llm
from wenda_data_agent.conf.settings import get_settings
from wenda_data_agent.services.query_service import QueryService

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    llm = build_llm()
    graph = build_graph()
    ctx = DataAgentContext()
    app.state.llm = llm
    app.state.graph = graph
    app.state.context = ctx
    app.state.query_service = QueryService(graph=graph)
    app.state.settings = settings
    logger.info(
        "wenda-data-agent 就绪 host=%s port=%d llm=%s meta_db=%s dw_db=%s",
        settings.host,
        settings.port,
        llm.enabled,
        settings.meta_db_enabled,
        settings.dw_db_enabled,
    )
    yield
