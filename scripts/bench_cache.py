#!/usr/bin/env python3
"""语义缓存容量基准（ADR-0013 C Stage 3）：4 租户 / 10 万条 / 512 维 / 200 QPS。

前置：一个**专用** Valkey（带 Search 模块，推荐 ``valkey/valkey-bundle:9.1.2``），
``maxmemory`` 至少 1GB 且基准期间不淘汰。不要对共享实例跑：脚本会写入 10 万条
并创建独立索引（scope 自带时间戳），默认结束后只清理自己命名空间内的 key。

示例：
    VALKEY_URL=redis://127.0.0.1:6379/0 uv run python scripts/bench_cache.py
    uv run python scripts/bench_cache.py --entries 10000 --duration 5   # 冒烟

预算（超出即 exit 1）：
    p95 ≤ 10ms、p99 ≤ 25ms、错误率 < 0.1%、10 万条内存增量 ≤ 512MB、写丢弃 = 0、
    写跳过（无租户/PII 门禁）= 0。写侧两项取自 seed 阶段的计数增量——读侧后端从不写入，
    拿它的 `dropped_writes` 判定恒为 0（假绿）。

计时前置（不满足则中止，不算预算红）：
    索引后台回填必须就绪（`FT.INFO` 的 `state=ready` 且 `hash_indexing_failures=0`）。
    回填中或 OOM 暂停时命中率会假低，读起来像容量不足，实际是没等够。
    向量由 `_seed_int`（sha256 派生）决定，跨进程、跨重跑可复现；原先用 `hash()`，
    CPython 按进程随机化 ⇒ 同一份脚本两次跑出的不是同一批向量。
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import sys
import time
from typing import Any

from agent_runtime.cache.config import CacheConfig
from agent_runtime.cache.valkey_backend import ValkeySemanticCache

_BUDGET_P95_MS = 10.0
_BUDGET_P99_MS = 25.0
_BUDGET_ERROR_RATE = 0.001
_BUDGET_MEMORY_BYTES = 512 * 1024 * 1024
_MIN_HIT_RATE = 0.95


class _FixedEmbedder:
    """基准只用显式向量；保留 embedder 只为让适配器解析出模型/维度。"""

    def __init__(self, dim: int) -> None:
        self.dim = dim


def _vector(seed: int, dim: int, noise: float = 0.0) -> list[float]:
    """确定性伪随机单位向量（不缓存 10 万条向量，按需重算控制脚本内存）。"""
    if noise:
        values = [
            math.sin(seed * 0.0001 + (d + 1) * 0.37) + noise * math.sin(seed * 0.0002 + (d + 1) * 1.13)
            for d in range(dim)
        ]
    else:
        values = [math.sin(seed * 0.0001 + (d + 1) * 0.37) for d in range(dim)]
    norm = math.sqrt(sum(v * v for v in values)) or 1.0
    return [v / norm for v in values]


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    pos = (len(ordered) - 1) * p
    low, high = math.floor(pos), math.ceil(pos)
    if low == high:
        return ordered[int(pos)]
    return ordered[low] * (high - pos) + ordered[high] * (pos - low)


def _seed_int(tenant: str, index: int) -> int:
    """跨进程稳定的向量种子。

    原先用 `hash((tenant, index))`：CPython 对 str 的哈希按进程随机化（PYTHONHASHSEED），
    seed 与 measure 只在同一次运行里自洽。基准的数字要能被人重跑核对（Stage 3/4 是
    放行判据的来源），所以这里改成 sha256 派生——同输入永远同向量。
    """
    return int(hashlib.sha256(f"{tenant}\x00{index}".encode()).hexdigest()[:8], 16)


def _backfill_verdict(info: Any) -> tuple[bool, str]:
    """判"索引后台回填是否已完成 + 是否有条目没能进索引"。

    字段名取自 valkey-search `docs/commands/ft.info.md`：`state` ∈
    `ready` / `backfill_in_progress` / `backfill_paused_by_oom`，`hash_indexing_failures`
    是入索失败计数（非零 ⇒ 一部分行根本不可检索，命中率会假低、容量结论会假像）。
    valkey-py 把 FT.INFO 解析成扁平 dict（`commands.py::_parse_info`）；形状不认识就判
    "未就绪"——宁可超时中止，也不要拿一个还在回填/有失败条目的索引去量命中率。
    """
    if not isinstance(info, dict):
        return False, f"info 形状不认识（type={type(info).__name__}）"
    state = str(info.get("state", "")).lower()
    try:
        failures = int(info.get("hash_indexing_failures", 0))
    except (TypeError, ValueError):
        failures = -1
    note = f"state={state or '未知'} hash_indexing_failures={failures}"
    if state != "ready":
        return False, note
    if failures != 0:
        return False, f"{note}（有条目未进索引，命中率不可信）"
    return True, note


async def _wait_backfill(cache: ValkeySemanticCache, timeout_s: float) -> str:
    """轮询 FT.INFO 直到回填完成；超时即中止基准（SystemExit ⇒ rc=1）。

    这里不放"降级继续"的口子：一个还在回填或 OOM 暂停的索引会让命中率掉到 0.9 以下，
    读起来像"缓存容量不够"，实际是"没等够"——Stage 3/4 是放行判据，不能带这种误读。
    """
    deadline = time.perf_counter() + timeout_s
    note = "未取到 info"
    while time.perf_counter() < deadline:
        try:
            info = await cache._client.ft(cache._index).info()
        except Exception as exc:  # noqa: BLE001 - 读不到就继续等，最后一票否决
            note = f"info 读取失败 {type(exc).__name__}"
            await asyncio.sleep(0.5)
            continue
        ready, note = _backfill_verdict(info)
        if ready:
            return note
        await asyncio.sleep(0.5)
    raise SystemExit(
        f"索引回填未在 {timeout_s:.0f}s 内就绪（{note}）——中止基准。"
        "先看 maxmemory 是否触发 backfill_paused_by_oom，再用 --backfill-timeout 放宽"
    )


def _config(args: argparse.Namespace, *, seed: bool) -> CacheConfig:
    return CacheConfig(
        enabled=True,
        backend="valkey",
        valkey_url=args.url,
        l1_ttl_seconds=3600,
        l2_ttl_seconds=1800,
        null_ttl_seconds=60,
        threshold=0.05,
        federation_threshold=0.05,
        vector_dim=args.dim,
        embedding_model="bench-sine",
        connect_timeout_ms=500 if seed else 50,
        command_timeout_ms=1000 if seed else 100,
        write_queue_max=args.batch,
        key_prefix=args.prefix,
    )


_WRITE_COUNTERS = ("dropped_writes", "error", "skipped_no_tenant", "skipped_pii")


async def _seed(cache: ValkeySemanticCache, args: argparse.Namespace, per_tenant: int) -> dict[str, int]:
    """灌数据并返回**写侧**计数增量（读侧后端从不写，写丢弃只能在写侧读到）。"""
    started = time.perf_counter()
    before = cache.get_stats()
    written = 0
    for tenant in args.tenants_list:
        for index in range(per_tenant):
            seed = _seed_int(tenant, index)
            await cache.set(
                tenant_id=tenant,
                intent="bench",
                rewritten_query=f"seed:{tenant}:{index}",
                value={"answer": f"answer-{tenant}-{index}"},
                embedding=_vector(seed, args.dim),
                ttl_seconds=3600,
            )
            written += 1
            if written % args.batch == 0:
                await cache.flush()
                elapsed = time.perf_counter() - started
                print(
                    f"  seeded {written}/{args.entries} ({written / max(elapsed, 1e-9):.0f}/s)",
                    file=sys.stderr,
                    flush=True,
                )
    await cache.flush()
    after = cache.get_stats()
    deltas = {
        "written": written,
        "dropped_writes": int(after.get("dropped_writes", 0)) - int(before.get("dropped_writes", 0)),
        "error": int(after.get("error", 0)) - int(before.get("error", 0)),
        "skipped_no_tenant": int(after.get("skipped_no_tenant", 0)) - int(before.get("skipped_no_tenant", 0)),
        "skipped_pii": int(after.get("skipped_pii", 0)) - int(before.get("skipped_pii", 0)),
    }
    print(
        f"  seed done: {written} entries in {time.perf_counter() - started:.1f}s "
        f"(dropped={deltas['dropped_writes']} skipped_pii={deltas['skipped_pii']})",
        file=sys.stderr,
        flush=True,
    )
    return deltas


async def _measure(cache: ValkeySemanticCache, args: argparse.Namespace, per_tenant: int) -> dict[str, Any]:
    # 等 Search 的后台回填真的结束再计时：原先固定 sleep(2.0) 对 10 万条 512 维根本不够，
    # 测出来的低命中率量的是"索引还在回填"而不是容量；判据见 _backfill_verdict。
    note = await _wait_backfill(cache, args.backfill_timeout)
    print(f"  backfill ready: {note}", file=sys.stderr, flush=True)

    latencies: list[float] = []
    exceptions = 0
    hits = 0
    stats_before = cache.get_stats()

    async def one(n: int) -> None:
        nonlocal exceptions, hits
        tenant = args.tenants_list[n % len(args.tenants_list)]
        index = (n * 7919) % per_tenant
        seed = _seed_int(tenant, index)
        if n % 2 == 0:
            # L1 精确命中：同 key，不需要向量
            query, embedding = f"seed:{tenant}:{index}", None
        else:
            # L2 语义命中：key 不同、向量相同（distance=0）
            query, embedding = f"probe:{n}", _vector(seed, args.dim)
        started = time.perf_counter()
        try:
            hit = await cache.get(
                tenant_id=tenant,
                intent="bench",
                rewritten_query=query,
                embedding=embedding,
            )
            if hit is not None:
                hits += 1
        except Exception:  # noqa: BLE001 - 基准要把任何异常计入错误率
            exceptions += 1
        finally:
            latencies.append((time.perf_counter() - started) * 1000.0)

    total = int(args.qps * args.duration)
    interval = 1.0 / args.qps
    started = time.perf_counter()
    tasks: list[asyncio.Task] = []
    for n in range(total):
        delay = started + n * interval - time.perf_counter()
        if delay > 0:
            await asyncio.sleep(delay)
        tasks.append(asyncio.create_task(one(n)))
    await asyncio.gather(*tasks)
    elapsed = time.perf_counter() - started

    stats_after = cache.get_stats()
    backend_errors = int(stats_after.get("error", 0)) - int(stats_before.get("error", 0))
    errors = exceptions + backend_errors
    return {
        "requests": total,
        "duration_s": round(elapsed, 3),
        "achieved_qps": round(total / max(elapsed, 1e-9), 1),
        "latency_ms": {
            "p50": round(_percentile(latencies, 0.50), 3),
            "p95": round(_percentile(latencies, 0.95), 3),
            "p99": round(_percentile(latencies, 0.99), 3),
        },
        "error_rate": round(errors / max(total, 1), 6),
        "errors": errors,
        "hit_rate": round(hits / max(total, 1), 4),
    }


def _budgets(result: dict[str, Any]) -> dict[str, bool]:
    """预算判定（纯函数，可单测）：写侧计数取自 seed 阶段，不是读侧后端的零值。"""
    latency = result["latency_ms"]
    writes = result["write_phase"]
    return {
        "p95": latency["p95"] <= _BUDGET_P95_MS,
        "p99": latency["p99"] <= _BUDGET_P99_MS,
        "error_rate": result["error_rate"] < _BUDGET_ERROR_RATE,
        "memory": result["memory_delta_bytes"] <= _BUDGET_MEMORY_BYTES,
        "dropped_writes": int(writes["dropped_writes"]) == 0,
        # 静默跳过（无租户/PII）会让命中率看起来像容量问题，必须单独翻红
        "write_skips": int(writes["skipped_no_tenant"]) + int(writes["skipped_pii"]) == 0,
        "hit_rate": result["hit_rate"] >= _MIN_HIT_RATE,
    }


async def _cleanup(cache: ValkeySemanticCache, args: argparse.Namespace) -> None:
    client = cache._client
    ns = cache._ns
    deleted = 0
    cursor = 0
    try:
        while True:
            cursor, keys = await client.scan(cursor=cursor, match=f"{ns}*", count=1000)
            if keys:
                await client.unlink(*keys)
                deleted += len(keys)
            if cursor == 0:
                break
    except Exception as exc:  # noqa: BLE001 - 清理失败只告警（基准前置可能已不可达）
        print(f"  warning: cleanup scan failed: {exc}", file=sys.stderr)
        return
    try:
        # 裸命令而不是 `ft().dropindex(delete_documents=False)`：valkey-py 6.2.0 在该分支会把
        # 空串当第三个参数发出（`FT.DROPINDEX <idx> ""`），服务器报 wrong number of arguments
        # ⇒ 清理会静默失败并留下一条 warning（2026-10-26 真机读数）。这里要的是"不带 DD 删索引"。
        await client.execute_command("FT.DROPINDEX", cache._index)
    except Exception as exc:  # noqa: BLE001 - 清理失败只告警，不影响基准结论
        print(f"  warning: drop index failed: {exc}", file=sys.stderr)
    print(f"  cleanup: deleted {deleted} keys, dropped {cache._index}", file=sys.stderr)


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    run_id = f"{int(time.time())}"
    scope = args.scope or f"bench{run_id}"
    per_tenant = args.entries // len(args.tenants_list)
    if per_tenant <= 0:
        raise SystemExit("--entries 必须大于租户数")

    seed_cache = ValkeySemanticCache(_config(args, seed=True), scope, embedder=_FixedEmbedder(args.dim))
    query_cache = ValkeySemanticCache(_config(args, seed=False), scope, embedder=_FixedEmbedder(args.dim))
    try:
        await seed_cache.startup()
        health = await seed_cache.health()
        if not health.ready:
            raise SystemExit(f"Valkey 不可用（{health.degraded_reason}），基准中止")
        client = seed_cache._client
        try:
            before = await client.info("memory")
        except Exception as exc:  # noqa: BLE001 - 环境前置不满足时给出可读错误
            raise SystemExit(f"读取 Valkey 内存失败（需要真实实例 + Search 模块）：{exc}") from exc
        print(f"  namespace: {seed_cache._ns}", file=sys.stderr)
        print(f"  index: {seed_cache._index}", file=sys.stderr)
        write_phase = await _seed(seed_cache, args, per_tenant)
        after = await client.info("memory")
        memory_delta = int(after.get("used_memory", 0)) - int(before.get("used_memory", 0))

        await query_cache.startup()
        measured = await _measure(query_cache, args, per_tenant)
        result: dict[str, Any] = {
            "entries": per_tenant * len(args.tenants_list),
            "dim": args.dim,
            "tenants": args.tenants_list,
            "qps_target": args.qps,
            "scope": scope,
            **measured,
            "write_phase": write_phase,
            "dropped_writes": write_phase["dropped_writes"],
            "memory_delta_bytes": memory_delta,
            "memory_delta_mb": round(memory_delta / 1024 / 1024, 1),
            "memory_used_bytes": int(after.get("used_memory", 0)),
            "memory_used_mb": int(after.get("used_memory", 0)) // 1024 // 1024,
        }
        budgets = _budgets(result)
        result["budgets"] = budgets
        result["passed"] = all(budgets.values())
        return result
    finally:
        try:
            if args.cleanup:
                await _cleanup(seed_cache, args)
        finally:
            await query_cache.aclose()
            await seed_cache.aclose()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Valkey 语义缓存容量基准")
    parser.add_argument("--url", default=os.getenv("VALKEY_URL", "redis://127.0.0.1:6379/0"))
    parser.add_argument("--entries", type=int, default=100_000)
    parser.add_argument("--dim", type=int, default=512)
    parser.add_argument("--tenants", default="tenant-a,tenant-b,tenant-c,tenant-d")
    parser.add_argument("--qps", type=float, default=200.0)
    parser.add_argument("--duration", type=float, default=20.0)
    parser.add_argument("--batch", type=int, default=1000, help="每批 flush 的写入条数")
    parser.add_argument(
        "--backfill-timeout",
        type=float,
        default=180.0,
        help="等索引后台回填就绪的上限秒数；超时即中止基准（不拿回填中的索引量命中率）",
    )
    parser.add_argument("--prefix", default="cache:bench:v1")
    parser.add_argument("--scope", default="", help="默认 bench<时间戳>，保证索引/命名空间不串")
    parser.add_argument("--json-out", default="")
    parser.add_argument("--no-cleanup", dest="cleanup", action="store_false", default=True)
    args = parser.parse_args(argv)
    args.tenants_list = [t.strip() for t in str(args.tenants).split(",") if t.strip()]
    if not args.tenants_list:
        parser.error("--tenants 不能为空")
    return args


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        result = asyncio.run(_run(args))
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - 运维脚本边界：给可读错误而不是整屏栈
        print(f"基准执行失败：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False, indent=2)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
