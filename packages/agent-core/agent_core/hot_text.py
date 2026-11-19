# -*- coding: utf-8 -*-
"""热加载文本配置：文件变了下次调用自动重读，不重启进程。

用途（2026-11-19 ADR 00XX）：路由 system prompt、词表等需要"改了不用重启"的
运行时文本。复用 nl2sql `_prompt.py:32-51` 已验证的 mtime 指纹模式，并做两点增强：

1. 指纹用 (st_mtime_ns, st_size, st_ino) 三元组——ConfigMap volume 挂载的
   ``..data`` 符号链接切换时，kubelet 换的是目标文件（inode 变），只靠 mtime/size
   可能在同尺寸同秒改写时漏检；带 inode 更稳。
2. ``stat()`` 跟随符号链接（默认行为），拿到的就是 CM 挂载切换后的真实文件身份。

线程安全靠 GIL：最坏多读一次盘，不会读到半截内容（read_text 原子性由 OS 保证）。
缓存按 **路径** 建模，同一路径内容变即失效；缺失文件返回 fallback 且不缓存
（这样文件后续被创建也能被感知）。

零依赖（只用 stdlib），放在 agent-core 供所有应用复用。
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# path → ((mtime_ns, size, ino), text)
_CACHE: dict[Path, tuple[tuple[int, int, int], str]] = {}


def load_hot_text(path: str | Path, fallback: str = "") -> str:
    """加载文本，文件内容变化时自动重读；缺失/不可读时返回 fallback。

    :param path: 文本文件路径（可以是 ConfigMap volume 里的符号链接路径）
    :param fallback: 文件缺失或读取失败时的兜底文本（不缓存，下次仍尝试读）
    :returns: 最新文本内容
    """
    p = Path(path)
    try:
        st = p.stat()  # 跟随符号链接 → CM ..data 切换后拿到真实文件身份
        identity = (st.st_mtime_ns, st.st_size, st.st_ino)
    except OSError:
        return fallback

    cached = _CACHE.get(p)
    if cached is not None and cached[0] == identity:
        return cached[1]

    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return fallback
    _CACHE[p] = (identity, text)
    return text


def clear_hot_text_cache() -> None:
    """清空缓存（仅供测试/eval 用；生产靠指纹自动失效，不调这个）。"""
    _CACHE.clear()


__all__ = ["load_hot_text", "clear_hot_text_cache"]
