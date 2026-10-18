# -*- coding: utf-8 -*-
"""GET /api/pools：连接池可观测快照（配额 / 占用 / 等待 / 错误计数）。

为什么不开在 `/health`：`/health` 走共享 `HealthResponse` 契约，
`tests/test_identity_gate_assembly.py::test_health_route_stays_on_shared_contract`
把 `dependencies == []` 钉死了；往里塞池状态会破坏共享契约形状（该用例禁止
为了本服务需求收窄或改写断言）。池状态单独开只读端点，契约零影响。

判读：`utilization` 持续 > 0.8 且 `requests_waiting` > 0 ⇒ 该扩配额，或该治
慢查询（本服务的已知慢查询候选是缺 ANN 索引导致的顺序扫描，见
docs/plans/plan-nl2sql-meta-lifecycle-2026-10-17.md N4）。`requests_errors`
上升说明已出现取连接超时或 TooManyRequests，用户侧对应一次无解释的失败。
"""

from __future__ import annotations

from agent_runtime.pool_factory import pool_stats
from fastapi import APIRouter, Request

router = APIRouter(prefix="/api", tags=["ops"])


@router.get("/pools")
async def pools(http_request: Request) -> dict:
    registry = getattr(http_request.app.state, "pools", None) or {}
    return {"pools": {name: pool_stats(pool) for name, pool in registry.items()}}
