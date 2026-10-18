"""H2 刷新触发管理端点：POST /api/meta/refresh。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from nl2sql_service.services.drift_detector import DriftReport


def _make_app(detector_report: DriftReport, with_meta=True, with_dw=True):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from nl2sql_service.api.routers.meta_admin_router import router

    ctx = MagicMock()
    ctx.meta_repository = MagicMock() if with_meta else None
    ctx.dw_repository = MagicMock() if with_dw else None
    settings = MagicMock()
    settings.datasource_dialect = "postgres"
    settings.dw_db_dsn = "postgres://x"
    settings.dw_schema = "public"
    settings.datasource_id = "dw"
    app = FastAPI()
    app.state.context = ctx
    app.state.settings = settings
    app.include_router(router)
    return TestClient(app), settings


def _patch_detector(monkeypatch, report, stats_written=0):
    det = MagicMock()
    det.detect = AsyncMock(return_value=report)
    det.refresh_table_stats = AsyncMock(return_value=stats_written)

    def _factory(**kwargs):
        return det

    monkeypatch.setattr("nl2sql_service.services.drift_detector.DriftDetector", _factory)
    return det


def test_refresh_no_drift(monkeypatch):
    report = DriftReport(unchanged=5)
    _patch_detector(monkeypatch, report)
    client, _ = _make_app(report)
    resp = client.post("/api/meta/refresh")
    assert resp.status_code == 200
    body = resp.json()
    assert body["rebuild_recommended"] is False
    assert body["unchanged"] == 5
    assert body["table_stats_written"] == 0


def test_refresh_with_drift_signals_rebuild(monkeypatch):
    report = DriftReport(added=[{"table_name": "orders", "column_name": "new_col"}], unchanged=3)
    _patch_detector(monkeypatch, report)
    client, _ = _make_app(report)
    body = client.post("/api/meta/refresh").json()
    assert body["rebuild_recommended"] is True
    assert body["added"][0]["column_name"] == "new_col"


def test_refresh_stats_flag(monkeypatch):
    report = DriftReport(unchanged=5)
    _patch_detector(monkeypatch, report, stats_written=4)
    client, _ = _make_app(report)
    body = client.post("/api/meta/refresh?refresh_stats=true").json()
    assert body["table_stats_written"] == 4


def test_refresh_503_when_pools_missing():
    report = DriftReport()
    client, _ = _make_app(report, with_meta=False)
    assert client.post("/api/meta/refresh").status_code == 503
