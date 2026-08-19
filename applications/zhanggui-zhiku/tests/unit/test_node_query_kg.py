# -*- coding: utf-8 -*-
"""KG 检索节点单测（zhanggui-zhiku）。

覆盖：
- query_kg：Neo4j 正常返回 / 无驱动降级 / 异常降级
- node_query_kg：空 query 跳过 / 有结果格式化 kg_chunks
- node_rrf：kg 通道接入 RRF 融合（结果进入 rrf_chunks）
不依赖真实 Neo4j / neo4j 驱动连接，全部用假 driver mock。
"""

from unittest.mock import patch

from app.clients import neo4j_utils
from app.query_process.agent.nodes.node_query_kg import node_query_kg
from app.query_process.agent.nodes.node_rrf import node_rrf


class _FakeRecord:
    def __init__(self, name, content, item_name):
        self._d = {"name": name, "content": content, "item_name": item_name}

    def get(self, key, default=None):
        return self._d.get(key, default)


class _FakeResult:
    def __init__(self, records):
        self._records = records

    def __iter__(self):
        return iter(self._records)


class _FakeSession:
    def __init__(self, records):
        self._records = records

    def run(self, cypher, params):
        return _FakeResult(self._records)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeDriver:
    def __init__(self, records):
        self._records = records

    def session(self, database=None):
        return _FakeSession(self._records)


def _kg_records():
    return [
        _FakeRecord("退款政策", "订单支付后7天内可申请退款", "售后手册"),
        _FakeRecord("运费规则", "满99元包邮，不足收10元运费", "售后手册"),
    ]


def test_query_kg_returns_normalized_docs():
    driver = _FakeDriver(_kg_records())
    with patch.object(neo4j_utils, "get_neo4j_driver", return_value=driver):
        docs = neo4j_utils.query_kg("退款", item_names=["售后手册"], limit=8)
    assert len(docs) == 2
    first = docs[0]
    assert first["chunk_id"].startswith("kg::")
    assert first["content"] == "订单支付后7天内可申请退款"
    assert first["item_name"] == "售后手册"
    assert first["score"] == 1.0


def test_query_kg_no_driver_returns_empty():
    with patch.object(neo4j_utils, "get_neo4j_driver", return_value=None):
        docs = neo4j_utils.query_kg("退款")
    assert docs == []


def test_query_kg_query_error_degrades_empty():
    class _BoomDriver:
        def session(self, database=None):
            raise RuntimeError("neo4j down")

    with patch.object(neo4j_utils, "get_neo4j_driver", return_value=_BoomDriver()):
        docs = neo4j_utils.query_kg("退款")
    assert docs == []


def test_node_query_kg_empty_query_skips():
    result = node_query_kg({"rewritten_query": "", "item_names": None, "session_id": "s1", "is_stream": False})
    assert result == {"kg_chunks": []}


def test_node_query_kg_formats_kg_chunks():
    driver = _FakeDriver(_kg_records())
    with patch.object(neo4j_utils, "get_neo4j_driver", return_value=driver):
        result = node_query_kg({
            "rewritten_query": "退款政策",
            "item_names": ["售后手册"],
            "session_id": "s1",
            "is_stream": False,
        })
    assert len(result["kg_chunks"]) == 2
    assert result["kg_chunks"][0]["content"].startswith("订单支付后")


def test_rrf_integrates_kg_channel():
    kg_docs = [{"chunk_id": "kg::售后手册::退款政策", "content": "7天退款", "item_name": "售后手册", "score": 1.0}]
    state = {
        "session_id": "s1",
        "is_stream": False,
        "embedding_chunks": [{"chunk_id": "e1", "content": "向量结果", "item_name": "手册"}],
        "hyde_embedding_chunks": [],
        "kg_chunks": kg_docs,
    }
    out = node_rrf(state)
    rrf = out.get("rrf_chunks") or []
    kg_ids = [d.get("chunk_id") for d in rrf]
    assert "kg::售后手册::退款政策" in kg_ids
