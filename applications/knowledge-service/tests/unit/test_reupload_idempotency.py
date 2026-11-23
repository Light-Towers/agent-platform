# -*- coding: utf-8 -*-
"""重新上传幂等清理（fake Milvus client，零 Milvus 依赖）。

钉四件事（对应主方案 §3.4 的 F-1/F-9/F-11/F-13）：
1. 同名重传按 (tenant, kid, source_doc) 删旧，filter 三谓词齐全；
2. 文件名含引号/反斜杠 → filter 已转义、不抛；
3. source_doc 空 → 不删 + 告警 + 返回 0；
4. 轻量只读：query 的 output_fields 仅含 chunk_id（不含向量）。
"""
from __future__ import annotations

from knowledge_service.utils.kb_delete import clear_chunks_for_reupload


class _FakeClient:
    def __init__(self, rows=None, collection_exists=True):
        self.rows = rows if rows is not None else [{"chunk_id": 1}, {"chunk_id": 2}]
        self.collection_exists = collection_exists
        self.query_calls = []
        self.delete_calls = []
        self.flush_calls = 0

    def has_collection(self, collection_name):
        return self.collection_exists

    def query(self, collection_name, filter, output_fields, limit):
        self.query_calls.append({"filter": filter, "output_fields": output_fields, "limit": limit})
        return list(self.rows)

    def delete(self, collection_name, filter):
        self.delete_calls.append(filter)

    def flush(self, collection_name):
        self.flush_calls += 1


COLL = "kb_chunks_v1_bge_m3"


def test_reupload_deletes_by_tenant_kid_source_doc() -> None:
    client = _FakeClient()
    n = clear_chunks_for_reupload(client, COLL, "t1", "kb-1", "手册.pdf")
    assert n == 2
    assert len(client.delete_calls) == 1
    f = client.delete_calls[0]
    assert 'tenant_id == "t1"' in f
    assert 'knowledge_id == "kb-1"' in f
    assert 'source_doc == "手册.pdf"' in f
    assert 'status !=' not in f  # H-1 修法 b：重传删全部历史版本（含 REVOKED），不带状态过滤


def test_special_chars_escaped() -> None:
    client = _FakeClient(rows=[{"chunk_id": 1}])
    # 文件名含双引号与反斜杠
    clear_chunks_for_reupload(client, COLL, "t1", "kb-1", 'a"b\\c.pdf')
    f = client.delete_calls[0]
    assert 'a\\"b\\\\c.pdf' in f  # " -> \", \ -> \\


def test_empty_source_doc_skips_delete() -> None:
    client = _FakeClient()
    assert clear_chunks_for_reupload(client, COLL, "t1", "kb-1", "   ") == 0
    assert client.query_calls == []
    assert client.delete_calls == []


def test_reads_only_chunk_id() -> None:
    client = _FakeClient()
    clear_chunks_for_reupload(client, COLL, "t1", "kb-1", "手册.pdf")
    assert client.query_calls[0]["output_fields"] == ["chunk_id"]


def test_no_old_chunks_no_delete() -> None:
    client = _FakeClient(rows=[])
    assert clear_chunks_for_reupload(client, COLL, "t1", "kb-1", "手册.pdf") == 0
    assert client.delete_calls == []


def test_collection_missing_no_delete() -> None:
    client = _FakeClient(collection_exists=False)
    assert clear_chunks_for_reupload(client, COLL, "t1", "kb-1", "手册.pdf") == 0
    assert client.delete_calls == []


def test_reupload_deletes_revoked_old_version_too() -> None:
    """H-1：重传把 REVOKED 旧版也纳入清理范围（filter 无 status 子句）。

    这样重传后该 source_doc 只剩新活跃版；后续 restore 不会再复活旧内容，杜绝新旧并存。
    """
    # query 返回融合活跃 + REVOKED 的切片（模拟"下线过又重传"的库）
    client = _FakeClient(rows=[{"chunk_id": 1}, {"chunk_id": 2}, {"chunk_id": 3}])
    n = clear_chunks_for_reupload(client, COLL, "t1", "kb-1", "手册")
    assert n == 3
    f = client.delete_calls[0]
    # 关键：filter 里没有任何 status 条件 ⇒ delete 覆盖全部历史版本
    assert "status" not in f
    assert 'source_doc == "手册"' in f


def test_node_wires_cleanup_with_state_identity(monkeypatch) -> None:
    """接线断言（M3）：node_import_milvus 必须用 state 的 tenant/kid/file_title 调清理。

    只 patch 步骤函数，不连 Milvus——钉"调用点"本身，防有人改回 item_name 清理或漏接。
    """
    from knowledge_service.import_process.agent.nodes import node_import_milvus as nim

    fake_client = object()
    monkeypatch.setattr(nim, "step_1_check_input", lambda state: ([{"x": 1}], 1024))
    monkeypatch.setattr(nim, "step_2_prepare_collection", lambda dim: fake_client)
    monkeypatch.setattr(nim, "step_4_insert_data", lambda client, chunks, state: chunks)
    monkeypatch.setattr(nim, "step_5_register_index", lambda chunks, state=None: None)
    monkeypatch.setattr(nim, "add_running_task", lambda *a, **k: None)

    calls = []

    def _fake_clear(client, collection, tenant, kid, source_doc):
        calls.append((client, collection, tenant, kid, source_doc))
        return 3

    monkeypatch.setattr(nim, "clear_chunks_for_reupload", _fake_clear)

    state = {
        "task_id": "t-1",
        "file_title": "手册",
        "tenant_id": "tenant-A",
        "knowledge_id": "kb-9",
        "status": "DRAFT",
        "chunks": [],
    }
    nim.node_import_milvus(state)

    assert len(calls) == 1
    client, collection, tenant, kid, source_doc = calls[0]
    assert client is fake_client
    assert tenant == "tenant-A"
    assert kid == "kb-9"
    assert source_doc == "手册"
