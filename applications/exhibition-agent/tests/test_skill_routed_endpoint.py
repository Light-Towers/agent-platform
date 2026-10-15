"""「route(...) → 执行」的后半截：catalog 解析出的端点必须真的驱动 REST 调用。

前半截（门禁能拦）在 `test_skill_router_wiring.py`；本文件补的是 TODO §3 原句
`run_skill → route(skill_name, ctx, **params) → 执行` 里「执行」那一截——此前 skill
自己硬编码 `_REST_PATH`，catalog 的 endpoint 解析出来就丢掉了，两处各持一份端点真相。

判据不是「没报错」，而是三条可失败的断言：
  ① skill 实际请求的路径 == catalog 里 `venue_schedule` 的 path（spy 记录，不看返回值）；
  ② 未经路由（`routed_endpoint` 缺失）→ fail-closed，warehouse **零调用**；
  ③ `run_skill` 放行后确实把 endpoint 注入了 ctx（端到端，不靠读代码推断）。
"""

from __future__ import annotations

from typing import Any

from exhibition_agent.foundation.skill_router import _load_catalog, route
from exhibition_agent.graph.nodes import run_skill
from exhibition_agent.skills.base_skill import SkillContext
from exhibition_agent.skills.venue_schedule_query import VenueScheduleQuerySkill
from exhibition_agent.testing_helpers import ctx, ctx_header

CATALOG_ENDPOINT = _load_catalog()["tools"]["venue_schedule"]["endpoint"]


class _SpyClient:
    """镜像 ``WarehouseClient`` 的接口，只多记一层 path，不改变返回值。

    ``__getattr__`` 透传其余属性：替身必须在**所有**被触达的面上与真实协作者同形，
    否则"零调用"这类反证会因为替身缺方法而假成立。
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.paths: list[str] = []

    async def get_rest(self, path: str, **kwargs: Any) -> Any:
        self.paths.append(path)
        return await self._inner.get_rest(path, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def _skill_context(warehouse_client, *, routed_endpoint=CATALOG_ENDPOINT) -> SkillContext:
    ec = ctx()
    return SkillContext(
        execution_context=ec,
        execution_context_header=ctx_header(ec),
        warehouse_client=warehouse_client,
        context_mode="jwt",
        routed_endpoint=routed_endpoint,
    )


async def test_skill_requests_the_catalog_endpoint(warehouse_client):
    """① 实际打出去的路径来自 catalog，不是 skill 里的硬编码常量。"""
    spy = _SpyClient(warehouse_client)
    sc = _skill_context(spy)

    result = await VenueScheduleQuerySkill().run({"venue_id": "vn-001"}, sc)

    assert spy.paths == [CATALOG_ENDPOINT["path"]]
    assert result.error_code != "DATA_NOT_CONNECTED"


async def test_unrouted_skill_fails_closed_without_touching_warehouse(warehouse_client):
    """② 没有 routed_endpoint ⇒ 拒绝直连，warehouse 零调用（门禁不可绕过）。

    这条同时钉住了"直接调 skill.run 就能跳过门禁"的旧漏洞：现在跳过路由就拿不到端点，
    拿不到端点就打不出请求。
    """
    spy = _SpyClient(warehouse_client)
    sc = _skill_context(spy, routed_endpoint=None)

    result = await VenueScheduleQuerySkill().run({"venue_id": "vn-001"}, sc)

    assert spy.paths == []
    assert result.error_code == "DATA_NOT_CONNECTED"
    # answer 是 INV-10 的固定话术（PENDING_ANSWER），拒绝原因落在 warnings 里
    assert "Skill Router" in result.warnings[0]


async def test_endpoint_without_path_key_also_fails_closed(warehouse_client):
    """端点形状不对（缺 path）同样 fail-closed，不退化成请求 None。"""
    spy = _SpyClient(warehouse_client)
    sc = _skill_context(spy, routed_endpoint={"method": "GET"})

    result = await VenueScheduleQuerySkill().run({"venue_id": "vn-001"}, sc)

    assert spy.paths == []
    assert result.error_code == "DATA_NOT_CONNECTED"


async def test_run_skill_injects_catalog_endpoint_into_ctx(warehouse_client):
    """③ 端到端：run_skill 过门禁后把 route() 的 endpoint 注入 ctx，skill 据此发请求。"""
    spy = _SpyClient(warehouse_client)
    ec = ctx()
    state = {
        "skill_name": "venue.schedule.query",
        "execution_context": ec,
        "execution_context_header": ctx_header(ec),
        "warehouse_client": spy,
        "params": {"venue_id": "vn-001"},
    }

    out = await run_skill(state)

    assert out.get("error") is None, out
    assert spy.paths == [CATALOG_ENDPOINT["path"]]


async def test_router_resolves_to_the_same_endpoint_the_catalog_declares():
    """catalog 与 route() 不得各说一套：解析结果就是 venue_schedule 的端点。"""
    ec = ctx()
    result = route("get_venue_operation", ec, card="schedule", venue_id="vn-001")
    assert result["allowed"] is True
    assert result["endpoint"] == CATALOG_ENDPOINT
