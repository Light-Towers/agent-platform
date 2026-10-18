"""全文召回查询构造用例（2026-10-18，方案 P0-5③ / B1 前半）。

钉三件事：
1. 词之间是 **OR** 不是 AND——一个词没命中不该把整次召回归零；
2. token 里的 tsquery 元字符与单引号被正确转义，不抛语法错、不注入；
3. 空 token / 纯标点 token 被丢弃；词数有上限；空输入不碰数据库。
"""

from __future__ import annotations

from nl2sql_service.clients.pgvector_client_manager import PgvectorClientManager, build_tsquery


def test_or_join():
    assert build_tsquery(["销售", "售额"]) == "'销售' | '售额'"


def test_escape_single_quote():
    assert build_tsquery(["o'brien"]) == "'o''brien'"


def test_tsquery_metachars_are_quoted():
    # & | ! ( ) : * 在引号内按字面处理，不会改变布尔语义
    assert build_tsquery(["a&b", "c|d"]) == "'a&b' | 'c|d'"


def test_drop_empty_and_punctuation_only():
    assert build_tsquery(["", "   ", "，", "？", "销售"]) == "'销售'"


def test_split_whitespace_inside_token():
    assert build_tsquery(["上月 销售"]) == "'上月' | '销售'"


def test_cap_terms():
    assert build_tsquery([f"t{i}" for i in range(30)], max_terms=3) == "'t0' | 't1' | 't2'"


def test_empty_tokens():
    assert build_tsquery([]) == ""
    assert build_tsquery(["", "，"]) == ""


async def test_fulltext_search_skips_db_on_empty_tokens():
    """空 tokens 必须在取连接前返回，不能拼出 `to_tsquery('simple','')` 让 PG 报错。"""
    client = PgvectorClientManager(pool=None)
    assert await client.fulltext_search("nl2sql_value_info", "value_tsvector", []) == []
