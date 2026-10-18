# -*- coding: utf-8 -*-
"""POST /api/meta/ingest 用例（A 方案 Stage ③，替代 agent_server /sql/train）。

钉七件事：
1. DDL/文档/范例三路摄入，写入 core 与迁移 CLI 同一份（ingest_service.write_scope）；
2. 全空请求 400；meta 未就绪 503（不静默）；
3. 坏 DDL / 未命中文档 / 空 question 全部进响应记账（喂坏了看得见）；
4. 作用域：tenant 服务端断言 > 请求体 > default（resolve_scope 同 /api/query）；
5. 响应带回实际落点 scope（摄入方 vs 召回方作用域不一致 = 恒不可见，必须可见）；
6. 单串 ddl/docs 归一为列表（对齐 SqlTrainRequest 的两种形状）；
7. 端点已挂载（create_app 含 /api/meta/ingest 路由）。
"""

from __future__ import annotations

import hashlib
import os
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from nl2sql_service.api.routers.ingest_router import ingest
from nl2sql_service.api.schemas.ingest_schema import IngestExample, IngestRequest

_DDL = "CREATE TABLE orders (id BIGINT, amount NUMERIC(10,2)); COMMENT ON TABLE orders IS '订单主表';"
_DDL_BAD = "CREATE TABEL broken ("


class _FakeMetaRepo:
    """记录 save_column/save_example 调用（首次插入，后续更新）。"""

    def __init__(self) -> None:
        self.columns: list[dict[str, Any]] = []
        self.examples: list[dict[str, Any]] = []
        self._seen_columns: set[tuple] = set()
        self._seen_examples: set[tuple] = set()

    async def save_column(self, data: dict[str, Any]) -> bool:
        key = (data.get("table_name"), data.get("column_name"))
        inserted = key not in self._seen_columns
        self._seen_columns.add(key)
        self.columns.append(data)
        return inserted

    async def save_example(self, data: dict[str, Any]) -> bool:
        inserted = data.get("question") not in self._seen_examples
        self._seen_examples.add(data.get("question"))
        self.examples.append(data)
        return inserted


class _FakeApp:
    def __init__(self, meta_repo: Any) -> None:
        self.state = SimpleNamespace(context=SimpleNamespace(meta_repository=meta_repo))


class _FakeHttpRequest:
    def __init__(self, app: Any) -> None:
        self.app = app


def _det_embedder(dim: int = 1024):
    def _vec(text: str) -> list[float]:
        out: list[float] = []
        for i in range(32):
            out.extend(b / 255.0 for b in hashlib.sha256(f"{text}#{i}".encode()).digest())
        return out

    class _Embedder:
        async def embed_texts(self, texts: list[str]) -> list[list[float]]:
            return [_vec(t) for t in texts]

        async def embed_query(self, text: str) -> list[float]:
            return _vec(text)

    return _Embedder()


@pytest.fixture
def patched_embedder(monkeypatch):
    import nl2sql_service.clients.embedding_client_manager as ecm

    monkeypatch.setattr(ecm, "build_embedder", lambda *a, **k: _det_embedder())
    return ecm


# ---------------------------------------------------------------------------
# ① 三路摄入 + 写入形状
# ---------------------------------------------------------------------------
async def test_ingest_ddl_docs_examples(patched_embedder):
    repo = _FakeMetaRepo()
    report = await ingest(
        IngestRequest(
            ddl=_DDL,
            docs="orders 的状态机说明",
            examples=[IngestExample(question="上个月销售额", sql="SELECT SUM(amount) FROM orders")],
            tenant_id="t-1",
            workspace_id="w-1",
        ),
        _FakeHttpRequest(_FakeApp(repo)),
    )
    assert report.columns == {"inserted": 2, "updated": 0}
    assert report.examples == {"inserted": 1, "updated": 0}
    assert (report.tenant_id, report.workspace_id) == ("t-1", "w-1"), "响应必须带回实际落点 scope"
    assert report.datasource_id, "datasource 落点必须可见（摄入方 vs 召回方不一致=恒不可见）"

    col = repo.columns[0]
    assert col["table_name"] == "orders" and col["column_name"] == "id"
    assert col["tenant_id"] == "t-1" and col["workspace_id"] == "w-1"
    assert "订单主表" in col["table_comment"] and "状态机说明" in col["table_comment"]
    assert col["embedding"] and len(col["embedding"]) == 1024
    ex = repo.examples[0]
    assert ex["question"] == "上个月销售额" and ex["source"] == "human"
    assert ex["embedding"] and len(ex["embedding"]) == 1024


async def test_ingest_examples_only(patched_embedder):
    repo = _FakeMetaRepo()
    report = await ingest(
        IngestRequest(examples=[IngestExample(question="q1", sql="SELECT 1")]),
        _FakeHttpRequest(_FakeApp(repo)),
    )
    assert report.examples == {"inserted": 1, "updated": 0}
    assert report.columns == {"inserted": 0, "updated": 0}


# ---------------------------------------------------------------------------
# ② 校验：全空 400 / meta 未就绪 503
# ---------------------------------------------------------------------------
async def test_ingest_empty_request_400(patched_embedder):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await ingest(IngestRequest(), _FakeHttpRequest(_FakeApp(_FakeMetaRepo())))
    assert exc_info.value.status_code == 400


