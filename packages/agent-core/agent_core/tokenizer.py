"""统一 token 计数：把文本换算成模型真实消费的 token 数。

上下文窗口管理（压缩 / 预算分配 / overrun 防护）必须先有"尺子"才能精确。
本模块提供 ``count_tokens(text)`` 单一入口：

- OpenAI 系模型（gpt-4o / gpt-4 / o1 等）：优先用 ``tiktoken`` 精确计数；
  tiktoken 未安装时降级到启发式估算。
- 非 OpenAI 模型（qwen / 兼容 OpenAI 的国产模型等）：精确 tokenizer 不在本仓库依赖内，
  统一走启发式估算（中文 ~1 字/token，英文 ~0.75 词/token，取字符数 / 1.5 作上界）。

设计原则（对齐 agent-core 零依赖内核定位）：
- 不强制依赖 tiktoken；导入失败静默降级，不抛异常、不阻断主链路。
- 单例缓存 encoding，避免重复构造开销。
- ``count_messages`` 供 LangChain / dict 混合消息列表复用。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# tiktoken 为可选依赖（仅 OpenAI 系精确计数需要）。
try:  # pragma: no cover - 依赖可选
    import tiktoken

    _TIKTOKEN_AVAILABLE = True
except Exception:  # noqa: BLE001 - 导入失败直接降级
    _TIKTOKEN_AVAILABLE = False
    tiktoken = None  # type: ignore[assignment]


# OpenAI 系模型名前缀 → 对应 encoding 名。
_OPENAI_ENCODINGS = {
    "gpt-4o": "o200k_base",
    "gpt-4": "cl100k_base",
    "gpt-3.5": "cl100k_base",
    "o1": "o200k_base",
    "o3": "o200k_base",
    "text-embedding": "cl100k_base",
}

# 非 OpenAI 模型走启发式估算时的除子（字符数 / 该值 ≈ token 数）。
_HEURISTIC_DIVISOR = 1.5


def _resolve_encoding(model: str | None):
    """返回 tiktoken Encoding，或 None（不可用时 / 非 OpenAI 模型）。

    仅对已知 OpenAI 系模型前缀精确匹配；其他模型（qwen / 国产 / 兼容 OpenAI 协议
    但非 OpenAI 编码表的模型）一律返回 None，走启发式估算——不能用 OpenAI 的 BPE
    编码表去数非 OpenAI 模型的 token，否则计数无意义。
    """
    if not _TIKTOKEN_AVAILABLE or model is None:
        return None
    for prefix, enc_name in _OPENAI_ENCODINGS.items():
        if model.startswith(prefix):
            try:
                return tiktoken.get_encoding(enc_name)
            except Exception:  # noqa: BLE001
                return None
    # 非 OpenAI 模型：不调用 encoding_for_model 兜底（会误用 OpenAI 编码表）。
    return None


# encoding 单例缓存：model 名 -> Encoding。
_ENCODING_CACHE: dict[str, Any] = {}


def get_tokenizer(model: str | None = None) -> Any:
    """获取 tokenizer。

    返回 tiktoken Encoding（OpenAI 系且可用时），否则返回 ``None``
    表示走启发式估算路径。
    """
    if model is None or not _TIKTOKEN_AVAILABLE:
        return None
    if model in _ENCODING_CACHE:
        return _ENCODING_CACHE[model]
    enc = _resolve_encoding(model)
    _ENCODING_CACHE[model] = enc
    return enc


def count_tokens(text: str, model: str | None = None) -> int:
    """统计 ``text`` 的 token 数。

    - OpenAI 系且有 tiktoken：精确计数；
    - 其他情况：启发式 ``len(text) / 1.5`` 上界估计。
    """
    if not text:
        return 0
    enc = get_tokenizer(model)
    if enc is not None:
        try:
            return len(enc.encode(text))
        except Exception:  # noqa: BLE001 - 极端输入防御
            logger.debug("tiktoken 编码失败，降级启发式: %r", text[:32])
    return int(len(text) / _HEURISTIC_DIVISOR)


def _msg_content(msg: Any) -> str:
    """从 LangChain 消息 / dict / 原始对象提取文本内容。"""
    if isinstance(msg, dict):
        content = msg.get("content", "")
        return content if isinstance(content, str) else str(content)
    # LangChain BaseMessage 有 .content
    content = getattr(msg, "content", None)
    if content is None:
        return str(msg)
    return content if isinstance(content, str) else str(content)


def count_messages(messages: list[Any], model: str | None = None) -> int:
    """统计消息列表总 token 数。"""
    return sum(count_tokens(_msg_content(m), model) for m in messages)


def estimate_tokens(messages: list[Any], model: str | None = None) -> int:
    """``count_messages`` 的语义别名（保留向后兼容）。"""
    return count_messages(messages, model)
