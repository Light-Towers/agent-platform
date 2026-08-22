"""§HA 场景 6：双恢复竞争（dual-recovery contention）。

A crash 后，B 和 C 同时发现 lease 过期并尝试接管。数据库（PG 行锁 + CAS）必须保证
**最终只有一个 owner**，不能出现最后写覆盖（B→owner=B，C→owner=C 都被当成拥有）。

这是 Admission/lease/ownership 真正需要用并发验证的地方（用户红线 I5）。
"""

import asyncio

import pytest

from .conftest import unique_execution_id
from .helpers import wait_lease_expiry


@pytest.mark.anyio
async def test_dual_recovery_single_owner(ha_stores):
    own = ha_stores["ownership"]
    execution_id = unique_execution_id("HA")

    # A 持有短 ttl lease 后"crash"（不续租不释放）
    assert await own.acquire(execution_id, "replica-A", 0.3) is True
    assert await wait_lease_expiry(own, execution_id, timeout_s=3.0), "A lease 未过期"

    # B、C 同时发现 lease 过期，并发 acquire
    async def try_takeover(name: str) -> tuple[str, bool]:
        return name, await own.acquire(execution_id, name, 10.0)

    results = await asyncio.gather(
        try_takeover("replica-B"), try_takeover("replica-C")
    )
    granted = [n for n, ok in results if ok]
    denied = [n for n, ok in results if not ok]

    # I5：恰好一个成功、一个失败（单 owner），无最后写覆盖
    assert len(granted) == 1, f"并发接管应有且仅有一个成功: {results}"
    assert len(denied) == 1, f"应恰好一个被拒: {results}"

    # 最终 owner 是成功者，且只有一个
    final_owner = await own.get_owner(execution_id)
    assert final_owner == granted[0], f"最终 owner 异常: {final_owner}"
    print(f"[场景6] B/C 并发接管：{granted[0]} 成功、{denied[0]} 被拒，单 owner：PASS")
