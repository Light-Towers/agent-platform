"""Tool Result 压缩 + 外置（Plan-F Context Pipeline P1）。

工具返回原始结果可能远超大上下文预算。本模块提供：

- ``normalize_result``：dict / JSON / list / 原始对象统一为文本块；
- ``ToolResultCompressor``：超过 ``max_tokens`` 时产出「头尾 + 关键字段 + 引用句柄」的
  视图，完整结果写入外置目录（复用 workspace/session_dir 机制），context 只留引用；
- ``read_tool_result(ref)``：按需取回完整结果（后续轮次的元工具）。

设计要点：
- 摘要优先用确定性截断（零 LLM 成本），不做 LLM 摘要；
- 结构化结果（JSON/表格）按字段重要性裁剪（保留头几条、关键字段）；
- 工具本身不感知压缩——由执行器出口统一装饰（``compress_result`` 装饰器）。
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from pathlib import Path
from typing import Any

from agent_core.tokenizer import count_tokens

logger = logging.getLogger(__name__)

# 头尾保留比例（各留 40%，中间省略）
_HEAD_FRACTION = 0.4
_TAIL_FRACTION = 0.4
# 结构化结果（list of dict）保留前 N 条
_LIST_SAMPLE = 5


def normalize_result(result: Any) -> str:
    """把任意 Tool 返回值归一化为文本块。"""
    if result is None:
        return ""
    if isinstance(result, str):
        return result
    if isinstance(result, (dict, list, tuple)):
        try:
            return json.dumps(result, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            return str(result)
    return str(result)


def _head_tail(text: str, max_chars: int) -> str:
    """确定性截断：头尾各保留一定比例，中间用省略标记。"""
    if len(text) <= max_chars:
        return text
    head_len = int(max_chars * _HEAD_FRACTION)
    tail_len = int(max_chars * _TAIL_FRACTION)
    head = text[:head_len]
    tail = text[-tail_len:] if tail_len > 0 else ""
    return f"{head}\n...[省略 {len(text) - head_len - tail_len} 字符]...\n{tail}"


def _structured_view(result: list[dict] | dict, max_chars: int) -> str:
    """结构化结果的字段级裁剪：保留前几条记录与关键字段。"""
    if isinstance(result, list):
        sampled = result[:_LIST_SAMPLE]
        remaining = len(result) - len(sampled)
        text = json.dumps(sampled, ensure_ascii=False, default=str)
        if remaining > 0:
            text += f"\n...[其余 {remaining} 条省略]..."
    else:
        text = json.dumps(result, ensure_ascii=False, default=str)
    return _head_tail(text, max_chars)


def _make_ref(result: Any) -> str:
    """生成引用句柄：基于内容哈希 + 短随机后缀。"""
    digest = hashlib.sha256(normalize_result(result).encode("utf-8", "replace")).hexdigest()[:12]
    return f"tool_result_{digest}_{uuid.uuid4().hex[:6]}"


class ToolResultCompressor:
    """工具结果压缩器：超过阈值时外置完整结果，context 留裁剪视图 + ref。"""

    def __init__(
        self,
        max_tokens: int = 8192,
        store_dir: str | Path | None = None,
        model: str | None = None,
    ) -> None:
        self.max_tokens = max_tokens
        self.store_dir = Path(store_dir) if store_dir else None
        self.model = model

    def compress(self, result: Any) -> dict[str, Any]:
        """压缩工具结果。

        返回 ``{"text", "ref", "full_path", "truncated"}``：
        - 未超阈值：text=原始文本，truncated=False，无 ref；
        - 超阈值：text=裁剪视图 + 引用句柄，truncated=True，完整结果写入外置文件。
        """
        text = normalize_result(result)
        if not text:
            return {"text": "", "ref": "", "full_path": "", "truncated": False}

        tokens = count_tokens(text, self.model)
        if tokens <= self.max_tokens:
            return {"text": text, "ref": "", "full_path": "", "truncated": False}

        ref = _make_ref(result)
        max_chars = int(self.max_tokens * 1.5)  # 近似：token 预算 → 字符预算（保守）

        # 结构化结果按字段级裁剪，其余按头尾截断
        if isinstance(result, (list, dict)):
            view = _structured_view(result, max_chars)
        else:
            view = _head_tail(text, max_chars)
        view = f"{view}\n[完整结果已外置，引用: {ref}]"

        full_path = ""
        if self.store_dir is not None:
            try:
                self.store_dir.mkdir(parents=True, exist_ok=True)
                full_path = str(self.store_dir / f"{ref}.txt")
                Path(full_path).write_text(text, encoding="utf-8")
            except OSError as exc:
                logger.warning("tool_result 外置写入失败（降级为仅截断视图）: %s", exc)

        logger.info(
            "tool_result 压缩: %d tokens → %d tokens（ref=%s, 外置=%s）",
            tokens,
            count_tokens(view, self.model),
            ref,
            bool(full_path),
        )
        return {"text": view, "ref": ref, "full_path": full_path, "truncated": True}


def read_tool_result(ref: str, store_dir: str | Path) -> str:
    """按引用句柄取回完整工具结果（后续轮次的元工具）。

    ``ref`` 形如 ``tool_result_<hash>_<suffix>``。找不到时抛 FileNotFoundError。
    """
    path = Path(store_dir) / f"{ref}.txt"
    return path.read_text(encoding="utf-8")


def compress_result(max_tokens: int = 8192, store_dir: str | Path | None = None):
    """执行器出口装饰器：自动压缩 Skill/工具返回结果。

    用法::

        @compress_result(max_tokens=8192, store_dir=session_dir)
        async def search(**kwargs) -> Any: ...

    返回结构：{text, ref, full_path, truncated}（见 ``ToolResultCompressor.compress``）。
    """

    def decorator(fn):
        compressor = ToolResultCompressor(max_tokens=max_tokens, store_dir=store_dir)

        async def wrapper(*args, **kwargs):
            result = await fn(*args, **kwargs)
            return compressor.compress(result)

        return wrapper

    return decorator


_RE_REF = re.compile(r"^tool_result_[0-9a-f]{12}_[0-9a-f]{6}$")


def is_tool_result_ref(text: str) -> bool:
    """判断文本是否为工具结果引用句柄（供元工具识别）。"""
    return bool(_RE_REF.match(text.strip()))