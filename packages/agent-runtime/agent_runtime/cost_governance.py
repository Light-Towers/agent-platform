"""Cost / Resource Governance 多层预算（V3 补-3）。

现状（v3 之前）：Admission 有 per-user/per-session/global rate limit（1 秒窗口），
但无 per-tenant cost / token / duration 预算，无多层治理。

本模块补上多层预算：
```
Request → Execution → Skill → Tenant → Platform
```

- ``BudgetDimension``：预算维度（requests / tokens / cost / duration）；
- ``BudgetLimit``：单维度限额（limit + window）；
- ``BudgetStore``：使用量持久化契约（InMemory + PG 可扩展）；
- ``CostGovernance``：检查 + 记录 + 查询，超限拒绝。

窗口策略：固定时间窗口（按 ``window_seconds`` 分桶），简单且足够。
"""

from __future__ import annotations

import abc
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any


class BudgetDimension(str, Enum):
    """预算维度。"""

    REQUESTS = "requests"
    TOKENS = "tokens"
    COST = "cost"  # 货币成本（元）
    DURATION = "duration"  # 秒


@dataclass
class BudgetLimit:
    """单维度限额。"""

    dimension: BudgetDimension
    limit: float
    window_seconds: float = 3600.0  # 窗口大小（默认 1 小时）


@dataclass
class BudgetUsage:
    """单维度使用量。"""

    tenant_id: str
    dimension: BudgetDimension
    used: float
    limit: float
    window_seconds: float
    remaining: float = 0.0

    def __post_init__(self) -> None:
        self.remaining = max(0.0, self.limit - self.used)

    @property
    def exceeded(self) -> bool:
        return self.used > self.limit

    @property
    def utilization(self) -> float:
        """使用率（0.0 ~ 1.0+）。"""
        return self.used / self.limit if self.limit > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "dimension": self.dimension.value,
            "used": self.used,
            "limit": self.limit,
            "remaining": self.remaining,
            "utilization": self.utilization,
            "exceeded": self.exceeded,
        }


class BudgetExceeded(RuntimeError):
    """预算超限。"""

    def __init__(self, usage: BudgetUsage) -> None:
        self.usage = usage
        super().__init__(
            f"预算超限：tenant={usage.tenant_id} dimension={usage.dimension.value} "
            f"used={usage.used} limit={usage.limit}"
        )


class BudgetStore(abc.ABC):
    """预算使用量持久化契约。"""

    @abc.abstractmethod
    async def record(
        self, tenant_id: str, dimension: BudgetDimension, amount: float, window_seconds: float
    ) -> float:
        """记录使用量，返回当前窗口内累计使用量。"""

    @abc.abstractmethod
    async def get_usage(
        self, tenant_id: str, dimension: BudgetDimension, window_seconds: float
    ) -> float:
        """查询当前窗口内累计使用量。"""


class InMemoryBudgetStore(BudgetStore):
    """进程内预算存储（固定窗口分桶）。"""

    def __init__(self) -> None:
        # key: (tenant_id, dimension, bucket_index) → amount
        self._buckets: dict[tuple[str, BudgetDimension, int], float] = {}

    def _bucket_index(self, window_seconds: float) -> int:
        return int(time.time() // window_seconds)

    async def record(
        self, tenant_id: str, dimension: BudgetDimension, amount: float, window_seconds: float
    ) -> float:
        key = (tenant_id, dimension, self._bucket_index(window_seconds))
        self._buckets[key] = self._buckets.get(key, 0.0) + amount
        return self._buckets[key]

    async def get_usage(
        self, tenant_id: str, dimension: BudgetDimension, window_seconds: float
    ) -> float:
        key = (tenant_id, dimension, self._bucket_index(window_seconds))
        return self._buckets.get(key, 0.0)


class CostGovernance:
    """多层预算治理：Request → Execution → Skill → Tenant → Platform。

    用法：
    ```
    gov = CostGovernance(
        store,
        limits={
            BudgetDimension.REQUESTS: BudgetLimit(BudgetDimension.REQUESTS, limit=1000),
            BudgetDimension.TOKENS: BudgetLimit(BudgetDimension.TOKENS, limit=100000),
            BudgetDimension.COST: BudgetLimit(BudgetDimension.COST, limit=10.0),
        },
    )
    # 检查
    await gov.check(tenant_id, BudgetDimension.TOKENS, estimated_tokens=500)
    # 记录实际使用
    await gov.record(tenant_id, BudgetDimension.TOKENS, actual_tokens=480)
    ```
    """

    def __init__(
        self,
        store: BudgetStore,
        limits: dict[BudgetDimension, BudgetLimit] | None = None,
    ) -> None:
        self._store = store
        self._limits = limits or {}

    def set_limit(self, limit: BudgetLimit) -> None:
        self._limits[limit.dimension] = limit

    async def check(
        self, tenant_id: str, dimension: BudgetDimension, estimated_amount: float = 0
    ) -> BudgetUsage:
        """检查是否超限。返回当前使用量（不记录）。

        超限时抛 BudgetExceeded；调用方可选择 catch 后拒绝请求或降级。
        """
        limit = self._limits.get(dimension)
        if limit is None:
            return BudgetUsage(tenant_id, dimension, 0.0, float("inf"), 0.0)

        used = await self._store.get_usage(tenant_id, dimension, limit.window_seconds)
        projected = used + estimated_amount
        usage = BudgetUsage(tenant_id, dimension, projected, limit.limit, limit.window_seconds)
        if usage.exceeded:
            raise BudgetExceeded(usage)
        return usage

    async def record(
        self, tenant_id: str, dimension: BudgetDimension, amount: float
    ) -> BudgetUsage:
        """记录实际使用量。超限时抛 BudgetExceeded。"""
        limit = self._limits.get(dimension)
        if limit is None:
            return BudgetUsage(tenant_id, dimension, 0.0, float("inf"), 0.0)

        total = await self._store.record(tenant_id, dimension, amount, limit.window_seconds)
        usage = BudgetUsage(tenant_id, dimension, total, limit.limit, limit.window_seconds)
        if usage.exceeded:
            raise BudgetExceeded(usage)
        return usage

    async def get_usage(
        self, tenant_id: str, dimension: BudgetDimension
    ) -> BudgetUsage | None:
        """查询当前使用量（不检查超限）。"""
        limit = self._limits.get(dimension)
        if limit is None:
            return None
        used = await self._store.get_usage(tenant_id, dimension, limit.window_seconds)
        return BudgetUsage(tenant_id, dimension, used, limit.limit, limit.window_seconds)

    async def get_all_usage(self, tenant_id: str) -> dict[BudgetDimension, BudgetUsage]:
        """查询所有维度的使用量。"""
        result: dict[BudgetDimension, BudgetUsage] = {}
        for dimension, limit in self._limits.items():
            used = await self._store.get_usage(tenant_id, dimension, limit.window_seconds)
            result[dimension] = BudgetUsage(
                tenant_id, dimension, used, limit.limit, limit.window_seconds
            )
        return result


__all__ = [
    "BudgetDimension",
    "BudgetLimit",
    "BudgetUsage",
    "BudgetExceeded",
    "BudgetStore",
    "InMemoryBudgetStore",
    "CostGovernance",
]
