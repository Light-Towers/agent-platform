"""元知识构建 CLI（P0-1 实装；此前是构造 service 后只 print 的空壳）。

用法：
    python -m nl2sql_service.scripts.build_meta_knowledge \\
        --dsn "$META_DB_DSN" --config <MetricConfig YAML> [--prune]

- `--config` 只接受 `config/metric_config_schema.py` 的 **MetricConfig**：
  运行契约单源，不再吃任意 dict（schema 漂移在加载期就炸，不在写入期）。
- `--prune`：删除源里已不存在的行（差异重建的另一半，方案 H3/P0-2）。
- 输出构建报告：每类 inserted/updated（+ prune 时的 deleted）计数。

embedding 走 Settings 的 backend/model（与在线路径同一工厂）；维度必须等于
`Settings.vector_dim`，不等直接抛错（不静默写坏数据）。
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from typing import Any


def load_metric_config(config_path: str) -> Any:
    """读 YAML 并校验为 MetricConfig；不接受任意 dict。"""
    import yaml

    from nl2sql_service.config.metric_config_schema import MetricConfig

    path = Path(config_path)
    if not path.is_file():
        raise FileNotFoundError(f"配置文件不存在: {config_path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"配置文件顶层必须是 mapping（表/列/指标/值四段）: {config_path}")
    return MetricConfig(**data)


def tables_from_config(config: Any) -> list[dict[str, Any]]:
    """MetricConfig 的扁平 columns 组装成 build_from_tables 的嵌套结构。

    表注释只存在于 `tables` 段；columns 段出现 tables 段未声明的表名时补
    空注释条目——不静默丢列（丢列 = 该列向量召回路少一条，无任何报错）。
    """
    grouped: dict[str, dict[str, Any]] = {}
    for t in config.tables:
        grouped[t.table_name] = {
            "table_name": t.table_name,
            "table_comment": t.table_comment,
            "columns": [],
        }
    for c in config.columns:
        entry = grouped.setdefault(
            c.table_name, {"table_name": c.table_name, "table_comment": "", "columns": []}
        )
        entry["columns"].append(c.model_dump())
    return list(grouped.values())


async def main_async(
    dsn: str,
    config_path: str,
    prune: bool = False,
    datasource_id: str = "",
    tenant_id: str = "",
    workspace_id: str = "",
) -> dict[str, Any]:
    from nl2sql_service.clients.embedding_client_manager import build_embedder
    from nl2sql_service.clients.postgres_client_manager import PostgresClientManager, redact_dsn
    from nl2sql_service.conf.settings import get_settings
    from nl2sql_service.repositories.postgres.meta.meta_repository import MetaRepository
    from nl2sql_service.services.meta_knowledge_service import MetaKnowledgeService

    settings = get_settings()
    # P1-6：元知识按源分片。--datasource 缺省取 settings.datasource_id——与在线
    # 召回的 datasource 过滤同源，否则"建了一套、召回按另一个源过滤"恒空。
    ds_id = datasource_id or settings.datasource_id
    # P1-1 隔离：tenant/workspace 作用域（A 方案前置）。缺省取 settings.default_*
    # （单租户 dev = ''，与 DDL scope 默认一致）；多租户构建显式传，召回侧才隔离。
    t_id = tenant_id or settings.default_tenant
    w_id = workspace_id or settings.default_workspace
    config = load_metric_config(config_path)
    tables = tables_from_config(config)
    metrics = [m.model_dump() for m in config.metrics]
    values = [v.model_dump() for v in config.values]
    relations = [r.model_dump() for r in config.relations]
    aliases = [a.model_dump() for a in config.aliases]

    pg = PostgresClientManager(
        dsn,
        name="meta-build",
        min_size=settings.meta_db_pool_min_size,
        max_size=settings.meta_db_pool_max_size,
        timeout=settings.meta_db_pool_timeout,
        statement_timeout_ms=settings.meta_db_statement_timeout_ms,
    )
    await pg.connect()
    try:
        embedder = build_embedder(
            settings.embedding_backend,
            api_key=settings.embedding_api_key,
            model=settings.embedding_model,
            base_url=settings.embedding_base_url,
        )
        service = MetaKnowledgeService(
            meta_repo=MetaRepository(pool=pg.pool, table_prefix=settings.table_prefix),
            embedder=embedder,
            tokenizer=settings.tokenizer,
            vector_dim=settings.vector_dim,
            datasource_id=ds_id,
            tenant_id=t_id,
            workspace_id=w_id,
        )
        report: dict[str, Any] = {
            "columns": await service.build_from_tables(tables),
            "metrics": await service.build_from_metrics(metrics),
            "values": await service.build_from_values(values),
            "relations": await service.build_from_relations(relations),
            "aliases": await service.build_from_aliases(aliases),
        }
        if prune:
            report["pruned"] = await service.prune(tables, metrics, values, relations, aliases)
    finally:
        await pg.close()
    report["dsn"] = redact_dsn(dsn)
    return report


def _print_report(report: dict[str, Any]) -> None:
    print(f"元知识构建报告（{report.get('dsn', '')}）：")
    for name in ("columns", "metrics", "values", "relations", "aliases"):
        stats = report.get(name) or {}
        print(f"  {name}: inserted={stats.get('inserted', 0)} updated={stats.get('updated', 0)}")
    if "pruned" in report:
        p = report["pruned"]
        print(
            f"  pruned: columns={p['columns_deleted']} metrics={p['metrics_deleted']} "
            f"values={p['values_deleted']} relations={p['relations_deleted']} "
            f"aliases={p['aliases_deleted']}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="构建元知识库（幂等 upsert；--prune 删源中已不存在的行）"
    )
    parser.add_argument("--dsn", required=True, help="元知识库 Postgres DSN")
    parser.add_argument(
        "--config",
        required=True,
        help="MetricConfig YAML 路径（结构见 nl2sql_service/config/metric_config.example.yaml）",
    )
    parser.add_argument(
        "--prune",
        action="store_true",
        help="删除源里已不存在的行（差异重建；不带则只 upsert）",
    )
    parser.add_argument(
        "--datasource",
        default="",
        help="datasource_id 作用域（P1-6；缺省取 Settings.datasource_id，与在线召回过滤同源）",
    )
    parser.add_argument("--tenant", default="", help="tenant_id 作用域（P1-1 隔离；缺省取 Settings.default_tenant）")
    parser.add_argument(
        "--workspace", default="", help="workspace_id 作用域（P1-1；缺省取 Settings.default_workspace）"
    )
    args = parser.parse_args(argv)
    report = asyncio.run(
        main_async(args.dsn, args.config, args.prune, args.datasource, args.tenant, args.workspace)
    )
    _print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
