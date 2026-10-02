# -*- coding: utf-8 -*-
"""统一 FastAPI app 工厂（P2 D-1=①，全局装配，方案 §3.2）。

kernel 拥有入站装配：**所有生产 FastAPI app 必须经 ``build_api_app`` 创建**，
由构造保证注册统一 500 脱敏 handler（``install_error_handlers``），杜绝各 app
手写 / 漏接。配合 ``scripts/lint_architecture.py`` 的"裸 ``FastAPI(`` 即 CI 失败"
门禁（§3.3），形成"工厂 + 门禁"双保险。

工厂只强制**错误处理这一全局不变量**：CORS / SecurityGuards 等差异化中间件
仍由调用方拿到返回值后自行 ``add_middleware``——不强推鉴权语义，避免改变各 app
现有对外行为。

需 fastapi（``web`` extra）。
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from agent_core.guardrails.errors import install_error_handlers


def build_api_app(
    *,
    get_request_id: Optional[Callable[[], str]] = None,
    logger: Optional[Any] = None,
    install_handlers: bool = True,
    enable_tracing: bool = False,
    **fastapi_kwargs: Any,
) -> Any:
    """创建 FastAPI app 并装配统一异常处理器。

    ``fastapi_kwargs`` 原样透传给 ``FastAPI(...)``（title / version / lifespan /
    docs_url 等），各 app 差异化配置无侵入。返回 app 后可继续 add_middleware /
    include_router。

    ``enable_tracing=True`` 时装配 kernel 统一 ``TracingMiddleware``（观测方案
    §3.2，S2）：每个 HTTP 请求创建 server span，覆盖 429/409/cache_hit/断连
    全旁路（R10）；未 init 启用时逐请求门控透传、零开销（opt-in 铁律）。
    默认关闭——对外 span 数量属行为变更，按 app 逐个开启（兼容顺序见方案 §4）。
    """
    from fastapi import FastAPI

    app = FastAPI(**fastapi_kwargs)
    if install_handlers:
        install_error_handlers(app, get_request_id=get_request_id, logger=logger)
    if enable_tracing:
        from agent_core.tracing_middleware import TracingMiddleware

        app.add_middleware(TracingMiddleware)
    return app


__all__ = ["build_api_app"]
