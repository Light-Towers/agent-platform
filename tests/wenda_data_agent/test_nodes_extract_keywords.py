"""extract_keywords 节点单测。"""


from wenda_data_agent.agent.nodes.extract_keywords import _bigram_tokenize, extract_keywords


def test_bigram_tokenize():
    assert _bigram_tokenize("你好") == ["你好"]
    assert _bigram_tokenize("销售额") == ["销售", "售额"]


async def test_extract_keywords_no_llm():
    state = {"query": "统计销售额", "tokenizer": "bigram"}
    result = await extract_keywords(state)
    assert "keywords" in result
    assert len(result["keywords"]) > 0
