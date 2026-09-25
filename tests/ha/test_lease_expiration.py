"""§HA 场景 4：kill during lease renewal → lease 过期 → B 接管。

验证 ownership 语义（用户红线 I5：同一时间最多一个 owner）：
- B 不能在 A 还持有有效 lease 时抢走 execution（acquire 必须返回 False）。
- A 的 lease 不会永久存在（expires_at 自动过期）。
- 过期后 B acquire 成功，且 owner 只有一个。
"""

import pytest

from .conftest import unique_execution_id
from .helpers import wait_lease_expiry


@pytest.mark.anyio
async def test_b_cannot_steal_while_a_holds_valid_lease(ha_stores):
    own = ha_stores["ownership"]
    execution_id = unique_execution_id("HA")

    # A 持有有效 lease（ttl 10s）
    assert await own.acquire(execution_id, "replica-A", 10.0) is True
    assert await own.get_owner(execution_id) == "replica-A"

    # B 在 A lease 有效时尝试接管 → 必须失败（不能双 owner）
    assert await own.acquire(execution_id, "replica-B", 10.0) is False, "B 不应抢走有效 lease"
    assert await own.get_owner(execution_id) == "replica-A", "owner 被非法篡改"

    # I5：同一时间最多一个 owner
    print("[场景4] A 持有效 lease 时 B 抢占失败，owner 仍为 A：PASS")


@pytest.mark.anyio
async def test_lease_expires_then_b_takes_over(ha_stores):
    own = ha_stores["ownership"]
    execution_id = unique_execution_id("HA")

    # A 持有短 ttl lease（0.4s），随后不续租（模拟 kill）
    assert await own.acquire(execution_id, "replica-A", 0.4) is True
    assert await own.get_owner(execution_id) == "replica-A"

    # lease 自动过期（PG expires_at）
    assert await wait_lease_expiry(own, execution_id, timeout_s=3.0), "A lease 未自动过期"

    # 过期后 B acquire 成功
    assert await own.acquire(execution_id, "replica-B", 10.0) is True
    assert await own.get_owner(execution_id) == "replica-B"
    print("[场景4] A lease 过期后 B 接管成功，单 owner：PASS")
