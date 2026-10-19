"""QueryService：查询服务（组装 12 节点管线执行）。

2026-10-18 审计（方案 §5.11-V2 / §5.16-7）：配置面集中在这里注入 state。
此前 `sql_max_rows`/`sql_max_correct_retries`/`retrieval_top_k`/`rrf_k`/`tokenizer`
都只有定义没有消费者，节点 `state.get(..., 默认)` 恒回落硬编码值——改配置不生效。
"""

import time
from datetime import datetime, timezone
from typing import Any

from agent_core.logging import get_logger
from agent_runtime.workspace_registry import server_tenant_id

from nl2sql_service.services.load_guard import LoadRejected
from nl2sql_service.services.metric_config_guard import MetricConfigRejected, check_metric_config

logger = get_logger(__name__)

_WEEKDAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


def build_date_info(settings: Any) -> str:
    """生成期日期上下文（P0-11①）：系统日期 + 可选数据口径说明。

    "上个月/今年/最近 7 天"的锚点是**当前日期**，而数据本身可能是 T+1 快照，
    两者不是一回事——`date_context_note` 让部署方声明后者，不写死在代码里。
    """
    now = datetime.now(timezone.utc).astimezone()
    stamp = f"{now:%Y-%m-%d %H:%M} {_WEEKDAYS[now.weekday()]}（{now:%z}）"
    note = getattr(settings, "date_context_note", "") or ""
    return f"当前时间：{stamp}" + (f"；口径说明：{note}" if note else "")


