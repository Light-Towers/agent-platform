"""数据源注册表 + 方言探测 + 请求契约（P1-3/P1-4/P1-6）。"""

from __future__ import annotations

import pytest
from nl2sql_service.services.datasource import (
    DataSource,
    DataSourceRegistry,
    build_default_registry,
    detect_dialect,
)


class TestDetectDialect:
    def test_mysql_and_mariadb_scheme(self):
        assert detect_dialect("mysql://u:p@h/db") == "mysql"
        assert detect_dialect("mariadb://u:p@h/db") == "mysql"

    def test_postgres_family_and_default(self):
        assert detect_dialect("postgres://u:p@h/db") == "postgres"
        assert detect_dialect("postgresql://u:p@h/db") == "postgres"
        assert detect_dialect("") == "postgres"
        assert detect_dialect("no-scheme") == "postgres"
        assert detect_dialect("redis://x") == "postgres"  # 未知 scheme 回落默认


class TestRegistry:
    def test_resolve_default_when_empty(self):
        reg = build_default_registry(datasource_id="dw", dialect="postgres", label="数仓 T+1")
        src = reg.resolve(None)
        assert src.id == "dw" and src.dialect == "postgres"
        assert reg.resolve("") == src

    def test_resolve_unknown_fail_fast(self):
        reg = build_default_registry(datasource_id="dw", dialect="postgres")
        with pytest.raises(KeyError):
            reg.resolve("mysql-ghost")

    def test_default_id_must_exist(self):
        with pytest.raises(ValueError):
            DataSourceRegistry({}, default_id="missing")

    def test_multi_source(self):
        reg = DataSourceRegistry(
            {
                "dw": DataSource(id="dw", dialect="postgres", label="数仓 T+1"),
                "biz": DataSource(id="biz", dialect="mysql", label="业务库、实时未清洗"),
            },
            default_id="dw",
        )
        assert reg.resolve("biz").dialect == "mysql"
        assert reg.resolve("biz").label == "业务库、实时未清洗"
        assert reg.ids() == ["biz", "dw"]


def test_request_schema_accepts_datasource_id():
    from nl2sql_service.api.schemas.query_schema import SqlQueryRequest

    req = SqlQueryRequest(query="查订单", datasource_id="biz")
    assert req.datasource_id == "biz"
    # 不传 = None（服务端回落默认源）
    assert SqlQueryRequest(query="x").datasource_id is None


def test_response_schema_has_datasource_label():
    from nl2sql_service.api.schemas.query_schema import SqlQueryResponse

    resp = SqlQueryResponse(answer="共 10 单", datasource_label="数仓 T+1、已清洗")
    assert resp.datasource_label == "数仓 T+1、已清洗"
    assert SqlQueryResponse(answer="x").datasource_label is None
