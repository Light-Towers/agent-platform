"""客服业务服务层：订单/物流/售后数据查询。

Phase 7 补全：从骨架接入真实业务逻辑。
使用配置驱动的模拟数据（不依赖外部 DB），生产环境可替换为真实 DB 查询。
"""

from __future__ import annotations

from typing import Any

from agent_core.logging import get_logger

logger = get_logger(__name__)


async def query_order(order_id: str | None) -> dict[str, Any]:
    """查询订单信息。

    Args:
        order_id: 订单 ID（None 时返回提示）

    Returns:
        {"found": bool, "order": {...} | None, "message": str}
    """
    if not order_id:
        return {
            "found": False,
            "order": None,
            "message": "请提供您的订单号，我可以帮您查询订单详情。",
        }

    mock_orders: dict[str, dict[str, Any]] = {
        "1001": {"order_id": "1001", "status": "已发货", "amount": 299.00, "items": ["商品A x1"], "created_at": "2026-08-01"},
        "1002": {"order_id": "1002", "status": "待付款", "amount": 598.00, "items": ["商品B x2"], "created_at": "2026-08-05"},
        "1003": {"order_id": "1003", "status": "已完成", "amount": 129.00, "items": ["商品C x1"], "created_at": "2026-07-20"},
    }

    order = mock_orders.get(order_id)
    if order:
        logger.info("订单查询命中: %s", order_id)
        return {"found": True, "order": order, "message": ""}
    logger.info("订单未找到: %s", order_id)
    return {
        "found": False,
        "order": None,
        "message": f"未找到订单号 {order_id}，请确认订单号是否正确。",
    }


async def query_logistics(tracking_id: str | None) -> dict[str, Any]:
    """查询物流信息。

    Args:
        tracking_id: 物流单号

    Returns:
        {"found": bool, "logistics": {...} | None, "message": str}
    """
    if not tracking_id:
        return {
            "found": False,
            "logistics": None,
            "message": "请提供您的物流单号，我可以帮您查询物流状态。",
        }

    mock_logistics: dict[str, dict[str, Any]] = {
        "SF1234": {"tracking_id": "SF1234", "carrier": "顺丰", "status": "运输中", "location": "深圳转运中心", "eta": "2026-08-12"},
        "YT5678": {"tracking_id": "YT5678", "carrier": "圆通", "status": "已签收", "location": "北京朝阳区", "eta": "2026-08-10"},
    }

    logistics = mock_logistics.get(tracking_id)
    if logistics:
        logger.info("物流查询命中: %s", tracking_id)
        return {"found": True, "logistics": logistics, "message": ""}
    logger.info("物流未找到: %s", tracking_id)
    return {
        "found": False,
        "logistics": None,
        "message": f"未找到物流单号 {tracking_id}，请确认单号是否正确。",
    }


async def query_postsale_policy(issue_type: str | None) -> dict[str, Any]:
    """查询售后政策。

    Args:
        issue_type: 售后类型（退款/换货/维修）

    Returns:
        {"found": bool, "policy": str, "message": str}
    """
    if not issue_type or issue_type == "未知":
        return {
            "found": False,
            "policy": "",
            "message": "请问您需要办理哪种售后？支持：退款、换货、维修。",
        }

    policies: dict[str, str] = {
        "退款": "退款政策：签收后 7 天内可申请全额退款，7-15 天可申请部分退款。退款将在 3-5 个工作日内原路退回。",
        "换货": "换货政策：签收后 15 天内可申请换货，商品需保持原包装完好。换货运费由责任方承担。",
        "维修": "维修政策：自购买之日起 1 年内提供免费维修服务。超过保修期可提供有偿维修。",
        "退货": "退货政策：签收后 7 天内可申请无理由退货，商品需保持原状。退货运费由买家承担（质量问题除外）。",
    }

    policy = policies.get(issue_type)
    if policy:
        logger.info("售后政策命中: %s", issue_type)
        return {"found": True, "policy": policy, "message": ""}
    logger.info("售后类型未匹配: %s", issue_type)
    return {
        "found": False,
        "policy": "",
        "message": f"暂不支持 {issue_type} 类型的售后，当前支持：退款、换货、维修、退货。",
    }


def extract_order_id(message: str) -> str | None:
    """从用户消息中提取订单 ID。"""
    import re

    match = re.search(r"(?:订单|单号)[：:]*\s*(\d{4,})", message)
    if match:
        return match.group(1)
    match = re.search(r"\b(\d{4})\b", message)
    if match:
        return match.group(1)
    return None


def extract_tracking_id(message: str) -> str | None:
    """从用户消息中提取物流单号。"""
    import re

    match = re.search(r"(?:物流|快递|单号)[：:]*\s*([A-Za-z]{2}\d{4,})", message)
    if match:
        return match.group(1)
    match = re.search(r"\b([A-Za-z]{2}\d{4})\b", message)
    if match:
        return match.group(1)
    return None


def extract_issue_type(message: str) -> str | None:
    """从用户消息中识别售后类型。"""
    if any(kw in message for kw in ["退款", "退钱"]):
        return "退款"
    if any(kw in message for kw in ["换货", "更换"]):
        return "换货"
    if any(kw in message for kw in ["维修", "修理"]):
        return "维修"
    if any(kw in message for kw in ["退货", "退回"]):
        return "退货"
    return None
