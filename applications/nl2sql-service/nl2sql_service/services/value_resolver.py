"""取值解析单入口（P0-9 / P0-7）：只读探针 + 跟随版本的缓存 + 降级链。

**这是服务内唯一可以碰数据源做取值匹配的地方**（C1 单入口）。设计纪律：

- **C2 召回阶段零源查询**：候选列的取值全集不在召回期拉取（那正是"取值
  副本"的老路）；这里只做**生成后**的字面量核验——问句里/生成的 SQL 里
  出现了什么字面量，就核验什么。
- **C3 批量 IN**：同列多字面量一次 `= ANY(%s)` + `GROUP BY`，不是 N 次
  单点查询；全参数化，字面量不进 SQL 文本。
- **C5 分区谓词必带**：配了分区列就必须带最新分区值（ Doris 全分区扫描
  是不可接受的）；最新分区值取不到 ⇒ **不探**（结果 unknown，不猜）。
- **C6 缓存键 = (datasource, source_snapshot, table, column, shape)**：
  同一版本内重复问同一列只打源一次；源无水位口径时退 TTL 分桶
  （min(snapshot, 15min)），不是"永久缓存"。
- **C7 探针预算**：LIMIT + per-statement 超时（事务内 SET LOCAL，退出即
  撤，不污染池连接）+ 信号量限并发。
- **C8 降级链**：任一环节失败降为 **unknown**——"探不到"≠"不存在"，
  这个区分是 P0-8③ 零结果分诊的前提，混同就会把系统故障说成"无数据"。
- **C9 标识符白名单**：表名/列名过 `agent_core.sql.identifiers`，探针 SQL
  的标识符不来自用户文本。
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from agent_core.logging import get_logger
from agent_core.sql.identifiers import validate_identifier

logger = get_logger(__name__)

#: 字面量核验结果三态。unknown 与 missing 的区分是契约（C8）。
STATUS_EXISTS = "exists"
STATUS_MISSING = "missing"
STATUS_UNKNOWN = "unknown"

#: P1-2 基数闸门：这些类型一律不许开 linkable（枚举/城市/行业才开）
_DENY_TYPES = ("uuid", "timestamp", "timestamptz", "datetime", "date", "json", "jsonb", "text", "phone", "blob", "bytea")
#: 声明取值数超过该值 ⇒ 高基数，关 linkable（自由文本不该进码表路）
_MAX_DECLARED_VALUES = 2000


@dataclass(frozen=True)
class LiteralProbe:
    """一个待核验字面量：(表, 列, 字面量)。表/列来自 SQL 解析，不是用户原话。"""

    table: str
    column: str
    literal: str


@dataclass
class ProbeDecision:
    """单列是否允许探针 + 原因（P1-2 闸门；原因要可读、可追溯）。"""

    allowed: bool
    reason: str = ""


@dataclass
class LiteralVerdict:
    table: str
    column: str
    literal: str
    status: str
    reason: str = ""


@dataclass
class ResolutionResult:
    verdicts: list[LiteralVerdict] = field(default_factory=list)

    @property
    def matched(self) -> list[str]:
        return [v.literal for v in self.verdicts if v.status == STATUS_EXISTS]

    @property
    def unmatched(self) -> list[str]:
        return [v.literal for v in self.verdicts if v.status == STATUS_MISSING]

    @property
    def unknown(self) -> list[str]:
        return [v.literal for v in self.verdicts if v.status == STATUS_UNKNOWN]

    @property
    def dict_hit(self) -> bool:
        """全部有确定结论才算字典命中（有 unknown ⇒ 不算，也不能据此拒答）。"""
        return bool(self.verdicts) and not self.unknown

    def to_dict(self) -> dict[str, Any]:
        return {
            "matched": self.matched,
            "unmatched": self.unmatched,
            "unknown": self.unknown,
            "dict_hit": self.dict_hit,
            "verdicts": [vars(v) for v in self.verdicts],
        }


class LinkablePolicy:
    """P1-2 基数闸门：哪些列允许被探针查询。

    默认**全关**（D6/P0-9：候选列由白名单控制）——开着的是枚举/城市/行业
    这类低基数列；UUID/时间戳/手机号/长文本一律关，且**记录原因**。
    """

    def __init__(self, allowlist: list[str] | None = None, max_declared_values: int = _MAX_DECLARED_VALUES) -> None:
        self._allow = {c.strip().lower() for c in (allowlist or []) if c.strip()}
        self._max_declared = max_declared_values

    def decide(self, table: str, column: str, data_type: str = "", declared_values: int = 0) -> ProbeDecision:
        qualified = f"{table}.{column}".lower()
        if qualified not in self._allow:
            return ProbeDecision(False, "not in linkable whitelist")
        lowered = (data_type or "").lower()
        if any(t in lowered for t in _DENY_TYPES):
            return ProbeDecision(False, f"denied type: {data_type}")
        if declared_values > self._max_declared:
            return ProbeDecision(False, f"cardinality too high: {declared_values} declared values")
        return ProbeDecision(True)


class SourceSnapshotProvider:
    """source_snapshot 提供者（P0-9②）：配置 SQL 优先，否则 TTL 分桶兜底。"""

    def __init__(self, dw_repository: Any, snapshot_sql: str = "", ttl_seconds: int = 900) -> None:
        self._dw = dw_repository
        self._sql = snapshot_sql.strip()
        self._ttl = ttl_seconds

    async def current(self) -> str:
        if self._sql:
            try:
                rows = await self._dw.execute_probe(self._sql, statement_timeout_ms=2000)
                if rows:
                    value = next(iter(rows[0].values()))
                    return str(value)
            except Exception:  # noqa: BLE001 - 取不到水位就走 TTL 兜底（C8 降级链第一环）
                logger.warning("source snapshot sql failed, fallback to ttl bucket", exc_info=True)
        bucket = int(time.time() // self._ttl)
        return f"ttl-{bucket}"


class ProbeCache:
    """探针结果缓存（C6）：键含 source_snapshot，版本不变即命中。"""

    def __init__(self, ttl_seconds: int = 900) -> None:
        self._ttl = ttl_seconds
        self._store: dict[tuple, tuple[float, list[str]]] = {}

    @staticmethod
    def key(datasource_id: str, snapshot: str, table: str, column: str, shape: str) -> tuple:
        return (datasource_id, snapshot, table, column, shape)

    def get(self, key: tuple) -> list[str] | None:
        hit = self._store.get(key)
        if hit is None:
            return None
        expires_at, values = hit
        # expires_at 是"过期时刻"语义：到达即过期（>=）。与预算超限判定的严格大于
        # 偏好不冲突——那是"用量恰好等于限额=合法用满"；此处时间戳相等在
        # Windows 时钟粒度（~15ms）下真实可发生，TTL=0 时 > 会漏判未过期。
        if time.time() >= expires_at:
            self._store.pop(key, None)
            return None
        return values

    def set(self, key: tuple, values: list[str]) -> None:
        self._store[key] = (time.time() + self._ttl, values)


@dataclass
class ValueResolverConfig:
    enabled: bool = True
    probe_limit: int = 50
    statement_timeout_ms: int = 2000
    connect_timeout: float = 2.0
    concurrency: int = 2
    cache_ttl_seconds: int = 900
    snapshot_sql: str = ""
    # 分区谓词（C5）：配了分区列就必须带最新分区值，取不到就不探
    partition_column: str = ""
    latest_partition_sql: str = ""
    partition_required: bool = True


class ValueResolver:
    """取值匹配唯一入口：字面量核验 + 零结果分诊探针。"""

    def __init__(
        self,
        dw_repository: Any,
        config: ValueResolverConfig | None = None,
        linkable: LinkablePolicy | None = None,
        datasource_id: str = "",
    ) -> None:
        self._dw = dw_repository
        self._config = config or ValueResolverConfig()
        self._linkable = linkable or LinkablePolicy()
        self._datasource_id = datasource_id
        self._snapshots = SourceSnapshotProvider(dw_repository, self._config.snapshot_sql, self._config.cache_ttl_seconds)
        self._cache = ProbeCache(self._config.cache_ttl_seconds)
        self._semaphore = asyncio.Semaphore(self._config.concurrency)
        self._latest_partition: dict[str, str] = {}

    # ------------------------------------------------------------------
    # 字面量核验（P0-8②/C3）
    # ------------------------------------------------------------------
    async def resolve(self, probes: list[LiteralProbe], data_types: dict[str, str] | None = None) -> ResolutionResult:
        if not self._config.enabled or not probes:
            return ResolutionResult()
        data_types = data_types or {}
        snapshot = await self._snapshots.current()
        result = ResolutionResult()
        by_column: dict[tuple[str, str], list[LiteralProbe]] = {}
        for probe in probes:
            decision = self._linkable.decide(probe.table, probe.column, data_types.get(f"{probe.table}.{probe.column}", ""))
            if not decision.allowed:
                result.verdicts.append(LiteralVerdict(probe.table, probe.column, probe.literal, STATUS_UNKNOWN, decision.reason))
                continue
            by_column.setdefault((probe.table, probe.column), []).append(probe)

        for (table, column), group in by_column.items():
            literals = [p.literal for p in group]
            existing = await self._existing_values(table, column, literals, snapshot)
            for probe in group:
                if existing is None:
                    # 降级链终点：探不到 ≠ 不存在（C8）
                    result.verdicts.append(LiteralVerdict(table, column, probe.literal, STATUS_UNKNOWN, "probe failed or skipped"))
                elif probe.literal in existing:
                    result.verdicts.append(LiteralVerdict(table, column, probe.literal, STATUS_EXISTS))
                else:
                    result.verdicts.append(LiteralVerdict(table, column, probe.literal, STATUS_MISSING))
        return result

    async def _existing_values(self, table: str, column: str, literals: list[str], snapshot: str) -> list[str] | None:
        """返回该列中**确实存在**的字面量子集；None = 探不到（降级，非不存在）。

        2026-10-18 golden 首跑抓出的**设计缺陷**（真库 + 在线路径复现）：membership
        缓存的键不含 literals，而值只是"本轮问到且存在的子集"——缓存命中时，
        未覆盖的新字面量被直接判 **missing**（g01 问过 `已支付` ⇒ g02 问 `已退款`
        命中同一键 ⇒ 误判不存在 ⇒ 拦截进 correct 循环，而该值实际存在）。
        修法：缓存只当"已确认存在"的**正集合**；未覆盖的新字面量必须真探
        （探不到 ⇒ 整体降级 unknown，保持 C8"探不到≠不存在"语义）。
        """
        cache_key = ProbeCache.key(self._datasource_id, snapshot, table, column, "membership")
        confirmed = list(self._cache.get(cache_key) or [])
        unanswered = [lit for lit in literals if lit not in confirmed]
        if unanswered:
            probed = await self._probe_membership(table, column, unanswered, snapshot)
            if probed is None:
                return None  # 探不到 ⇒ 整体降级（C8），不当成"不存在"
            for value in probed:
                if value not in confirmed:
                    confirmed.append(value)
            self._cache.set(cache_key, confirmed)
        return [lit for lit in literals if lit in confirmed]

    async def _probe_membership(
        self, table: str, column: str, literals: list[str], snapshot: str
    ) -> list[str] | None:
        """真探一批字面量在该列的存在子集；None = 探不到（分区取不到/执行失败）。"""
        partition_sql, partition_params = await self._partition_predicate(table)
        if partition_sql is None:
            return None  # 分区必带但取不到 ⇒ 不探（C5）
        validate_identifier(table, "探针表名")
        validate_identifier(column, "探针列名")
        sql = (
            f"SELECT {column} AS value FROM {table} "
            f"WHERE {column} = ANY(%s){partition_sql} "
            f"GROUP BY {column} LIMIT %s"
        )
        try:
            async with self._semaphore:
                rows = await self._dw.execute_probe(
                    sql,
                    (literals, *partition_params, self._config.probe_limit),
                    statement_timeout_ms=self._config.statement_timeout_ms,
                    connect_timeout=self._config.connect_timeout,
                )
        except Exception:  # noqa: BLE001 - 探针失败一律降级 unknown，不当成"不存在"
            logger.warning("value probe failed (%s.%s), degrade to unknown", table, column, exc_info=True)
            return None
        return [str(r["value"]) for r in rows]

    # ------------------------------------------------------------------
    # 零结果分诊探针（P0-8③）
    # ------------------------------------------------------------------
    async def column_values(self, table: str, column: str, data_type: str = "", declared_values: int = 0) -> list[str] | None:
        """取该列实际取值（分诊用）；None = 探不到或不允许。"""
        decision = self._linkable.decide(table, column, data_type, declared_values)
        if not decision.allowed:
            logger.info("column %s.%s not probeable: %s", table, column, decision.reason)
            return None
        snapshot = await self._snapshots.current()
        cache_key = ProbeCache.key(self._datasource_id, snapshot, table, column, "distinct")
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached
        partition_sql, partition_params = await self._partition_predicate(table)
        if partition_sql is None:
            return None
        validate_identifier(table, "探针表名")
        validate_identifier(column, "探针列名")
        sql = f"SELECT DISTINCT {column} AS value FROM {table}{partition_sql} LIMIT %s"
        try:
            async with self._semaphore:
                rows = await self._dw.execute_probe(
                    sql,
                    (*partition_params, self._config.probe_limit),
                    statement_timeout_ms=self._config.statement_timeout_ms,
                    connect_timeout=self._config.connect_timeout,
                )
        except Exception:  # noqa: BLE001 - 同上：降级不当"不存在"
            logger.warning("column probe failed (%s.%s), degrade to unknown", table, column, exc_info=True)
            return None
        values = [str(r["value"]) for r in rows]
        self._cache.set(cache_key, values)
        return values

    # ------------------------------------------------------------------
    # 分区谓词（C5）
    # ------------------------------------------------------------------
    async def _partition_predicate(self, table: str) -> tuple[str | None, tuple]:
        """返回 (SQL 片段, 参数)；None = 必须带分区但取不到（调用方不探）。"""
        column = self._config.partition_column
        if not column:
            return "", ()
        validate_identifier(column, "分区列名")
        latest = self._latest_partition.get(table)
        if latest is None:
            template = self._config.latest_partition_sql
            if not template:
                logger.warning("partition column configured but no latest_partition_sql; skip probe")
                return (None, ()) if self._config.partition_required else ("", ())
            sql = template.format(table=table)
            try:
                rows = await self._dw.execute_probe(sql, statement_timeout_ms=self._config.statement_timeout_ms)
                value = next(iter(rows[0].values()), None) if rows else None
                latest = "" if value is None else str(value)
            except Exception:  # noqa: BLE001 - 取不到最新分区 ⇒ 必须不探（C5）
                logger.warning("latest partition probe failed (%s)", table, exc_info=True)
                return (None, ()) if self._config.partition_required else ("", ())
            if not latest:
                return (None, ()) if self._config.partition_required else ("", ())
            self._latest_partition[table] = latest
        return f" AND {column} = %s", (latest,)