class QueryService:
    """查询服务：封装 Text-to-SQL 管线调用。"""

    def __init__(self, graph=None, context=None, llm=None) -> None:
        self._graph = graph
        self._context = context
        self._llm = llm

    def set_graph(self, graph) -> None:
        self._graph = graph

    async def query(self, question: str, **kwargs: Any) -> dict[str, Any]:
        if self._graph is None:
            return {"answer": "", "error": "graph not initialized", "fallback": True}

        from nl2sql_service.conf.settings import get_settings

        settings = get_settings()
        metric_config = kwargs.get("metric_config")
        datasource_id = kwargs.get("datasource_id")
        # 多轮（§5.13 M1）：session_id 从请求读入并注入 state；
        # 不传 session_id 时 inherit_context 走单轮零变更分支（逐字节一致）。
        session_id = (kwargs.get("session_id") or "").strip()
        # 隔离作用域（P1-1 / A 前置）：tenant 按 ADR-0007 服务端断言 > 请求体 >
        # default_tenant 解析（不再裸信客户端 body）；workspace 同套优先级。
        from nl2sql_service.services.tenant_scope import resolve_scope

        scope = resolve_scope(
            request_tenant=kwargs.get("tenant_id"),
            request_workspace=kwargs.get("workspace_id"),
            default_tenant=settings.default_tenant,
            default_workspace=settings.default_workspace,
        )
        tenant_id = scope.tenant_id
        workspace_id = scope.workspace_id
        # 数据源解析（P1-3/P1-4/P1-6）：请求显式选源；未知 id fail-fast，
        # 不静默回落默认源（串源比报错更糟）。无注册表（老部署/测试）回落默认串。
        registry = getattr(self._context, "datasources", None)
        dialect = "postgres"
        source_label = settings.datasource_label
        resolved_ds = settings.datasource_id
        if registry is not None:
            try:
                source = registry.resolve(datasource_id)
            except KeyError:
                return {
                    "answer": "",
                    "error": f"未知数据源: {datasource_id}",
                    "fallback": True,
                }
            dialect = source.dialect
            source_label = source.label
            resolved_ds = source.id
        state: dict[str, Any] = {
            "query": question,
            "context": self._context,
            "llm": self._llm,
            "session_id": session_id,
            "tenant_id": tenant_id,
            "workspace_id": workspace_id,
            "_start_perf": time.perf_counter(),
            "datasource_id": resolved_ds,
            "datasource_label": source_label,
            "dialect": dialect,
            "sql_max_rows": settings.sql_max_rows,
            "sql_max_correct_retries": settings.sql_max_correct_retries,
            "retrieval_top_k": settings.retrieval_top_k,
            "rrf_k": settings.rrf_k,
            "tokenizer": settings.tokenizer,
            "retrieval_score_margin": settings.retrieval_score_margin,
            "date_info": build_date_info(settings),
            # 进模型的结果体量上限（§5.11-V3 双上限分离）
            "sql_max_rows_for_prompt": settings.sql_max_rows_for_prompt,
            "sql_prompt_max_bytes": settings.sql_prompt_max_bytes,
            # 漂移检测表统计（P0-3 → 聚合引导）；无则空，不猜表大小
            "table_stats": getattr(self._context, "table_stats", None) or [],
            # 数据权限清单（§5.9 L2 guard）：服务端单源注入，客户端不可覆盖
            "allowed_tables": list(settings.allowed_tables or []),
            "sensitive_columns": list(settings.sensitive_columns or []),
            # L3 结果层脱敏的角色与开关（§5.9）：角色来自服务端断言
            "user_role": settings.default_query_role,
            "result_masking_enabled": settings.result_masking_enabled,
            "mask_keep_chars": settings.mask_keep_chars,
            "admin_roles": list(settings.admin_roles or []),
        }
        if metric_config is not None:
            recall = (
                metric_config.to_recall_result()
                if hasattr(metric_config, "to_recall_result")
                else metric_config
            )
            # S-2：入参守卫（表白名单 + 体量上限）在进 state/召回前拦——
            # 未授权表 fail-fast，不静默丢弃（丢了会让"注入了"与"被丢了"无法区分）。
            try:
                check_metric_config(recall, settings.allowed_tables, settings.metric_config_max_items)
            except MetricConfigRejected as exc:
                logger.info("metric_config rejected: %s", exc.message)
                return {"answer": "", "error": exc.message, "fallback": True}
            state["metric_config"] = recall
        # 负载隔离（P1-5/S-6）：并发闸 + 限流包住整条图执行。限流/并发维度取
        # **服务端断言**租户（#103）：请求体 tenant_id 是客户端可控值，拿它当键
        # 等于"换个串就换个桶"，限流可被单向绕过——observe 档下 scope.tenant_id
        # 本身就采信 body，故键不能从 scope 取；无断言且无部署 default 的单租户
        # dev 落 "anon" 共享桶（与修复前 dev 行为逐位一致）。
        load_guard = getattr(self._context, "load_guard", None)
        rate_key = server_tenant_id(settings.default_tenant) or "anon"
        try:
            if load_guard is None:
                result = await self._graph.ainvoke(state)
            else:
                async with load_guard.slot(rate_key):
                    result = await self._graph.ainvoke(state)
            return self._build_response(result)
        except LoadRejected as exc:
            # 负载拒绝：对外可读、可重试，不算系统故障（不走 500）。
            logger.info("query rejected by load guard: %s", exc.message)
            return {"answer": "", "error": exc.message, "fallback": True}
        except Exception:
            logger.exception("query service failed")
            return {"answer": "", "error": "internal error", "fallback": True}

    @staticmethod
    def _build_response(result: dict[str, Any]) -> dict[str, Any]:
        """图结果 → 响应体。

        降级拒答（P0-8③ 的配套、L4 兜底）：什么都没召回到、也没生成 SQL 时，
        明确拒答而不是回空 answer——空回答对用户等于"系统坏了"，拒答至少可行动。
        """
        response = {
            "answer": result.get("answer", ""),
            "sql": result.get("sql", ""),
            "result": result.get("result"),
            "error": result.get("error"),
            "fallback": False,
            # P0-8④⑤：取值匹配语义与分诊结论上响应体（error_detail 刻意不上）
            "matched_values": result.get("value_matched", []),
            "unmatched_terms": result.get("value_unmatched", []),
            "dict_hit": result.get("dict_hit", False),
            "empty_result_reason": result.get("empty_result_reason"),
            "path": result.get("path", "graph"),
            # P1-3②：口径标签经 state 透传（graph 保留 datasource_label）
            "datasource_label": result.get("datasource_label"),
        }
        if not response["sql"] and not response["error"]:
            response["answer"] = response["answer"] or (
                "未召回到与问题相关的元知识（表/列/指标/取值均为空），已拒绝猜测。"
                "请通过 metric_config 补充相关定义，或换一种问法。"
            )
            response["fallback"] = True
        return response
