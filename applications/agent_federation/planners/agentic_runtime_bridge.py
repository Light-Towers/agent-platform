"""deepagents 接入 AgenticRuntimeBridge（Phase D 联邦侧集成，opt-in）。

默认关闭（``AGENTIC_RUNTIME_BRIDGE != "true"``）：联邦 deep_agent 行为与现状完全一致，
本模块不被任何默认代码路径引用。

开启后（仅实验/灰度）：
- 联邦侧能力（文件工具 + 3 个子智能体）注册为统一 ``SkillRegistry``；
- ``get_main_agent`` 的工具列表追加「经统一 Runtime 治理」的桥接 LangChain 工具；
  agent 调用这些工具时，经 ``RuntimeToolCaller`` → ``runtime.delegate``，受统一
  预算 / 权限 / 超时 / 熔断 / 追踪 / 轨迹治理（架构不变量 #4：Agentic 不绕过统一 Skill Runtime）。

所有集成点均 try/except 降级：任一环节失败都回退到当前行为，不影响主链路。
机械正确性由 ``test_agentic_runtime_bridge_langchain.py`` 验证（fake runtime，不拉起 deepagents）。
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_BRIDGE_FLAG = "AGENTIC_RUNTIME_BRIDGE"


def bridge_enabled() -> bool:
    """是否启用 deepagents → 统一 Runtime 桥接（默认关闭）。"""
    return os.getenv(_BRIDGE_FLAG, "false").lower() == "true"


def federation_capability_registry() -> "Any":
    """best-effort 构建联邦能力注册表（文件工具 + 3 个子智能体）。

    任一能力注册失败仅跳过该能力（不中断），保证降级安全。返回 ``SkillRegistry``。
    """
    from agent_runtime.skills.registry import Skill, SkillKind, SkillRegistry

    reg = SkillRegistry()

    # 文件工具（FUNCTION）
    for name, fn, desc in _file_tool_specs():
        try:
            reg.register(Skill(name, desc, SkillKind.FUNCTION, fn))
        except Exception as exc:  # noqa: BLE001
            logger.warning("bridge: 文件工具 %s 注册失败（跳过）: %s", name, exc)

    # 3 个子智能体（AGENT/FUNCTION 包裹，经统一 Runtime 执行）
    for ag in _subagent_specs():
        try:
            name = ag.get("name")
            if not name:
                continue

            async def _invoke(ag=ag, **kwargs: Any) -> Any:
                sub = ag["instance"]
                return await sub.ainvoke(kwargs)

            reg.register(
                Skill(name, ag.get("description", ""), SkillKind.FUNCTION, _invoke)
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("bridge: 子智能体 %s 注册失败（跳过）: %s", ag.get("name"), exc)

    return reg


def build_bridged_langchain_tools(
    runtime: "Any", query: str = "", top_k: int = 10
) -> "list[Any]":
    """把统一 Runtime 的能力发现结果转为 deepagents 可用的 LangChain 工具列表。

    每个工具经 ``RuntimeToolCaller`` 路由到 ``runtime.delegate``（统一治理）。
    架构验收 #4：agent 工具调用不绕过 Skill Runtime。
    """
    from agent_runtime.planner.agentic_bridge import (
        RuntimeToolCaller,
        discover_agent_tools,
    )
    from langchain_core.tools import StructuredTool
    from pydantic import BaseModel, ConfigDict, create_model

    schemas = discover_agent_tools(runtime.registry, query, top_k=top_k)
    caller = RuntimeToolCaller(runtime)
    tools: list[Any] = []

    for sch in schemas:
        fn = sch.get("function", sch)
        cname = fn["name"]
        cdesc = fn.get("description", "")
        params = fn.get("parameters", {}) or {}
        props = params.get("properties", {}) or {}

        fields = {pname: (Any, None) for pname in props}
        args_model = create_model(
            f"{cname}_Args",
            __base__=BaseModel,
            __config__=ConfigDict(extra="allow"),
            **fields,
        )

        async def _invoke(cname=cname, **kwargs: Any) -> Any:
            return await caller.call(cname, kwargs)

        tools.append(
            StructuredTool.from_function(
                coroutine=_invoke,
                name=cname,
                description=cdesc,
                args_schema=args_model,
            )
        )
    return tools


def _file_tool_specs() -> "list[tuple[str, Any, str]]":
    """联邦文件工具（generate_markdown / convert_md_to_pdf / read_file_content）。"""
    try:
        from tools.markdown_tools import generate_markdown
        from tools.pdf_tools import convert_md_to_pdf
        from tools.upload_file_read_tool import read_file_content

        return [
            ("generate_markdown", generate_markdown, "生成 Markdown 文档"),
            ("convert_md_to_pdf", convert_md_to_pdf, "Markdown 转 PDF"),
            ("read_file_content", read_file_content, "读取上传文件内容"),
        ]
    except Exception as exc:  # noqa: BLE001
        logger.warning("bridge: 文件工具导入失败: %s", exc)
        return []


def _subagent_specs() -> "list[dict[str, Any]]":
    """联邦 3 个子智能体实例（database / network / knowledge）。"""
    specs: list[dict[str, Any]] = []
    try:
        from agent.async_subagents import get_remote_subagents
        from agent.config import is_remote_mode
        from agent.subagents.database_query_agent import database_query_agent
        from agent.subagents.knowledge_base_agent import knowledge_base_agent
        from agent.subagents.network_search_agent import network_search_agent

        if is_remote_mode():
            for sub in get_remote_subagents():
                specs.append(
                    {
                        "name": getattr(sub, "name", None) or sub.__class__.__name__,
                        "description": getattr(sub, "description", ""),
                        "instance": sub,
                    }
                )
        else:
            for sub in (
                database_query_agent,
                network_search_agent,
                knowledge_base_agent,
            ):
                specs.append(
                    {
                        "name": getattr(sub, "name", None) or sub.__class__.__name__,
                        "description": getattr(sub, "description", ""),
                        "instance": sub,
                    }
                )
    except Exception as exc:  # noqa: BLE001
        logger.warning("bridge: 子智能体导入失败: %s", exc)
    return specs
