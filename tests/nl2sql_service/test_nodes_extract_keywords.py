"""extract_keywords 节点单测（ADR-0017/T8：分词走共享单例）。"""

from agent_runtime.retrieval_tokenizer import get_tokenizer
from nl2sql_service.agent.nodes.extract_keywords import extract_keywords


def test_shared_tokenizer_chinese_word():
    tokens = get_tokenizer().tokenize("你好")
    assert tokens == ["你好"]


def test_shared_tokenizer_segmentation():
    tokens = get_tokenizer().tokenize("销售额")
    assert tokens == ["销售额"]  # 词典分词保留整词，不再按字符 bigram 切


async def test_extract_keywords_no_llm():
    state = {"query": "统计销售额", "tokenizer": "jieba"}
    result = await extract_keywords(state)
    assert "keywords" in result
    assert len(result["keywords"]) > 0
