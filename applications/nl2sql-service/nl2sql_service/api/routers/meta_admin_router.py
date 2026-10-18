"""元知识刷新触发管理端点（H2）。

**H2 缺口**：上游表加列/改类型/删字段，系统不知道也不问——无 cron / CI /
管理端点。数据链路口径（2026-10-17 用户）：数仓最新分区每日同步完成之后取值
字典才变更，故"刷新触发"从"设计定时扫描"降级为"**挂在同步任务下游**"——同步
跑完调一次本端点即可。

**本端点做什么**：跑一遍漂移检测（P0-3，只读比对源 schema vs 元知识库），
返回三类差异 + `rebuild_recommended` 信号。**默认只报警、不自动重建语义**
（P0-3 纪律：加/删列只报告，人工决定是否进语义层；类型除外）。是否真正重建
元知识由调用方（同步任务 / 运维）据 `rebuild_recommended` 决定，再跑构建入口
`python -m nl2sql_service.scripts.build_meta_knowledge`——把"要不要改语义"
这个判断留给人，不让一个 HTTP 调用悄悄改写语义层。

`?refresh_stats=true` 时顺带刷新表行数估值（nl2sql_table_stats，驱动生成期
聚合引导）——这是纯统计、无语义，可自动。

**未接身份门（S-1）下的定位**：只读 + 只报警，最坏后果是多跑一次比对；
重建动作在本端点之外、需显式跑构建 CLI。登记为内部/运维端点，接入身份门后
加 admin 断言。
"""

from __future__ import annotations

from agent_core.logging import get_logger
from fastapi import APIRouter, HTTPException, Request

logger = get_logger(__name__)

router = APIRouter(prefix="/api/meta", tags=["meta-admin"])


@router.post("/refresh")
async def refresh(http_request: Request, refresh_stats: bool = False) -> dict:
    """跑漂移检测，返回差异 + rebuild_recommended（H2 刷新触发器）。

    - meta 库 / dw 库未就绪 ⇒ 503（没有比对基线，跑了也是空）；
    - `refresh_stats=true` 顺带刷新表统计（聚合引导用）。
    """
    ctx = http_request.app.state.context
    settings = http_request.app.state.settings
    meta_repo = getattr(ctx, "meta_repository", None)
    dw_repo = getattr(ctx, "dw_repository", None)
    if meta_repo is None or dw_repo is None:
        raise HTTPException(status_code=503, detail="meta/dw 未就绪，无法跑漂移检测")

    from nl2sql_service.services.datasource import detect_dialect
    from nl2sql_service.services.drift_detector import DriftDetector

    dialect = settings.datasource_dialect or detect_dialect(settings.dw_db_dsn)
    detector = DriftDetector(
        dw_repository=dw_repo,
        meta_repository=meta_repo,
        dialect=dialect,
        schema=settings.dw_schema,
        datasource_id=settings.datasource_id,
    )
    report = await detector.detect()
    stats_written = await detector.refresh_table_stats(report) if refresh_stats else 0
    payload = report.to_dict()
    payload["rebuild_recommended"] = report.has_drift
    payload["datasource_id"] = settings.datasource_id
    payload["dialect"] = dialect
    payload["table_stats_written"] = stats_written
    if report.has_drift:
        logger.info(
            "drift detected: +%d -%d ~%d（rebuild_recommended=true，默认不自动改语义）",
            len(report.added),
            len(report.deleted),
            len(report.type_changed),
        )
    return payload
