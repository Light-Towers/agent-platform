"""漂移检测 CLI（P0-3）：比对源 schema 与元知识库，输出三类差异。

用法：
    python -m nl2sql_service.scripts.detect_drift \
        --meta-dsn "$META_DB_DSN" --dw-dsn "$DW_DB_DSN" [--schema public] \
        [--dialect postgres|mysql] [--apply-types] [--refresh-stats] [--json]

- 默认**只报警**：新增/删除列只报告，人工决定是否进语义层；
  `--apply-types` 才自动跟类型（P0-3 的唯一自动写）。
- `--refresh-stats` 把行数估值写进 `nl2sql_table_stats`（生成期聚合引导用）。
- `--fail-on-drift` 供 CI 门禁使用：有差异返回 2。
"""

from __future__ import annotations

import argparse
import asyncio
import json


async def main_async(args: argparse.Namespace) -> tuple[int, dict]:
    from nl2sql_service.clients.postgres_client_manager import PostgresClientManager, redact_dsn
    from nl2sql_service.conf.settings import get_settings
    from nl2sql_service.repositories.postgres.dw.dw_repository import DwRepository
    from nl2sql_service.repositories.postgres.meta.meta_repository import MetaRepository
    from nl2sql_service.services.drift_detector import DriftDetector

    settings = get_settings()
    meta_pg = PostgresClientManager(
        args.meta_dsn,
        name="meta-drift",
        statement_timeout_ms=settings.meta_db_statement_timeout_ms,
    )
    # dw 只读探测：information_schema 查询，复用 dw 池的语句超时配额
    dw_pg = PostgresClientManager(
        args.dw_dsn,
        name="dw-drift",
        statement_timeout_ms=settings.dw_db_statement_timeout_ms,
    )
    await meta_pg.connect()
    await dw_pg.connect()
    try:
        detector = DriftDetector(
            dw_repository=DwRepository(pool=dw_pg.pool),
            meta_repository=MetaRepository(pool=meta_pg.pool, table_prefix=settings.table_prefix),
            dialect=args.dialect,
            schema=args.schema,
            datasource_id=args.datasource,
        )
        report = await detector.detect()
        applied = await detector.apply_type_updates(report) if args.apply_types else 0
        stats_written = await detector.refresh_table_stats(report) if args.refresh_stats else 0
        payload = report.to_dict()
        payload["applied_type_updates"] = applied
        payload["table_stats_written"] = stats_written
        payload["meta_dsn"] = redact_dsn(args.meta_dsn)
        payload["dw_dsn"] = redact_dsn(args.dw_dsn)
    finally:
        await dw_pg.close()
        await meta_pg.close()
    return (2 if args.fail_on_drift and report.has_drift else 0), payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="元知识库 schema 漂移检测（默认只报警）")
    parser.add_argument("--meta-dsn", required=True, help="元知识库 DSN")
    parser.add_argument("--dw-dsn", required=True, help="业务数仓 DSN（只读探测）")
    parser.add_argument("--schema", default="public")
    parser.add_argument("--dialect", default="postgres", choices=["postgres", "mysql"])
    parser.add_argument("--datasource", default="", help="datasource_id 作用域（P1-6；缺省空）")
    parser.add_argument("--apply-types", action="store_true", help="自动跟随类型变更（唯一自动写）")
    parser.add_argument("--refresh-stats", action="store_true", help="刷新表行数估值（聚合引导用）")
    parser.add_argument("--json", action="store_true", help="JSON 输出（供 CI/脚本消费）")
    parser.add_argument("--fail-on-drift", action="store_true", help="有差异时返回 2（门禁用）")
    args = parser.parse_args(argv)

    code, payload = asyncio.run(main_async(args))
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(
            f"漂移检测（meta={payload['meta_dsn']} dw={payload['dw_dsn']} dialect={args.dialect}）："
            f"+{len(payload['added'])} 新增 / -{len(payload['deleted'])} 删除 / "
            f"~{len(payload['type_changed'])} 类型变更 / {payload['unchanged']} 未变"
        )
        for item in payload["added"]:
            print(f"  + {item['table_name']}.{item['column_name']} ({item.get('data_type', '')})")
        for item in payload["deleted"]:
            print(f"  - {item['table_name']}.{item['column_name']}")
        for item in payload["type_changed"]:
            print(f"  ~ {item['table_name']}.{item['column_name']}: {item['old_type']} -> {item['new_type']}")
        if payload["applied_type_updates"]:
            print(f"  已自动跟随类型 {payload['applied_type_updates']} 处")
        if payload["table_stats_written"]:
            print(f"  已刷新表统计 {payload['table_stats_written']} 张")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
