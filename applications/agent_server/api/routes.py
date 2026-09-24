"""HTTP 端点聚合：/health、/query(SSE)、/import、/sql/train、/session/revert、/history、/api/executions。

D6: 按业务域拆分为子模块，本文件为聚合入口（main.py 仍 `from agent_server.api.routes import router`）。
"""

from fastapi import APIRouter

from agent_server.api.callback import router as callback_router
from agent_server.api.control import router as control_router
from agent_server.api.health_router import router as health_router
from agent_server.api.import_router import router as import_router
from agent_server.api.query_router import router as query_router
from agent_server.api.session_router import router as session_router
from agent_server.api.sql_router import router as sql_router

router = APIRouter()
router.include_router(health_router)
router.include_router(query_router)
router.include_router(import_router)
router.include_router(sql_router)
router.include_router(session_router)
router.include_router(control_router)
router.include_router(callback_router)
