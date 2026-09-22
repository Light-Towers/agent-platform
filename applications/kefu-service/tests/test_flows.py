"""kefu Flow 测试：3 个业务流程节点契约 + 服务层数据查询。

mock LLM/LangGraph，测 order/logistics/postsale 3 个流程分支。
无外部依赖（services 层用 mock 数据，不依赖 DB）。
"""

from __future__ import annotations

from kefu_agent.flows.logistics_flow import (
    _format_logistics,
    build_logistics_flow,
    collect_tracking_id,
    query_logistics_info,
)
from kefu_agent.flows.order_flow import (
    _format_order,
    build_order_flow,
    collect_order_id,
    format_order_response,
    query_order_info,
)
from kefu_agent.flows.postsale_flow import (
    build_postsale_flow,
    collect_issue_type,
    format_postsale_response,
    query_postsale_policy_info,
)
from kefu_agent.services import (
    extract_issue_type,
    extract_order_id,
    extract_tracking_id,
    query_logistics,
    query_order,
    query_postsale_policy,
)


def _state(**kwargs):
    return {"user_message": "", "session_id": "s1", "slots": {}, **kwargs}


# ---------------------------------------------------------------------------
# order_flow
# ---------------------------------------------------------------------------
async def test_collect_order_id_extracted():
    """从用户消息提取订单 ID 到 slots。"""
    state = _state(user_message="订单1001")
    result = await collect_order_id(state)
    assert result["slots"]["order_id"] == "1001"


async def test_collect_order_id_not_found():
    """无订单 ID 时不写入 slots。"""
    state = _state(user_message="你好")
    result = await collect_order_id(state)
    assert "order_id" not in result["slots"]


async def test_query_order_info_found():
    """查询到订单时返回格式化信息。"""
    state = _state(slots={"order_id": "1001"})
    result = await query_order_info(state)
    assert "已发货" in result["response"]


async def test_query_order_info_not_found():
    """订单不存在时返回提示。"""
    state = _state(slots={"order_id": "9999"})
    result = await query_order_info(state)
    assert "未找到" in result["response"]


async def test_query_order_info_no_id():
    """无 order_id 时返回提示。"""
    state = _state(slots={})
    result = await query_order_info(state)
    assert "请提供" in result["response"]


async def test_format_order_response_passthrough():
    """format_order_response 是 passthrough。"""
    state = _state(response="test")
    result = await format_order_response(state)
    assert result is state


def test_format_order_with_data():
    """_format_order 格式化订单数据。"""
    order = {
        "order_id": "1001",
        "status": "已发货",
        "amount": 299.0,
        "items": ["商品A"],
        "created_at": "2026-08-01",
    }
    result = _format_order(order)
    assert "1001" in result
    assert "已发货" in result
    assert "299.00" in result


def test_format_order_none():
    """_format_order(None) 返回未找到提示。"""
    assert "未找到" in _format_order(None)


def test_build_order_flow():
    """build_order_flow 返回编译图。"""
    graph = build_order_flow()
    assert graph is not None


# ---------------------------------------------------------------------------
# logistics_flow
# ---------------------------------------------------------------------------
async def test_collect_tracking_id_extracted():
    """从用户消息提取物流单号到 slots。"""
    state = _state(user_message="物流单号SF1234")
    result = await collect_tracking_id(state)
    assert result["slots"]["tracking_id"] == "SF1234"


async def test_collect_tracking_id_not_found():
    """无物流单号时不写入 slots。"""
    state = _state(user_message="你好")
    result = await collect_tracking_id(state)
    assert "tracking_id" not in result["slots"]


async def test_query_logistics_info_found():
    """查询到物流时返回格式化信息。"""
    state = _state(slots={"tracking_id": "SF1234"})
    result = await query_logistics_info(state)
    assert "顺丰" in result["response"]


async def test_query_logistics_info_not_found():
    """物流不存在时返回提示。"""
    state = _state(slots={"tracking_id": "XX9999"})
    result = await query_logistics_info(state)
    assert "未找到" in result["response"]


