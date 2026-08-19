"""可观测性接线：Langfuse 可选，未配置/未安装时静默降级为空回调列表。

三态降级设计：已配置且可导入 -> 真实 handler；配置缺失或导入失败 -> 空列表，
主链路绝不因 tracing 失败而中断。
"""

import logging

logger = logging.getLogger(__name__)


def get_langfuse_callbacks(public_key: str = "", secret_key: str = "", host: str = "") -> list:
    """凭据由调用方注入（配置依赖倒置，Plan-F）；三者均为空视为未启用。"""
    if not (public_key and secret_key):
        return []
    try:
        from langfuse.callback import CallbackHandler

        handler = CallbackHandler(
            public_key=public_key,
            secret_key=secret_key,
            host=host,
        )
        return [handler]
    except Exception:
        logger.warning("Langfuse 初始化失败，已降级为无 trace 模式")
        return []
