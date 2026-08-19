from agent_server.rag.store import rrf_merge, tokenize


def test_rrf_common_item_rises_to_top():
    merged = rrf_merge([[1, 2, 3], [2, 3, 4]], k=60)
    assert merged[0] == 2  # 两路都召回的 id 排最前


def test_rrf_empty_inputs():
    assert rrf_merge([[], []]) == []


def test_tokenize_chinese_bigram_and_english():
    tokens = tokenize("LangGraph 检查点")
    assert "langgraph" in tokens
    assert "检查" in tokens and "查点" in tokens


def test_tokenize_single_char():
    assert "表" in tokenize("表")
