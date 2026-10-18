# -*- coding: utf-8 -*-
"""取值只读探针用例（2026-10-18，P0-9/P0-7，C1–C9 逐条钉）。

钉九件事（对应方案 C1–C9）：
1. 单入口：核验只经 ValueResolver.resolve；
2. 批量 IN：同列多字面量一次查询、全参数化（字面量不进 SQL 文本）；
3. 分区谓词必带：取不到最新分区 ⇒ 不探（unknown，不是 missing）；
4. 缓存键含 source_snapshot：同版本重复问只打源一次；
5. 探针预算：LIMIT + 语句超时 + 信号量真的传到执行层；
6. 降级链：探针失败 ⇒ **unknown**（"探不到"≠"不存在"）；
7. linkable 白名单默认全关，关列记原因；
8. 基数闸门：UUID/时间戳/手机号/长文本/高基数一律关；
9. 零结果分诊探针 column_values 与核验路共用缓存与降级。
"""

from __future__ import annotations

import asyncio
from typing import Any

from nl2sql_service.services.value_resolver import (
    STATUS_EXISTS,
    STATUS_MISSING,
    STATUS_UNKNOWN,
    LinkablePolicy,
    LiteralProbe,
    ProbeCache,
    SourceSnapshotProvider,
    ValueResolver,
    ValueResolverConfig,
)


class _StubDw:
    """记录每次执行的 (sql, params, kwargs)；按路由返回预制行。

    带在途并发计数（in_flight/max_in_flight）——信号量是否生效不能靠
    "调用次数"证明，要看在途峰值。
    """

    def __init__(
        self,
        membership: list[dict] | None = None,
        distinct: list[dict] | None = None,
        snapshot: str | None = None,
        snapshot_sql: str = "",
        partition: str | None = None,
        boom: bool = False,
    ) -> None:
        self.membership = membership if membership is not None else [{"value": "已支付"}]
        self.distinct = distinct if distinct is not None else [{"value": "已支付"}, {"value": "待发货"}]
        self.snapshot = snapshot
        self.snapshot_sql = snapshot_sql
        self.partition = partition
        self.boom = boom
        self.calls: list[tuple[str, tuple, dict]] = []
        self.in_flight = 0
        self.max_in_flight = 0

    async def execute_probe(self, sql: str, params: tuple | None = None, **kwargs: Any) -> list[dict]:
        self.calls.append((sql, tuple(params or ()), kwargs))
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            await asyncio.sleep(0)  # 让出事件循环，真实并发才会交叠
            if self.boom:
                raise TimeoutError("statement timeout")
            if self.snapshot_sql and sql == self.snapshot_sql:
                return [{"v": self.snapshot}]
            if "max(dt)" in sql:
                return [{"v": self.partition}]
            if "DISTINCT" in sql:
                return self.distinct
            return self.membership
        finally:
            self.in_flight -= 1


def _resolver(dw: _StubDw, **cfg: Any) -> ValueResolver:
    config = ValueResolverConfig(**{**{"snapshot_sql": ""}, **cfg})
    return ValueResolver(
        dw_repository=dw,
        config=config,
        linkable=LinkablePolicy(allowlist=["orders.status", "customers.city"]),
    )


# ---------------------------------------------------------------------------
# C3：批量 IN + 参数化
# ---------------------------------------------------------------------------
async def test_resolve_uses_batch_in_with_parameters():
    dw = _StubDw(membership=[{"value": "已支付"}])
    out = await _resolver(dw).resolve(
        [LiteralProbe("orders", "status", "已支付"), LiteralProbe("orders", "status", "已退款")]
    )
    sql, params, _kwargs = dw.calls[-1]
    assert "= ANY(%s)" in sql, "同列多字面量必须一次批量 IN（C3）"
    assert "已支付" not in sql and "已退款" not in sql, "字面量不许进 SQL 文本"
    assert params[0] == ["已支付", "已退款"]
    assert [v.status for v in out.verdicts] == [STATUS_EXISTS, STATUS_MISSING]
    assert out.matched == ["已支付"] and out.unmatched == ["已退款"]
    assert out.dict_hit is True


async def test_resolve_disabled_returns_empty():
    dw = _StubDw()
    out = await _resolver(dw, enabled=False).resolve([LiteralProbe("orders", "status", "x")])
    assert out.verdicts == [] and dw.calls == []


