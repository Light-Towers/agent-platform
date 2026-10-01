# -*- coding: utf-8 -*-
"""服务端租户解析（ADR-0006 D1 / T11，W4）。

多租户下 ``tenant_id`` 是唯一安全边界。历史实现允许 ``tenant_id`` 为空并据此
跳过租户过滤（"不传即全库"）——归属不明的请求可跨租户读写，即泄漏通道。

本模块把"空 tenant"从**静默全量**收敛为**服务端注入本部署级默认租户 + 审计**：

- 入站携带非空 tenant：作为归属维沿用（真正的"客户端不可指定"需 JWT/签名令牌，
  框架规则中列为待评估项，本 ADR 不重复决策）；
- 入站 tenant 为空：回退 ``settings.knowledge_default_tenant_id`` 并记 WARNING，
  调用点从此**总能拿到一个具体租户**，下游 Milvus / Mongo 过滤恒非空 →
  不再有"空 → 不加过滤"的旁路。
"""

from __future__ import annotations

from knowledge_service.core.config import settings
from knowledge_service.core.logger import logger
from knowledge_service.utils.tenant_identity import current_asserted_tenant


def resolve_server_tenant(provided: str | None, *, endpoint: str = "") -> str:
    """解析请求的服务端租户（ADR-0007）：优先级 **签名断言 > provided > default**。

    - 有已验签内部头断言（网关经 X-Internal-Tenant 传入）→ 采信断言（不可自报的安全边界）；
      body 与断言不符仅记审计不拒（A5 双读过渡）。
    - 无断言 → 沿用入站 provided（**过渡期**，A6 弃用后移除）。
    - 都为空 → 回退 ``knowledge_default_tenant_id`` + 审计（永不返回空）。

    :param provided: 入站 ``tenant_id``（表单 / body / query，可能为空串或 None）。
    :param endpoint: 端点名（仅用于审计日志定位）。
    :return: 非空租户字符串。
    """
    asserted = current_asserted_tenant()
    if asserted:
        p = (provided or "").strip()
        if p and p != asserted:
            logger.warning(
                "[isolation] body tenant_id=%r 与签名断言=%r 不符，采信断言（endpoint=%s）",
                p, asserted, endpoint or "-",
            )
        return asserted
    tenant = (provided or "").strip()
    if tenant:
        return tenant
    fallback = (settings.knowledge_default_tenant_id or "default").strip() or "default"
    logger.warning(
        "[isolation] 请求未携带 tenant_id（endpoint=%s），服务端注入默认租户 %r "
        "（ADR-0006 T11：不传即全量为跨租户泄漏形态，已收窄）",
        endpoint or "-", fallback,
    )
    return fallback


__all__ = ["resolve_server_tenant"]