async def test_ingest_without_meta_503(patched_embedder):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await ingest(
            IngestRequest(ddl=_DDL),
            _FakeHttpRequest(_FakeApp(None)),  # context.meta_repository = None
        )
    assert exc_info.value.status_code == 503


# ---------------------------------------------------------------------------
# ③ 记账：坏 DDL / 未命中文档 / 空 question
# ---------------------------------------------------------------------------
async def test_ingest_records_bad_inputs(patched_embedder):
    repo = _FakeMetaRepo()
    report = await ingest(
        IngestRequest(ddl=[_DDL, _DDL_BAD], docs="不提表名的运维手册", examples=[IngestExample(question="  ", sql="SELECT 1")]),
        _FakeHttpRequest(_FakeApp(repo)),
    )
    assert report.skipped_ddl and "unparsed statement" in report.skipped_ddl[0]
    assert report.unmapped_docs and "运维手册" in report.unmapped_docs[0]
    assert report.skipped_examples and "empty question" in report.skipped_examples[0]
    assert report.examples == {"inserted": 0, "updated": 0}, "空 question 不得落库"


# ---------------------------------------------------------------------------
# ④ 单串归一（对齐 SqlTrainRequest 两种形状）
# ---------------------------------------------------------------------------
async def test_ingest_accepts_string_or_list(patched_embedder):
    repo_str = _FakeMetaRepo()
    await ingest(IngestRequest(ddl=_DDL), _FakeHttpRequest(_FakeApp(repo_str)))
    repo_list = _FakeMetaRepo()
    await ingest(IngestRequest(ddl=[_DDL]), _FakeHttpRequest(_FakeApp(repo_list)))
    assert len(repo_str.columns) == len(repo_list.columns) == 2, "单串与单元素列表必须等价"


# ---------------------------------------------------------------------------
# ⑥ 幂等：同内容两次摄入 = 第二次全 updated
# ---------------------------------------------------------------------------
async def test_ingest_is_idempotent(patched_embedder):
    repo = _FakeMetaRepo()
    req = IngestRequest(ddl=_DDL, examples=[IngestExample(question="q", sql="SELECT 1")])
    first = await ingest(req, _FakeHttpRequest(_FakeApp(repo)))
    second = await ingest(req, _FakeHttpRequest(_FakeApp(repo)))
    assert first.columns == {"inserted": 2, "updated": 0}
    assert second.columns == {"inserted": 0, "updated": 2}, "重跑必须 upsert 不翻倍"
    assert second.examples == {"inserted": 0, "updated": 1}


# ---------------------------------------------------------------------------
# ⑦ 挂载：路由在 create_app 里
# ---------------------------------------------------------------------------
def test_ingest_route_mounted():
    from nl2sql_service.api.server import create_app

    app = create_app()
    # app.routes 在本版本 FastAPI 下含 _IncludedRouter 包装对象（无 .path）——
    # 挂载断言走 openapi paths（唯一可靠的"端点真在服务里"判据）
    paths = set(app.openapi()["paths"])
    assert "/api/meta/ingest" in paths, "ingest 端点必须挂载（/sql/train 的替代）"


# ---------------------------------------------------------------------------
# 附：真库用例（skipif）——TestClient 全链路（需要 embedder；余额耗尽时用
# 确定性假向量，机械性验证）
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not os.environ.get("META_DB_DSN"), reason="需真实 meta 库；手动设 META_DB_DSN 跑 -k real_pg")
async def test_ingest_endpoint_on_real_pg(patched_embedder):
    """真库判据：假 repo 证不了 upsert 落库，必须真 PG。

    手动步骤：
        python -m nl2sql_service.scripts.init_meta_schema --dsn "$META_DB_DSN"
        META_DB_DSN="..." uv run pytest applications/nl2sql-service/tests \\
            ::test_ingest_endpoint.py -k real_pg -q -s
    """

    from nl2sql_service.api.server import create_app

    settings_dsn = os.environ["META_DB_DSN"]
    app = create_app()
    with TestClient(app) as client:
        resp = client.post(
            "/api/meta/ingest",
            json={
                "ddl": "CREATE TABLE ingest_probe (id BIGINT, note TEXT);",
                "examples": [{"question": "ingest 探针问题", "sql": "SELECT 1"}],
                "tenant_id": "probe",
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["columns"]["inserted"] + body["columns"]["updated"] == 2
        assert body["examples"]["inserted"] + body["examples"]["updated"] == 1
        assert body["tenant_id"] == "probe"

        # 清理：删掉探针行（tenant_id='probe' 是专用作用域，不碰别的数据）
        from nl2sql_service.clients.postgres_client_manager import PostgresClientManager

        pg = PostgresClientManager(settings_dsn, name="ingest-probe-clean", statement_timeout_ms=10_000)
        await pg.connect()
        try:
            async with pg.pool.connection() as conn:
                await conn.execute("DELETE FROM nl2sql_column_info WHERE tenant_id = 'probe'")
                await conn.execute("DELETE FROM nl2sql_example_info WHERE tenant_id = 'probe'")
        finally:
            await pg.close()
    print("real-pg ingest 验证通过")