# ---------------------------------------------------------------------------
# C7：白名单默认全关 + 原因可读
# ---------------------------------------------------------------------------
async def test_non_linkable_column_is_unknown_with_reason():
    dw = _StubDw()
    out = await _resolver(dw).resolve([LiteralProbe("users", "phone", "13800000000")])
    assert out.verdicts[0].status == STATUS_UNKNOWN
    assert out.verdicts[0].reason == "not in linkable whitelist"
    assert dw.calls == [], "未开 linkable 的列不许探源"


def test_linkable_policy_type_and_cardinality_gates():
    policy = LinkablePolicy(allowlist=["orders.status", "orders.uuid_col", "orders.created_at", "orders.note"])
    assert policy.decide("orders", "status", "varchar").allowed is True
    for col, dtype in (("uuid_col", "uuid"), ("created_at", "timestamptz"), ("note", "text")):
        decision = policy.decide("orders", col, dtype)
        assert decision.allowed is False
        assert decision.reason.startswith("denied type"), f"{col} 应按类型关: {decision.reason}"
    high = policy.decide("orders", "status", "varchar", declared_values=5000)
    assert high.allowed is False and "cardinality" in high.reason


# ---------------------------------------------------------------------------
# C5：分区谓词必带
# ---------------------------------------------------------------------------
async def test_partition_predicate_is_required_and_injected():
    dw = _StubDw(partition="2026-10-18")
    resolver = _resolver(dw, partition_column="dt", latest_partition_sql="SELECT max(dt) AS v FROM {table}")
    await resolver.resolve([LiteralProbe("orders", "status", "已支付")])

    partition_call = next(c for c in dw.calls if "max(dt)" in c[0])
    assert partition_call[2].get("statement_timeout_ms"), "最新分区查询也要短超时"
    probe_call = dw.calls[-1]
    assert " AND dt = %s" in probe_call[0], "分区谓词必须拼进探针 SQL"
    assert "2026-10-18" in probe_call[1], "最新分区值必须参数化传入"


async def test_probe_skipped_when_partition_unavailable():
    dw = _StubDw(partition=None)  # 最新分区取不到（返回 NULL）
    resolver = _resolver(dw, partition_column="dt", latest_partition_sql="SELECT max(dt) AS v FROM {table}")
    out = await resolver.resolve([LiteralProbe("orders", "status", "已支付")])

    assert out.verdicts[0].status == STATUS_UNKNOWN, "分区取不到 ⇒ 不探（C5），且不是 missing"
    assert not any("= ANY" in c[0] for c in dw.calls), "分区缺失时不许发起无分区谓词的扫描"


async def test_probe_allowed_without_partition_when_not_required():
    dw = _StubDw()
    resolver = _resolver(dw, partition_column="dt", latest_partition_sql="", partition_required=False)
    await resolver.resolve([LiteralProbe("orders", "status", "已支付")])
    assert any("= ANY" in c[0] for c in dw.calls)


# ---------------------------------------------------------------------------
# C6：缓存键含 source_snapshot
# ---------------------------------------------------------------------------
async def test_cache_hit_avoids_second_probe():
    dw = _StubDw(membership=[{"value": "已支付"}])
    resolver = _resolver(dw, snapshot_sql="SELECT '2026-10-18' AS v")
    probes = [LiteralProbe("orders", "status", "已支付")]

    await resolver.resolve(probes)
    calls_after_first = len([c for c in dw.calls if "= ANY" in c[0]])
    await resolver.resolve(probes)
    calls_after_second = len([c for c in dw.calls if "= ANY" in c[0]])

    assert calls_after_first == 1
    assert calls_after_second == 1, "同 snapshot 同列重复问只打源一次（C6）"


async def test_cache_invalidated_by_new_snapshot():
    cache = ProbeCache(ttl_seconds=900)
    key = ProbeCache.key("ds-1", "snap-a", "orders", "status", "membership")
    cache.set(key, ["已支付"])
    assert cache.get(key) == ["已支付"]
    other = ProbeCache.key("ds-1", "snap-b", "orders", "status", "membership")
    assert cache.get(other) is None, "snapshot 变化必须换键（不是覆盖旧值）"


def test_cache_expires():
    cache = ProbeCache(ttl_seconds=0)
    key = ("ds", "snap", "t", "c", "shape")
    cache.set(key, ["v"])
    assert cache.get(key) is None, "TTL=0 必须立即过期"


