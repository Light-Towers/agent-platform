"""SSE（Server-Sent Events）打包统一契约。

各应用 SSE 流格式不一致（agent_server 不带 event / zhanggui 带 event / opencode_gateway 不带 event），
统一到本模块。以 zhanggui 带 event 格式为准，event 为空时退化为无 event 行（向后兼容）。
"""

from __future__ import annotations

import json
from typing import Any


def sse_pack(event: str = "", data: dict[str, Any] | None = None) -> str:
    """打包 SSE 消息格式。

    :param event: 事件类型；空字符串时不输出 event 行（向后兼容无 event 的客户端）。
    :param data: 事件数据字典，JSON 序列化（ensure_ascii=False）。
    :return: SSE 格式字符串。

    格式：
        - event 非空：``event: {event}\\ndata: {json}\\n\\n``
        - event 空：``data: {json}\\n\\n``
    """
    payload = json.dumps(data or {}, ensure_ascii=False)
    if event:
        return f"event: {event}\ndata: {payload}\n\n"
    return f"data: {payload}\n\n"


__all__ = ["sse_pack"]
