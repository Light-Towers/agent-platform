# -*- coding: utf-8 -*-
"""
Web 搜索 MCP 节点（zhiku 侧，使用 agent_core.tools.adapters.mcp.MCPToolAdapter）。

将原先硬编码的百炼 MCP 连接 / 工具名 / 任务记账改写为：通过 ``MCPToolAdapter`` 参数化
注入（mcp url / key / tool_name / 超时来自 zhiku 配置），任务记账（``add_running_task`` /
``add_done_task``）通过 ``on_start`` / ``on_done`` 回调注入，**去除对 task_utils 的顶层硬依赖
与 bailian 硬编码**。通用 MCP 调用逻辑已下沉到 agent_core，本文件只保留 zhiku 业务解析。
"""

import json
from typing import Any, Dict

from agent_core.logging import get_logger
from agent_core.tools.adapters.mcp import MCPToolAdapter
from agent_core.tracing import traced_span
from app.conf.bailian_mcp_config import mcp_config
from app.conf.retrieval_config import retrieval_cfg
from app.utils.task_utils import add_done_task, add_running_task

logger = get_logger(__name__)

_NODE_NAME = "node_web_search_mcp"


def _web_span_attrs(*args, result=None, **kwargs):
    """retrieval.web span 动态属性（hits / timeout_s）。"""
    result = result or {}
    hits = len(result.get("web_search_docs") or []) if isinstance(result, dict) else 0
    return {
        "hits": hits,
        "timeout_s": retrieval_cfg.channels.web.timeout_s,
    }


def _parse_web_pages(raw_text: str) -> Dict[str, Any]:
    """解析 MCP 原始 JSON（pages->docs）为统一 ``{web_search_docs: [...]}`` 结构。"""
    data = json.loads(raw_text)
    pages = data.get("pages") or []
    docs = []
    for item in pages:
        snippet = (item.get("snippet") or "").strip()
        url = (item.get("url") or "").strip()
        title = (item.get("title") or "").strip()
        if not snippet:
            continue
        docs.append({"title": title, "url": url, "snippet": snippet})
    return {"web_search_docs": docs} if docs else {}


# 构造 MCP 适配器：bailian 配置来自 zhiku 配置（非内核硬编码）；任务记账经回调注入。
_web_search_adapter = MCPToolAdapter(
    name="search_mcp",
    mcp_url=mcp_config.mcp_base_url,
    api_key=mcp_config.api_key,
    timeout_s=float(retrieval_cfg.channels.web.timeout_s),
    tool_name="bailian_web_search",
    arguments=lambda q, s: {"query": q, "count": 5},
    result_parser=_parse_web_pages,
    on_start=lambda s: add_running_task(s["session_id"], _NODE_NAME, s.get("is_stream")),
    on_done=lambda s: add_done_task(s["session_id"], _NODE_NAME, s.get("is_stream")),
)


@traced_span("retrieval.web", attributes_fn=_web_span_attrs)
def node_web_search_mcp(state):
    """
    LangGraph 同步节点函数：处理 MCP 搜索逻辑，作为整个搜索流程的入口。

    委托 ``MCPToolAdapter.invoke`` 执行远程调用并解析结果；
    返回 ``{web_search_docs: [...]}``（无结果返回 ``{}``）。
    """
    logger.info("---node_web_search_mcp 开始处理---")
    result = _web_search_adapter.invoke(state)
    logger.info("---node_web_search_mcp 处理结束---")
    return result


if __name__ == "__main__":
    # 测试：单独运行该文件验证 MCP 搜索功能是否正常。
    print("\n" + "=" * 50)
    print(">>> 启动 node_web_search_mcp 本地测试")
    print("=" * 50)

    test_state = {
        "session_id": "test_mcp_session",
        "rewritten_query": "HAK 180 在出厂默认状态下，若想在纸张上只把烫金膜转印到顶部 50 mm–170 mm 的局部区域，应在操作面板上如何设置",
        "is_stream": False,
    }

    try:
        result_state = node_web_search_mcp(test_state)
        print("\n" + "=" * 50)
        print(">>> 测试结果摘要:")
        search_results = result_state.get("web_search_docs", [])
        print(f"搜索结果数量: {len(search_results)}")
        if search_results:
            print("首条结果预览:")
            print(json.dumps(search_results[0], indent=2, ensure_ascii=False))
        else:
            print("未获取到搜索结果")
        print("=" * 50)
    except Exception as e:
        logger.exception("测试运行期间发生未捕获异常: %s", e)
