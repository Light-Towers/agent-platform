# -*- coding: utf-8 -*-
"""
掌柜智库（Zhanggui Zhiku）统一服务入口。

将原本分散的「文件导入服务」与「查询服务」两个独立 FastAPI 应用，
合并为**单一** FastAPI 应用：通过 APIRouter 挂载，统一配置 CORS、日志与生命周期。
统一在 app.core.config 中完成一次 .env 加载，全项目共享配置单例。
"""

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.logger import logger
from app.core.tracing import init_tracing
from app.api.errors import register_exception_handlers, error_response
from app.api.middleware.security_guards import SecurityGuardsMiddleware
from app.api.import_router import router as import_router
from app.api.query_router import router as query_router
from app.conf.milvus_config import milvus_config
from eval.run_eval import compute_config_hash


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """应用生命周期：启动/关闭时执行一次性逻辑（此处仅记录启动日志）。"""
    logger.info("掌柜智库服务启动完成，监听 %s:%s", settings.app_host, settings.app_port)
    yield
    logger.info("掌柜智库服务已关闭")


def create_app() -> FastAPI:
    """
    应用工厂：构建并配置单一 FastAPI 实例。

    - 统一 CORS（来源来自 settings.cors_origins，逗号分隔）；
    - 挂载文件导入路由与查询路由；
    - 使用 lifespan 管理生命周期与日志。
    :return: 配置完成的 FastAPI 实例
    """
    app = FastAPI(
        title="掌柜智库 Zhanggui Zhiku",
        description="PDF/MD 知识库导入 + 多路检索问答一体化服务（RAG）",
        version="1.0.0",
        lifespan=lifespan,
    )

    # M5：统一错误响应（脱敏 {code, msg, request_id}）—— 注册在路由之前，对全路由生效
    register_exception_handlers(app)

    # M5：入站安全护栏 middleware（API Key 鉴权 + 入站限流 + 载荷大小护栏 + request_id 注入）。
    # ⚠️ 必须先于 CORS 添加：Starlette 中**后添加的 middleware 更外层**，
    # 保证 CORS 先处理 OPTIONS 预检，再进入鉴权/限流（预检不带自定义头，不会被 401 拦截）。
    app.add_middleware(
        SecurityGuardsMiddleware,
        api_key=settings.zhanggui_api_key,
        rate_limit_per_client=settings.zhanggui_rate_limit_per_client,
        rate_limit_global=settings.zhanggui_rate_limit_global,
        rate_limit_window_s=settings.zhanggui_rate_limit_window_s,
        max_body_bytes=settings.zhanggui_max_body_bytes,
        error_response=error_response,
    )

    # 跨域中间件：来源来自统一配置（CORS_ORIGINS 逗号分隔，去除空白项）
    allow_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # M4：OTel 全链路追踪初始化（幂等；未配置 endpoint / 未启用 / 未装 SDK 时自动 no-op，
    # 本地无 collector 也能正常运行 —— 方案 §8 no-op 降级铁律）。
    # 抽取后内核不再硬编码宿主配置，必须由宿主注入 config_hash / collection，
    # 否则 span 无法归因到检索配置版本（还原抽取前 _default_config_hash 的行为）。
    init_tracing(
        config_hash=compute_config_hash(),
        collection=milvus_config.chunks_collection,
    )

    # 挂载子路由（端点路径与原两个独立服务保持一致）
    app.include_router(import_router)  # /import.html, /upload, /status/{task_id}
    app.include_router(query_router)  # /chat.html, /health, /query, /stream/{session_id}, /history/{session_id}

    return app


# 全局应用实例：供 uvicorn 以 `app.main:app` 直接加载
app = create_app()


def run() -> None:
    """命令行入口（pyproject scripts：zhanggui-zhiku）：以 uvicorn 启动服务。"""
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=False,
    )


if __name__ == "__main__":
    run()
