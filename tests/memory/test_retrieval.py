from agent_runtime.retrieval_tokenizer import get_tokenizer
from agent_server.rag.store import rrf_merge


def test_rrf_common_item_rises_to_top():
    merged = rrf_merge([[1, 2, 3], [2, 3, 4]], k=60)
    assert merged[0] == 2  # 两路都召回的 id 排最前


def test_rrf_empty_inputs():
    assert rrf_merge([[], []]) == []


def test_shared_tokenizer_chinese_word_and_english():
    # ADR-0017/T7：中文改为词典分词，不再断言字符 bigram。
    tokens = get_tokenizer().tokenize("LangGraph 检查点")
    assert "langgraph" in tokens
    assert "检查点" in tokens
    assert "检查" not in tokens and "查点" not in tokens


def test_shared_tokenizer_single_char():
    assert "表" in get_tokenizer().tokenize("表")
