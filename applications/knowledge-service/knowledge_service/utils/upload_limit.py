# -*- coding: utf-8 -*-
"""上传大小上限（P11 拍板 2026-11-11：100MB · KS 侧唯一硬校验）的纯实现。

为什么单独成模块：调用点 ``api/import_router.py`` 模块级 import ``main_graph``
（LangGraph 重型链），而 ``tests/unit`` 套件刻意零重型依赖（conftest 头部契约）
⇒ 把可单测的计数拷贝抽出来，端点只留接线。本模块纯 stdlib。

与护栏的配对关系（补记 9 发现 2）：``SecurityGuardsMiddleware`` 的 Content-Length
护栏（``KNOWLEDGE_MAX_BODY_BYTES``，缺省 128MB）是**粗护**（挡 10GB 级 DoS）；
精确校验在这里——边写边数、超限立即停写（10GB 级请求不该先占满磁盘），两层
不冲突也不互替。代理层（agent_server /kb/uploads）不重复设限（单一真相源）。
"""

from __future__ import annotations

from typing import Any

#: 上传字节数上限：100 MiB。直接覆盖直传与 agent_server 代理两条路径（最终都落 /upload）。
MAX_UPLOAD_BYTES = 100 * 1024 * 1024

#: 分块读大小：1MiB。100MB 文件 ≈ 100 次读，IO 次数可忽略；不整体缓冲进内存。
_CHUNK = 1024 * 1024


class UploadTooLarge(Exception):
    """单文件超出上限（在拷贝线程里抛，端点薄壳转 413 具名响应）。"""


def copy_with_limit(src: Any, dst: Any, max_bytes: int = MAX_UPLOAD_BYTES) -> int:
    """带上限的流式拷贝（同步，调用方跑在线程池）：分块读写，不整体缓冲进内存。

    :return: 实际写入字节数（调用方用于日志）。
    :raises UploadTooLarge: 累计超过 max_bytes 时立即停写并抛出（不落半截完整文件——
        已写入的残留在调用方清理或覆盖语义内，不假装拷贝成功）。
    """
    written = 0
    with open(dst, "wb") as out:
        while True:
            block = src.read(_CHUNK)
            if not block:
                break
            written += len(block)
            if written > max_bytes:
                raise UploadTooLarge(f"文件超出上传上限 {max_bytes} 字节")
            out.write(block)
    return written


__all__ = ["MAX_UPLOAD_BYTES", "UploadTooLarge", "copy_with_limit"]
