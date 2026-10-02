"""可观测性接线：Langfuse 可选，未配置/未安装时静默降级为空回调列表。

三态降级设计：已配置且可导入 -> 真实 handler；配置缺失或导入失败 -> 空列表，
主链路绝不因 tracing 失败而中断。
"""

import logging

logger = logging.getLogger(__name__)


def get_langfuse_callbacks(public_key: str = "", secret_key: str = "", host: str = "") -> list:
    """凭据由调用方注入（配置依赖倒置，Plan-F）；三者均为空视为未启用。

    S4（方案 §3.4 选项 a）：import 路径已迁 **v3+/v4 代际契约**（extras 声明 langfuse>=4）：
    v2 的 ``langfuse.callback.CallbackHandler(secret_key=, host=)`` 形态已不存在——
    v3+ 起凭据归 ``Langfuse`` 客户端构造，langchain 回调按 ``public_key`` 绑定客户端
    （langfuse 4.14 实测签名：CallbackHandler(*, public_key, trace_context)）。
    旧写法在真装 v3+/v4 时必 TypeError → 恒降级空列表，Langfuse 面对本仓从未真正可用（R1）。
    langfuse 未安装时仍静默降级空列表（opt-in，主链路绝不因 tracing 中断）。
    """
    if not (public_key and secret_key):
        return []
    try:
        from langfuse import Langfuse
        from langfuse.langchain import CallbackHandler

        # 凭据注册进客户端（构造离线，不阻塞网络）；handler 按 public_key 绑定该客户端
        Langfuse(public_key=public_key, secret_key=secret_key, host=host or None)
        return [CallbackHandler(public_key=public_key)]
    except Exception:
        logger.warning("Langfuse 初始化失败，已降级为无 trace 模式")
        return []
