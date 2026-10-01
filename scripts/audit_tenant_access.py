#!/usr/bin/env python3
"""租户访问追溯审计（plan-tenant-identity A1，分支 A 事故响应）。

**只读**：全程 SELECT + `SET TRANSACTION READ ONLY`，绝不写库。产出 JSON（stdout）+
Markdown 报告（--out），供持目标库访问权者在生产/预发执行；编码 agent 不连生产库。

⚠️ 执行时机：必须**先于 A3 令牌体系上线**。A3/A4 改变 tenant 来源与分布基线后，
"是否已发生跨租户越权"的取证基线被破坏，无法回溯。

检查项（逐项 try/except，互不中断）：
1. 各业务表 tenant 分布：memories / chunks / sql_ddl / sql_docs / sql_examples /
   episodic_memories / procedural_memories 逐表 GROUP BY tenant_id；标记 default 外
   的孤立小租户、疑似测试/占位租户名。
2. semantic_cache 跨租户污染：按 tenant 统计条目数与命中计数，抽样 query 供人工判定。
3. 访问日志关联（自动探测 request_logs 类表，无则跳过并注明）：同一来源 key 自报多
   个 tenant → 标红（单 key 多租户 = 越权信号）。
4. knowledge-service default 归属审计（应用日志非 DB 表，探测审计表否则跳过并注明）。
5. trajectory/episodic 按 tenant 分布（自动探测轨迹表）。

依赖：`psycopg[binary]`（v3）。用法：
    python scripts/audit_tenant_access.py --dsn "$DATABASE_URL" \
        [--default-tenant default] [--orphan-max 5] --out output/tenant_audit.md
不提交任何真实数据：本脚本仅在运行时连库，仓库内不含任何查询结果。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from typing import Any

# 已知业务表（列 tenant_id 由 ADR-0006 隔离加固 T9/T13/T1 落地）。
BUSINESS_TABLES = [
    "memories",
    "chunks",
    "sql_ddl",
    "sql_docs",
    "sql_examples",
    "episodic_memories",
    "procedural_memories",
]

# 疑似测试/占位租户名（命中仅作提示，需人工判定，不作硬结论）。
_PLACEHOLDER_RE = re.compile(r"^(test|sample|demo|foo|bar|example|dummy|tmp)[_-]?[0-9a-z]*$", re.I)


def _tag_tenant(tenant: str, count: int, default_tenant: str, orphan_max: int) -> list[str]:
    """纯函数：给单个 tenant 分布点打可疑标记（供人工排查，不自动定性越权）。"""
    tags: list[str] = []
    if _PLACEHOLDER_RE.match(tenant or ""):
        tags.append("疑似测试/占位租户名")
    if tenant != default_tenant and count <= orphan_max:
        tags.append(f"孤立小租户(<= {orphan_max} 行)，可能误归属/残留")
    return tags


def _resolve_table(conn, candidates: list[str]) -> str | None:
    """自动探测存在的表名（按 schema 'public'），返回首个命中，否则 None。"""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = ANY(%s)",
            (candidates,),
        )
        found = {r[0] for r in cur.fetchall()}
    for name in candidates:
        if name in found:
            return name
    return None


def _table_has_tenant(conn, table: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name=%s AND column_name='tenant_id' LIMIT 1",
            (table,),
        )
        return cur.fetchone() is not None


def _group_by_tenant(conn, table: str) -> list[tuple[str, int]]:
    with conn.cursor() as cur:
        cur.execute(f'SELECT COALESCE(tenant_id,\'<NULL>\'), count(*) FROM "{table}" GROUP BY 1 ORDER BY 2 DESC')
        return [(str(t), int(c)) for t, c in cur.fetchall()]


def check_tenant_distribution(conn, args) -> dict[str, Any]:
    out: dict[str, Any] = {"check": "1_business_tenant_distribution", "tables": []}
    for table in BUSINESS_TABLES:
        entry: dict[str, Any] = {"table": table}
        try:
            if not _table_has_tenant(conn, table):
                entry["status"] = "skip"
                entry["note"] = "表不存在或无 tenant_id 列（迁移未应用？）"
                out["tables"].append(entry)
                continue
            dist = _group_by_tenant(conn, table)
            flags: list[str] = []
            for tenant, count in dist:
                t = _tag_tenant(tenant, count, args.default_tenant, args.orphan_max)
                if t:
                    flags.append(f"{tenant}({count} 行): " + "; ".join(t))
            entry.update({"status": "ok", "distribution": dist, "flags": flags})
        except Exception as e:  # noqa: BLE001 - 逐项不中断
            entry.update({"status": "error", "error": str(e)})
        out["tables"].append(entry)
    return out


def check_semantic_cache(conn, args) -> dict[str, Any]:
    entry: dict[str, Any] = {"check": "2_semantic_cache_cross_tenant"}
    try:
        table = _resolve_table(conn, ["semantic_cache", "semantic_cache_entries"])
        if not table:
            entry.update({"status": "skip", "note": "semantic_cache 表不存在"})
            return entry
        with conn.cursor() as cur:
            cur.execute(
                f'SELECT COALESCE(tenant_id,\'<NULL>\'), count(*), COALESCE(SUM(hit_count),0) '
                f'FROM "{table}" GROUP BY 1 ORDER BY 2 DESC'
            )
            agg = [(str(t), int(n), int(h)) for t, n, h in cur.fetchall()]
            cur.execute(
                f'SELECT COALESCE(tenant_id,\'<NULL>\'), left(query::text, 80), COALESCE(hit_count,0) '
                f'FROM "{table}" ORDER BY COALESCE(hit_count,0) DESC LIMIT 20'
            )
            samples = [(str(t), q, int(h)) for t, q, h in cur.fetchall()]
        entry.update({
            "status": "ok",
            "per_tenant": agg,
            "top_hit_samples": samples,
            "note": "人工判定：query 内容与其归属租户业务是否相符；命中数跨租户偏高提示缓存串味",
        })
    except Exception as e:  # noqa: BLE001
        entry.update({"status": "error", "error": str(e)})
    return entry


def check_access_log(conn, args) -> dict[str, Any]:
    entry: dict[str, Any] = {"check": "3_access_log_single_key_multi_tenant"}
    try:
        table = _resolve_table(conn, ["request_logs", "access_logs", "api_access_log", "access_log"])
        if not table:
            entry.update({"status": "skip", "note": "未探测到访问日志表（不同部署表名不一），跳过"})
            return entry
        # 找来源列（api_key/source/client_id）+ tenant_id
        with conn.cursor() as cur:
            cur.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name=%s",
                (table,),
            )
            cols = {r[0] for r in cur.fetchall()}
        source_col = next((c for c in ("api_key", "api_key_hash", "source", "client_id", "key") if c in cols), None)
        if not source_col or "tenant_id" not in cols:
            entry.update({"status": "skip", "note": f"表 {table} 缺来源列或 tenant_id，跳过"})
            return entry
        with conn.cursor() as cur:
            cur.execute(
                f'SELECT "{source_col}", count(DISTINCT tenant_id) AS tenants, '
                f'array_agg(DISTINCT tenant_id) FROM "{table}" '
                f'GROUP BY 1 HAVING count(DISTINCT tenant_id) > 1 ORDER BY 2 DESC'
            )
            rows = [(str(s), int(n), [str(t) for t in (ts or [])]) for s, n, ts in cur.fetchall()]
        entry.update({
            "status": "ok",
            "single_key_multi_tenant": rows,
            "note": "同一来源自报多个 tenant = 越权信号（ADR-0007 触发点）；需结合时间窗判定",
        })
    except Exception as e:  # noqa: BLE001
        entry.update({"status": "error", "error": str(e)})
    return entry


def check_ks_default_audit(conn, args) -> dict[str, Any]:
    entry: dict[str, Any] = {"check": "4_knowledge_service_default_injection_audit"}
    try:
        table = _resolve_table(conn, ["ks_default_tenant_audit", "tenant_injection_audit", "audit_log"])
        if not table:
            entry.update({
                "status": "skip",
                "note": "T11 default 注入审计落应用日志（logger.warning），非 DB 表；"
                       "需从日志系统汇总 'tenant_id 缺失，按部署默认注入' 计数，本脚本无法直连",
            })
            return entry
        entry.update({"status": "ok", "table": table, "note": "探测到审计表，人工按 tenant/时间窗聚合"})
    except Exception as e:  # noqa: BLE001
        entry.update({"status": "error", "error": str(e)})
    return entry


def check_trajectory_tenant(conn, args) -> dict[str, Any]:
    entry: dict[str, Any] = {"check": "5_trajectory_tenant_distribution"}
    try:
        table = _resolve_table(conn, ["trajectories", "agent_trajectories", "trajectory_records", "executions"])
        if not table or not _table_has_tenant(conn, table or ""):
            entry.update({"status": "skip", "note": "未探测到含 tenant_id 的轨迹表（episodic 已并入检查 1）"})
            return entry
        entry.update({"status": "ok", "table": table, "distribution": _group_by_tenant(conn, table)})
    except Exception as e:  # noqa: BLE001
        entry.update({"status": "error", "error": str(e)})
    return entry


def _render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# 租户访问追溯审计报告",
        f"- 执行时间窗（UTC）：{report['started_at']} → {report['finished_at']}",
        f"- DSN 主机：{report['dsn_host']}（凭证不落报告）",
        f"- 默认租户：`{report['default_tenant']}` · 孤立阈值：{report['orphan_max']} 行",
        "",
        "> **取证基线声明**：本快照须在 A3 令牌体系上线前采集；上线后 tenant 来源与分布改变，"
        "不可据此回溯越权是否已发生。",
        "",
    ]
    for sec in report["checks"]:
        lines.append(f"## {sec['check']}  —  status: **{sec['status']}**")
        if sec.get("note"):
            lines.append(f"- note: {sec['note']}")
        if sec["check"].startswith("1_"):
            for t in sec.get("tables", []):
                lines.append(f"- `{t['table']}`: {t['status']}")
                for fl in t.get("flags", []):
                    lines.append(f"    - ⚠️ {fl}")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="只读租户访问追溯审计（A1）")
    ap.add_argument("--dsn", required=True, help="目标库只读连接串（DATABASE_URL）")
    ap.add_argument("--default-tenant", default="default", help="部署默认租户（孤立判定基准）")
    ap.add_argument("--orphan-max", type=int, default=5, help="非默认租户行数 <= 此值标为孤立小租户")
    ap.add_argument("--out", default="", help="Markdown 报告输出路径（留空仅打印 JSON）")
    args = ap.parse_args(argv)

    try:
        import psycopg  # v3；operator 环境需 pip install "psycopg[binary]"
    except ImportError:
        print("需要 psycopg[binary]：pip install 'psycopg[binary]'", file=sys.stderr)
        return 2

    started = datetime.now(timezone.utc).isoformat()
    try:
        conn = psycopg.connect(args.dsn)
    except Exception as e:  # noqa: BLE001
        print(f"连接失败：{e}", file=sys.stderr)
        return 1
    conn.read_only = True

    checks = [fn(conn, args) for fn in (
        check_tenant_distribution,
        check_semantic_cache,
        check_access_log,
        check_ks_default_audit,
        check_trajectory_tenant,
    )]
    finished = datetime.now(timezone.utc).isoformat()
    conn.close()

    report = {
        "started_at": started,
        "finished_at": finished,
        "dsn_host": _host_of(args.dsn),
        "default_tenant": args.default_tenant,
        "orphan_max": args.orphan_max,
        "checks": checks,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    if args.out:
        md = _render_markdown(report)
        from pathlib import Path
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(md, encoding="utf-8", newline="\n")
    return 0


def _host_of(dsn: str) -> str:
    m = re.search(r"@([^/?]+)", dsn or "")
    return m.group(1) if m else "<unknown>"


if __name__ == "__main__":
    raise SystemExit(main())
