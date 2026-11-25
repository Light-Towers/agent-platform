# -*- coding: utf-8 -*-
"""兼容读件：分词唯一实现已上移到 `agent_runtime.retrieval_tokenizer`（ADR-0017 / T14）。

生产调用方必须直接 `from agent_runtime.retrieval_tokenizer import get_tokenizer`；
本模块只保留旧导入路径，供历史测试 / 脚本过渡使用，**不是第二实现**。
"""

from agent_runtime.retrieval_tokenizer import DICT_VERSION, get_tokenizer

tokenize = get_tokenizer().tokenize

__all__ = ["DICT_VERSION", "tokenize"]
