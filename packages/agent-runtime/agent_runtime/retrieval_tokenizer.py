"""中英混排检索分词：两个 Python 服务共用的唯一实现（ADR-0017 / T14）。

设计约束（不是普通工具函数）：
1. 单一实现：agent_server 与 nl2sql-service 只从 :func:`get_tokenizer` 取分词能力，
   禁止各自写正则切词或词典读取逻辑。
2. 单一事实源：词典版本、领域词、analyzer 配置均来自同包的
   ``retrieval_tokenizer_config.json``；Milvus analyzer 配置由 :func:`milvus_analyzer_params`
   从同一份源派生，避免"版本号一致但行为不等价"。
3. 缺依赖即失败：jieba 是 optional extra（``agent-runtime[tokenizer]``）；未安装时
   :func:`get_tokenizer` 抛 RuntimeError，不允许静默降级到字符二元组。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from importlib.resources import files
from typing import Any

_CONFIG: dict[str, Any] = json.loads(
    files("agent_runtime").joinpath("retrieval_tokenizer_config.json").read_text(encoding="utf-8")
)

DICT_VERSION: str = str(_CONFIG["version"])
DOMAIN_TERMS: tuple[str, ...] = tuple(str(term) for term in _CONFIG["domain_terms"])

_ASCII_WORD_RE = re.compile(r"[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*")
_CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]+")
_SEGMENT_RE = re.compile(r"[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*|[\u4e00-\u9fff]+")

_jieba_module: Any | None = None


def _load_jieba() -> Any:
    """惰性加载 jieba 并注入领域词；同进程只初始化一次。"""
    global _jieba_module
    if _jieba_module is None:
        try:
            import jieba  # noqa: PLC0415 —— optional extra，惰性导入是有意为之
        except ImportError as exc:
            raise RuntimeError(
                "检索分词需要 jieba：请安装 agent-runtime[tokenizer]（或部署镜像带 jieba>=0.42）；"
                "禁止静默降级到字符二元组"
            ) from exc
        for term in DOMAIN_TERMS:
            jieba.add_word(term)
        _jieba_module = jieba
    return _jieba_module


@dataclass(frozen=True)
class RetrievalTokenizer:
    """检索词项化器。无状态、线程安全（jieba 词典在初始化时一次性注入）。"""

    dict_version: str = DICT_VERSION

    def tokenize(self, text: str | None) -> list[str]:
        """中英混排文本 → 词项列表；英文整词保形并小写，中文走 jieba 词典切分。"""
        if not text:
            return []
        jieba = _load_jieba()
        tokens: list[str] = []
        for segment in _SEGMENT_RE.findall(text):
            if _ASCII_WORD_RE.fullmatch(segment):
                tokens.append(segment.lower())
                continue
            if _CJK_RUN_RE.fullmatch(segment):
                tokens.extend(token for token in jieba.cut(segment) if token and _CJK_RUN_RE.fullmatch(token))
        return tokens


_TOKENIZER = RetrievalTokenizer()


def get_tokenizer() -> RetrievalTokenizer:
    """唯一装配入口：三个服务只允许通过本函数获取检索分词能力。"""
    return _TOKENIZER


def milvus_analyzer_params() -> dict[str, Any]:
    """从同一份配置派生 Milvus jieba analyzer 参数。

    ``dict`` 里的自定义词典名由 T2 的 POC 确认注册方式后落定；此处按版本派生，
    避免配置文本与 Python 实现各写一份。
    """
    analyzer_cfg = _CONFIG["analyzer"]
    return {
        "tokenizer": {
            "type": "jieba",
            "dict": ["_default_", f"cn_en_tok_{DICT_VERSION}"],
            "mode": str(analyzer_cfg["mode"]),
            "hmm": bool(analyzer_cfg["hmm"]),
        },
        "filter": ["lowercase"],
    }


__all__ = ["DICT_VERSION", "DOMAIN_TERMS", "RetrievalTokenizer", "get_tokenizer", "milvus_analyzer_params"]