# ---------------------------------------------------------------------------
# C8：降级链——探不到 ≠ 不存在
# ---------------------------------------------------------------------------
async def test_probe_failure_degrades_to_unknown_not_missing():
    dw = _StubDw(boom=True)
    out = await _resolver(dw).resolve([LiteralProbe("orders", "status", "已支付")])
    assert out.verdicts[0].status == STATUS_UNKNOWN
    assert out.unmatched == [] and out.unknown == ["已支付"]
    assert out.dict_hit is False, "有 unknown 时不算字典命中（不能据此拒答）"


async def test_snapshot_sql_failure_falls_back_to_ttl_bucket():
    dw = _StubDw(boom=True)
    provider = SourceSnapshotProvider(dw, snapshot_sql="SELECT '2026-10-18' AS v", ttl_seconds=900)
    snapshot = await provider.current()
    assert snapshot.startswith("ttl-"), "水位取不到必须退 TTL 分桶（C8 第一环）"


async def test_snapshot_sql_value_used_when_available():
    dw = _StubDw(snapshot="2026-10-18", snapshot_sql="SELECT '2026-10-18' AS v")
    provider = SourceSnapshotProvider(dw, snapshot_sql="SELECT '2026-10-18' AS v")
    assert await provider.current() == "2026-10-18"


# ---------------------------------------------------------------------------
# C7：探针预算真的传到执行层
# ---------------------------------------------------------------------------
async def test_probe_budget_reaches_execution_layer():
    dw = _StubDw()
    resolver = _resolver(dw, probe_limit=7, statement_timeout_ms=1234, connect_timeout=1.5)
    await resolver.resolve([LiteralProbe("orders", "status", "已支付")])
    _sql, params, kwargs = dw.calls[-1]
    assert params[-1] == 7, "LIMIT 必须来自配置"
    assert kwargs["statement_timeout_ms"] == 1234
    assert kwargs["connect_timeout"] == 1.5


async def test_concurrency_semaphore_limits_parallel_probes():
    """在途峰值 ≤ 配置的并发上限（不是调用次数——次数会被缓存抹掉）。"""
    dw = _StubDw()
    resolver = _resolver(dw, concurrency=1)
    await asyncio.gather(
        resolver.resolve([LiteralProbe("orders", "status", "a")]),
        resolver.resolve([LiteralProbe("customers", "city", "北京")]),
    )
    assert dw.max_in_flight <= 1, f"并发突破信号量上限: {dw.max_in_flight}"
    assert len([c for c in dw.calls if "= ANY" in c[0]]) == 2, "两列都必须探到"


async def test_concurrency_allows_configured_parallelism():
    dw = _StubDw()
    resolver = _resolver(dw, concurrency=2)
    await asyncio.gather(
        resolver.resolve([LiteralProbe("orders", "status", "a")]),
        resolver.resolve([LiteralProbe("customers", "city", "北京")]),
    )
    assert dw.max_in_flight == 2, "concurrency=2 时应允许两个探针交叠"


# ---------------------------------------------------------------------------
# C9：零结果分诊探针
# ---------------------------------------------------------------------------
async def test_column_values_probe_with_cache_and_gate():
    dw = _StubDw(distinct=[{"value": "已支付"}, {"value": "待发货"}])
    resolver = _resolver(dw)

    values = await resolver.column_values("orders", "status", "varchar")
    assert values == ["已支付", "待发货"]
    assert "DISTINCT" in dw.calls[-1][0]

    cached = await resolver.column_values("orders", "status", "varchar")
    assert cached == values
    assert len([c for c in dw.calls if "DISTINCT" in c[0]]) == 1, "分诊探针也必须走缓存（C6）"

    denied = await resolver.column_values("users", "phone", "varchar")
    assert denied is None, "未开 linkable 的列不探（记原因，不抛）"


async def test_illegal_identifiers_rejected_before_sql():
    dw = _StubDw()
    resolver = _resolver(dw)
    out = await resolver.resolve([LiteralProbe("orders; drop", "status", "x")])
    # 白名单先拦（表不在 linkable），非法标识符根本到不了 SQL 拼装层
    assert out.verdicts[0].status == STATUS_UNKNOWN
    assert dw.calls == []