async def test_query_logistics_info_no_id():
    """无 tracking_id 时返回提示。"""
    state = _state(slots={})
    result = await query_logistics_info(state)
    assert "请提供" in result["response"]


def test_format_logistics_with_data():
    """_format_logistics 格式化物流数据。"""
    logistics = {
        "tracking_id": "SF1234",
        "carrier": "顺丰",
        "status": "运输中",
        "location": "深圳",
        "eta": "2026-08-12",
    }
    result = _format_logistics(logistics)
    assert "SF1234" in result
    assert "顺丰" in result


def test_format_logistics_none():
    assert "未找到" in _format_logistics(None)


def test_build_logistics_flow():
    graph = build_logistics_flow()
    assert graph is not None


# ---------------------------------------------------------------------------
# postsale_flow
# ---------------------------------------------------------------------------
async def test_collect_issue_type_refund():
    """识别退款类型。"""
    state = _state(user_message="我要退款")
    result = await collect_issue_type(state)
    assert result["slots"]["issue_type"] == "退款"


async def test_collect_issue_type_exchange():
    """识别换货类型。"""
    state = _state(user_message="我要换货")
    result = await collect_issue_type(state)
    assert result["slots"]["issue_type"] == "换货"


async def test_collect_issue_type_repair():
    """识别维修类型。"""
    state = _state(user_message="需要维修")
    result = await collect_issue_type(state)
    assert result["slots"]["issue_type"] == "维修"


async def test_collect_issue_type_not_found():
    """无售后关键词时不写入 slots。"""
    state = _state(user_message="你好")
    result = await collect_issue_type(state)
    assert "issue_type" not in result["slots"]


async def test_query_postsale_policy_found():
    """查询到售后政策时返回政策内容。"""
    state = _state(slots={"issue_type": "退款"})
    result = await query_postsale_policy_info(state)
    assert "退款" in result["response"]


async def test_query_postsale_policy_unknown():
    """未知售后类型时返回提示。"""
    state = _state(slots={"issue_type": "未知"})
    result = await query_postsale_policy_info(state)
    assert "哪种售后" in result["response"]


async def test_format_postsale_response_passthrough():
    state = _state(response="test")
    result = await format_postsale_response(state)
    assert result is state


def test_build_postsale_flow():
    graph = build_postsale_flow()
    assert graph is not None


# ---------------------------------------------------------------------------
# services 层
# ---------------------------------------------------------------------------
async def test_service_query_order_found():
    result = await query_order("1001")
    assert result["found"] is True
    assert result["order"]["order_id"] == "1001"


async def test_service_query_order_not_found():
    result = await query_order("9999")
    assert result["found"] is False


async def test_service_query_order_none_id():
    result = await query_order(None)
    assert result["found"] is False
    assert "请提供" in result["message"]


async def test_service_query_logistics_found():
    result = await query_logistics("SF1234")
    assert result["found"] is True


async def test_service_query_logistics_not_found():
    result = await query_logistics("XX9999")
    assert result["found"] is False


async def test_service_query_postsale_policy_found():
    result = await query_postsale_policy("退款")
    assert result["found"] is True
    assert "退款" in result["policy"]


async def test_service_query_postsale_policy_unknown():
    result = await query_postsale_policy("未知")
    assert result["found"] is False


def test_extract_order_id_from_message():
    assert extract_order_id("订单1001") == "1001"
    assert extract_order_id("单号:1002") == "1002"
    assert extract_order_id("没有订单号") is None


def test_extract_tracking_id_from_message():
    assert extract_tracking_id("物流SF1234") == "SF1234"
    assert extract_tracking_id("快递单号YT5678") == "YT5678"
    assert extract_tracking_id("没有单号") is None


async def test_extract_issue_type_keywords():
    assert await extract_issue_type("我要退款") == "退款"
    assert await extract_issue_type("需要换货") == "换货"
    assert await extract_issue_type("维修服务") == "维修"
    assert await extract_issue_type("退货") == "退货"
    assert await extract_issue_type("你好") is None
