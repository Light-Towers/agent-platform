# -*- coding: utf-8 -*-
"""
逐路召回超时隔离（zhiku 侧桥接 ``agent_core.tools.guarded``）。

通用「逐路超时 + 失败降级 return {} + 异常路径 span 埋点」逻辑已抽取到
``agent_core.tools.guarded``；本模块保留 zhiku 专属的 ``retrieval_cfg`` 读取与
公共 API（``guarded_call`` / ``wrap_channel_node``），供 main_graph / tests 零改动使用。

说明：``retrieval_cfg`` 是**顶层模块级导入**（本模块 :17），测试要替换它须 patch
``fanout.retrieval_cfg`` 这个绑定本身，patch 源模块不会生效；另注意
``wrap_channel_node`` 在图构建期（``main_graph`` 被 import 时）就读取 enabled/timeout_s
并据此选择包装结果，运行期改配置不会重新装配节点。
"""

from typing import Any, Callable, Dict

from agent_core.logging import get_logger
from agent_core.tools.guarded import _DEFAULT_TIMEOUT_S, guarded_invoke, wrap_tool

from knowledge_service.conf.retrieval_config import retrieval_cfg

logger = get_logger(__name__)


def guarded_call(
    fn: Callable[[Dict[str, Any]], Any], channel: str, timeout_s: float, state: Dict[str, Any]
) -> Dict[str, Any]:
    """
    桥接 agent_core.tools.guarded.guarded_invoke（兼容原签名）。

    :param fn: 单路召回节点函数（同步，接收 state，返回 dict）
    :param channel: 通道名（embedding / hyde / kg / web）
    :param timeout_s: 逐路超时上界
    :param state: 检索图状态
    :return: 节点返回的 dict；超时 / 异常一律归一为 {}
    """
    return guarded_invoke(fn, state, timeout_s=timeout_s, channel=channel)


def wrap_channel_node(fn: Callable[[Dict[str, Any]], Any], channel: str) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    """
    将单路节点包装为「超时隔离 + 失败降级」节点（兼容原签名）。

    读取 zhiku ``retrieval_cfg.channels[channel]`` 的 enabled / timeout_s；
    缺失 / ``enabled=false`` 时直接返回 ``{}``（跳过该路）。
    """
    # retrieval_cfg 为模块级导入，测试通过 monkeypatch 替换。
    ch_cfg = retrieval_cfg.channels.get(channel) if isinstance(retrieval_cfg.channels, dict) else None
    if ch_cfg is None or not getattr(ch_cfg, "enabled", True):
        logger.info("channel %s disabled, skip recall", channel)
        return lambda state: {}
    timeout_s = float(getattr(ch_cfg, "timeout_s", _DEFAULT_TIMEOUT_S))
    return wrap_tool(fn, enabled=True, timeout_s=timeout_s, channel=channel)


__all__ = ["guarded_call", "wrap_channel_node"]
