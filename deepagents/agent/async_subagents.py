"""远程子 Agent 定义（AsyncSubAgent + Agent Protocol）。

D14：远程子服务以 subagent 形态包装（非裸 tool），
复用 task 委派 + monitor 链路。

子服务需实现 Agent Protocol（LangGraph Platform 原生支持，
FastAPI 服务用 langgraph-protocol 包适配）。
M2 阶段子服务尚未升级为 Agent Protocol server，
AGENT_MODE=local 时仍用本地 subagent。

远程调用实现说明（Phase 7 收尾已修复）：
  优先使用外部 `deepagents` 包的 `AsyncSubAgent`（graph_id+url，Agent Protocol）。
  若该包未安装（当前 .venv 未包含），自动回退到基于 httpx 的
  `_HttpSubAgent`：POST 到子服务各自的 endpoint（见 SubserviceConfig.endpoint），
  例如 kefu 直连走 /invoke（返回 QueryResponse），wenda-data-agent 走 /api/query
  （返回 SqlQueryResponse）。两路径对外暴露同一 `ainvoke(input)` 接口。
"""

from __future__ import annotations

import asyncio

from agent_core.monitor import monitor

from agent.circuit_breaker import get_breaker_sync
from agent.config import get_all_subservices
from agent.metrics import record_delegation
from agent.prompts import sub_agents_content
from agent.tracing.langfuse_adapter import langfuse_observe as observe

try:  # 外部 deepagents 包（Agent Protocol 原生支持）
    from deepagents import AsyncSubAgent

    _HAS_DEEPAGENTS = True
except Exception:  # pragma: no cover - 回退路径
    AsyncSubAgent = None  # type: ignore[assignment]
    _HAS_DEEPAGENTS = False


import os

import httpx
from agent_core.logging import get_logger

logger = get_logger(__name__)

# E-1 契约断言灰度开关（优化 E / P4.1 / S-1）：默认开启。
# 关闭时回退到原 str(data)/dict 规整，便于现网快速回滚（无需发版）。
_E1_CONTRACT_ASSERT = os.getenv("E1_CONTRACT_ASSERT", "on").lower() in ("1", "true", "yes", "on")
# E-1b 内容断言（TB-6 补充）：在形状断言之外，验证响应语义非空（answer 非空）。
# 与形状断言分离，可独立回滚。默认开启。
_E1_CONTENT_ASSERT = os.getenv("E1_CONTENT_ASSERT", "on").lower() in ("1", "true", "yes", "on")

try:  # shared-schemas 已在 dependencies 声明（优化 E / B-1）
    from shared_schemas import QueryResponse as _QueryResponse

    _HAS_SHARED_SCHEMAS = True
except Exception:  # pragma: no cover - 兜底：依赖缺失时跳过断言
    _QueryResponse = None
    _HAS_SHARED_SCHEMAS = False


def _normalize_response(data, name: str) -> dict:
    """将远程子服务响应规整为 {"answer": ...} 供 main_agent 消费。

    同时执行两级联邦契约断言（优化 E / P4.1 / TB-6）：
    1. 形状断言（_E1_CONTRACT_ASSERT，默认 on）：响应能被 shared_schemas.QueryResponse
       构造，确保字段形状符合联邦契约（kefu 的 QueryResponse / wenda 的 SqlQueryResponse 超集均吸收）。
    2. 内容断言（_E1_CONTENT_ASSERT，默认 on）：answer 非空，避免"契约通过但内容空洞"
       （kefu 图未产出 response 时返回空 answer，形状合法但语义退化）。
    """
    # 旧 adapter /api/messages 返回 list。
    if isinstance(data, list):
        text = " ".join(msg.get("text", "") for msg in data if isinstance(msg, dict))
        return {"answer": text}
    if isinstance(data, dict):
        # E-1 联邦契约对齐：形状校验（SqlQueryResponse 字段超集被安全吸收）。
        if _E1_CONTRACT_ASSERT and _HAS_SHARED_SCHEMAS:
            try:
                _QueryResponse(**data)
            except Exception as exc:
                raise ValueError(
                    f"[{name}] 远程响应不符合 shared_schemas.QueryResponse 契约: {exc} | keys={list(data.keys())}"
                ) from exc
        # E-1b 内容校验（TB-6）：answer 非空。
        if _E1_CONTENT_ASSERT:
            answer = data.get("answer", "")
            if not answer or not str(answer).strip():
                logger.warning("[%s] 远程响应 answer 为空（契约形状通过但内容空洞），疑似子服务退化", name)
        return {"answer": data.get("answer", ""), **data}
    return {"answer": str(data)}


