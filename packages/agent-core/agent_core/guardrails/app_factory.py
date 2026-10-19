# -*- coding: utf-8 -*-
"""统一 FastAPI app 工厂（P2 D-1=①，全局装配，方案 §3.2）。

kernel 拥有入站装配：**所有生产 FastAPI app 必须经 ``build_api_app`` 创建**，
由构造保证注册统一 500 脱敏 handler（``install_error_handlers``），杜绝各 app
手写 / 漏接。配合 ``scripts/lint_architecture.py`` 的"裸 ``FastAPI(`` 即 CI 失败"
门禁（§3.3），形成"工厂 + 门禁"双保险。

工厂只强制两个全局不变量：**错误处理**（统一 500 脱敏 handler）与**原生
telemetry 默认关闭**（R19：防 FastAPI ≥0.142 框架侧双 SERVER span 与 provider
覆盖；调用方可显式覆盖）。CORS / SecurityGuards 等差异化中间件仍由调用方拿到
返回值后自行 ``add_middleware``——不强推鉴权语义，避免改变各 app 现有对外行为。

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

    # R19（docs/plans/plan-r19-fastapi-native-telemetry-2026-10-19.md）：FastAPI ≥0.142
    # 原生 telemetry 默认开启，会 ① 与 kernel TracingMiddleware 对同一请求各建一个同名
    # SERVER span（互为兄弟）、② 自行 set_tracer_provider() 覆盖 kernel init_tracing
    # 装配的 provider（观测状态机被框架旁路）。工厂默认关原生 tracing；调用方确需开启
    # 时可经 fastapi_kwargs 显式覆盖（setdefault 不剥夺覆盖权）。
    fastapi_kwargs.setdefault("telemetry", {"tracing": False})
    app = FastAPI(**fastapi_kwargs)
    if install_handlers:
        install_error_handlers(app, get_request_id=get_request_id, logger=logger)
    if enable_tracing:
        from agent_core.tracing_middleware import TracingMiddleware

        app.add_middleware(TracingMiddleware)
    return app


__all__ = ["build_api_app"]
