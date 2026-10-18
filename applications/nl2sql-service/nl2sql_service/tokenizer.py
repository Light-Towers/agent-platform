# -*- coding: utf-8 -*-
"""分词器：召回查询侧与构建写入侧单源（方案 B1 的 search_text 契约）。

`nl2sql_value_info.search_text` 由构建方按**同一套分词**写入（001 DDL：
`value_tsvector` 只从 `search_text` 生成），查询侧 `build_tsquery` 收的又是
`extract_keywords` 切出来的 token——两侧必须是同一个分词器，否则写入的
lexeme 与查询的 lexeme 互相认不出（中文整串当词的老问题换一个形状复发）。

此前两份私有实现（`_bigram_tokenize` / `_jieba_tokenize`）内嵌在
`extract_keywords` 节点里，构建入口要"同一套分词"只能复制第三份——复制即
漂移，故收敛到本模块。
"""

from __future__ import annotations

from agent_core.logging import get_logger

logger = get_logger(__name__)

_jieba_warned = False


def bigram_tokenize(text: str) -> list[str]:
    """二字滑窗（默认分词）：中英文都可切，不依赖任何词表。"""
    return [text[i : i + 2] for i in range(len(text) - 1)] if len(text) > 1 else [text]


def jieba_tokenize(text: str) -> list[str]:
    """jieba 分词；缺包时告警降级 bigram（TOKENIZER=jieba 需 [tokenizer] extra）。

    不静默降级：静默降级会让"配了 jieba 实际跑 bigram"的部署看起来正常。
    """
    global _jieba_warned
    try:
        import jieba

        return list(jieba.cut(text))
    except ImportError:
        if not _jieba_warned:
            logger.warning("TOKENIZER=jieba 但未安装 jieba，已降级 bigram（pip install 'nl2sql-service[tokenizer]'）")
            _jieba_warned = True
        return bigram_tokenize(text)


def tokenize(text: str, tokenizer: str = "bigram") -> list[str]:
    """按 `Settings.tokenizer`（jieba | bigram）分词；空文本返回空列表。"""
    if not text:
        return []
    return jieba_tokenize(text) if tokenizer == "jieba" else bigram_tokenize(text)


__all__ = ["bigram_tokenize", "jieba_tokenize", "tokenize"]