class _HttpSubAgent:
    """deepagents 未安装时的 httpx 远程回退（兼容 AsyncSubAgent.ainvoke 接口）。"""

    def __init__(self, svc, description: str) -> None:
        self.name = svc.name
        self.graph_id = svc.graph_id
        self.url = svc.url
        self.endpoint = svc.endpoint
        self.description = description

    async def ainvoke(self, input: dict) -> dict:
        endpoint = self.endpoint
        payload = {
            "query": input.get("query", input.get("message", "")),
            "session_id": input.get("session_id"),
            "tenant_id": input.get("tenant_id"),
            "trace_id": input.get("trace_id"),
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(self.url.rstrip("/") + endpoint, json=payload)
            resp.raise_for_status()
            data = resp.json()
        # kefu /invoke 返回 QueryResponse(dict)；wenda-data-agent /api/query 返回 SqlQueryResponse(dict，QueryResponse 子类)；
        # 旧 adapter /api/messages 返回 list。统一规整为 {"answer": ...} 供 main_agent 消费。
        return _normalize_response(data, self.name)


def _build_async_subagent(key: str, description: str):
    """构建单个远程子 Agent（优先 AsyncSubAgent，否则 httpx 回退）。

    P3：返回的 agent 被 `DelegatingSubAgent` 包装，委派时施加
    健康探活短路 + 熔断器 + 指数退避重试 + 本地 fallback（local_agent）。
    """
    svc = get_all_subservices()[key]
    if _HAS_DEEPAGENTS and AsyncSubAgent is not None:
        inner = AsyncSubAgent(
            graph_id=svc.graph_id,
            url=svc.url,
            name=svc.name,
            description=description,
        )
    else:
        inner = _HttpSubAgent(svc, description)
    return DelegatingSubAgent(key, inner, svc, description)


class DelegatingSubAgent:
    """P3：委派包装层。

    在 deepagents 框架的 subagent 委派（`ainvoke`）外层增加：
      1. 健康探活短路：config.healthy=False 时直接跳过远程，走本地 fallback。
      2. 熔断器：OPEN 态跳过远程，走本地 fallback；监控失败率自动熔断。
      3. 指数退避重试：网络抖动偶发失败时重试（默认 2 次）。
      4. 本地 fallback：配置了 local_agent 时降级到本地 subagent；
         否则返回结构化降级响应（带 degraded 标记）。
    """

    # 偶发失败的重试次数（不含首次）。
    RETRIES = int(os.getenv("SUBAGENT_RETRIES", "2"))
    # 重试基础退避（秒），指数增长：base * 2**attempt。
    RETRY_BASE = float(os.getenv("SUBAGENT_RETRY_BASE", "0.5"))

    def __init__(self, key: str, inner, svc, description: str = "") -> None:
        self.key = key
        self.name = svc.name
        self.graph_id = svc.graph_id
        self.url = svc.url
        self.endpoint = svc.endpoint
        self.description = description or getattr(inner, "description", "")
        self._inner = inner
        self._svc = svc
        self._breaker = get_breaker_sync(self.name)
        self._local_agent = None  # 懒编译

    @observe(name="subagent.delegate", as_type="span")
    async def ainvoke(self, input: dict) -> dict:
        monitor.report_assistant(self.name, {"event": "delegate_start"})
        # 1. 健康探活短路（config.healthy 由 health_check 维护）
        if not self._svc.healthy:
            logger.warning("[%s] 健康探活标记不可用，跳过远程委派，走本地 fallback", self.name)
            monitor.report_assistant(self.name, {"event": "delegate_degraded", "reason": "unhealthy"})
            return await self._fallback(input, reason="unhealthy")

        # 2. 熔断器放行检查
        if not await self._breaker.allow():
            logger.warning("[%s] 熔断器 OPEN，跳过远程委派，走本地 fallback", self.name)
            monitor.report_assistant(self.name, {"event": "delegate_degraded", "reason": "circuit_open"})
            return await self._fallback(input, reason="circuit_open")

        # 3. 指数退避重试的远程委派
        last_exc: Exception | None = None
        for attempt in range(self.RETRIES + 1):
            try:
                result = await self._inner.ainvoke(input)
                await self._breaker.record_success()
                record_delegation(success=True)
                return result
            except Exception as exc:  # 网络/协议/子服务异常
                last_exc = exc
                logger.warning(
                    "[%s] 远程委派失败（attempt %d/%d）: %s",
                    self.name, attempt + 1, self.RETRIES + 1, exc,
                )
                if attempt < self.RETRIES:
                    await asyncio.sleep(self.RETRY_BASE * (2 ** attempt))
                    continue
        # 4. 用尽重试仍失败 -> 计入熔断 + 本地 fallback
        await self._breaker.record_failure()
        logger.error("[%s] 远程委派彻底失败，转入本地 fallback: %s", self.name, last_exc)
        monitor.report_assistant(self.name, {"event": "delegate_degraded", "reason": "remote_failed"})
        return await self._fallback(input, reason="remote_failed", error=last_exc)

    async def _fallback(self, input: dict, reason: str, error: Exception | None = None) -> dict:
        """本地降级路径。

        配置了 local_agent（dict）时尝试编译并调用本地 subagent；
        否则返回结构化降级响应，避免把失败抛给主管线程。
        """
        local_spec = self._svc.local_agent
        if local_spec:
            try:
                agent = self._get_local_agent(local_spec)
                result = await agent.ainvoke(input)
                result.setdefault("degraded", True)
                result.setdefault("degraded_reason", reason)
                record_delegation(success=True, degraded=True)
                return result
            except Exception as exc:
                logger.error("[%s] 本地 fallback 也失败: %s", self.name, exc)
                # 落入结构化降级响应
        # 熔断 + 本地兜底均不可用，才是「彻底失败」——驱动 delegation_failure_total（#4 修复）。
        record_delegation(success=False, degraded=True)
        return {
            "answer": f"子服务「{self.name}」当前不可用（{reason}），已降级处理，请稍后重试或由主管直接回答。",
            "degraded": True,
            "degraded_reason": reason,
            "error": str(error) if error else None,
        }

    def _get_local_agent(self, spec: dict):
        """懒编译本地 fallback subagent（仅一次）。"""
        if self._local_agent is None:
            from deepagents import create_deep_agent

            from agent.llm import model

            self._local_agent = create_deep_agent(
                model=model,
                name=spec.get("name", self.name),
                description=spec.get("description", self.description),
                system_prompt=spec.get("system_prompt", ""),
                tools=spec.get("tools", []),
            )
        return self._local_agent


def get_remote_subagents():
    """构建 3 个远程子 Agent。

    text_to_sql → wenda-data-agent(:8001)/api/query（Text-to-SQL，adapter 已退役）
    rag_query   → zhiku（RAG 知识库）
    customer_service → kefu-service(:8003)/invoke（直连）或 kefu-adapter(:8002)
    """
    return [
        _build_async_subagent(
            "text_to_sql",
            sub_agents_content["db"]["description"],
        ),
        _build_async_subagent(
            "rag_query",
            sub_agents_content["knowledge_base"]["description"],
        ),
        _build_async_subagent(
            "customer_service",
            "智能客服助手，处理订单查询、物流跟踪、售后退换等客服场景",
        ),
    ]
