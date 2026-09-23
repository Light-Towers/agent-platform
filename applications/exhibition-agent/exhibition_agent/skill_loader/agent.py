"""会展查询 Agent — LLM tool calling 循环。

将 48 个 warehouse REST 端点转为 OpenAI function calling tools，
LLM 根据用户意图自动选择端点、填充参数、调用 warehouse、解读结果。

流程：
1. 用户输入自然语言问题
2. LLM 收到 system prompt + 48 个 tools，返回 tool_calls 或直接回复
3. 后端执行 tool_calls（httpx 调 warehouse），结果喂回 LLM
4. 循环直到 LLM 不再调用 tool，返回最终自然语言回复
"""

from __future__ import annotations

import json
import os
import re

import httpx

from .llm_client import LLMClient
from .parser import Endpoint

TOOL_RESULT_MAX_CHARS = int(os.environ.get("TOOL_RESULT_MAX_CHARS", "8000"))
MAX_TOOL_ROUNDS = int(os.environ.get("MAX_TOOL_ROUNDS", "6"))

SYSTEM_PROMPT = """你是会展数据查询助手，通过调用会展数据仓库的 REST 端点回答用户问题。

可用端点分为四个域：
1. 查询域（PARTIAL）：展会/展商/观众/场馆/主办列表与画像、概览、业务记录（合同/安全/会议/线索）
2. 推荐域（SYNTHETIC）：基于场馆/展商的推荐（合成数据，仅供链路演示）
3. 洞察域：场馆运营、策略洞察、预测（部分合成）
4. 写操作：创建/删除线索（仅测试用）

调用规则：
- 根据用户意图选择最合适的端点，可连续调用多个端点组合信息
- 路径参数（如 exhibition_id、venue_id）需从用户输入获取；如缺失则先询问用户
- readiness=SYNTHETIC 的端点返回合成数据，须告知用户"此为合成数据，非真实经营结论"
- readiness=PARTIAL 的端点返回部分真实数据，指标可能稀疏，须如实呈现
- 不要编造数据，端点返回什么就呈现什么
- 查询结果用中文自然语言总结，不要直接输出原始 JSON
- 如果结果中包含 data_readiness 字段，需如实告知用户数据可信度
"""


def endpoint_to_function_name(method: str, path: str) -> str:
    """把端点转为合法的 OpenAI function name（[a-zA-Z0-9_-]，最长 64）。"""
    p = path.replace("/api/", "")
    p = re.sub(r"\{(\w+)\}", r"by_\1", p)
    p = p.replace("/", "_").replace("-", "_")
    name = f"{method.lower()}_{p}"
    return name[:64]


def endpoint_to_tool(ep: Endpoint) -> dict:
    """把端点转为 OpenAI function calling tool 格式。"""
    name = endpoint_to_function_name(ep.method, ep.path)

    properties: dict[str, dict] = {}
    required: list[str] = []
    for p in ep.params:
        prop: dict = {"type": "string", "description": ""}
        if p.in_path:
            prop["description"] = f"路径参数 {p.name}"
        else:
            prop["description"] = f"查询参数 {p.name}"
        if p.default:
            prop["default"] = p.default
        properties[p.name] = prop
        if p.required:
            required.append(p.name)

    desc = ep.desc or f"{ep.method} {ep.path}"
    if ep.readiness:
        desc += f" (readiness={ep.readiness})"

    return {
        "type": "function",
        "function": {
            "name": name,
            "description": desc,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


def _summarize_body(body, max_chars: int = 300) -> str:
    """生成 tool 结果摘要（用于前端展示）。"""
    if isinstance(body, dict):
        keys = list(body.keys())
        preview = json.dumps(body, ensure_ascii=False)[:max_chars]
        return f"keys={keys[:8]} | preview={preview}"
    if isinstance(body, list):
        return f"list len={len(body)} | preview={json.dumps(body[:2], ensure_ascii=False)[:max_chars]}"
    return str(body)[:max_chars]


def _truncate_for_llm(text: str) -> str:
    if len(text) <= TOOL_RESULT_MAX_CHARS:
        return text
    return text[:TOOL_RESULT_MAX_CHARS] + f"\n...[结果已截断，完整结果 {len(text)} 字符]"


class ExhibitionAgent:
    def __init__(
        self,
        warehouse_base_url: str,
        llm_client: LLMClient,
        endpoints: list[Endpoint],
    ):
        self.warehouse_base_url = warehouse_base_url
        self.llm = llm_client
        self.endpoints = endpoints
        self.tools = [endpoint_to_tool(ep) for ep in endpoints]
        self.func_name_to_endpoint: dict[str, Endpoint] = {
            endpoint_to_function_name(ep.method, ep.path): ep for ep in endpoints
        }

    async def chat(self, messages: list[dict]) -> dict:
        """处理一轮对话。

        Args:
            messages: 前端传来的对话历史（不含 system prompt）

        Returns:
            {
                "reply": "LLM 最终自然语言回复",
                "tool_calls": [{name, args, result_summary, status_code}, ...],
                "messages": 更新后的完整对话历史（含 assistant + tool 消息）
            }
        """
        full_messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
        for m in messages:
            full_messages.append(dict(m))

        tool_calls_log: list[dict] = []

        for round_idx in range(MAX_TOOL_ROUNDS):
            resp_msg = await self.llm.chat_completion(full_messages, self.tools)

            clean_msg = {"role": "assistant"}
            if resp_msg.get("content"):
                clean_msg["content"] = resp_msg["content"]
            if resp_msg.get("tool_calls"):
                clean_msg["tool_calls"] = resp_msg["tool_calls"]
            full_messages.append(clean_msg)

            tool_calls = resp_msg.get("tool_calls")
            if not tool_calls:
                return {
                    "reply": resp_msg.get("content", ""),
                    "tool_calls": tool_calls_log,
                    "messages": full_messages[1:],
                }

            for tc in tool_calls:
                func_name = tc["function"]["name"]
                args_str = tc["function"]["arguments"]
                try:
                    args = json.loads(args_str) if args_str else {}
                except json.JSONDecodeError:
                    args = {}

                tool_result = await self._execute_tool(func_name, args)
                tool_calls_log.append(
                    {
                        "name": func_name,
                        "method": tool_result.get("method", ""),
                        "path": tool_result.get("path", ""),
                        "url": tool_result.get("url", ""),
                        "args": args,
                        "status_code": tool_result["status_code"],
                        "result_summary": _summarize_body(tool_result["body"]),
                    }
                )

                result_str = json.dumps(tool_result["body"], ensure_ascii=False)
                result_str = _truncate_for_llm(result_str)

                full_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": result_str,
                    }
                )

        return {
            "reply": "已达到最大工具调用轮数限制，以上是当前查询结果。如需继续请细化问题。",
            "tool_calls": tool_calls_log,
            "messages": full_messages[1:],
        }

    async def _execute_tool(self, func_name: str, args: dict) -> dict:
        ep = self.func_name_to_endpoint.get(func_name)
        if not ep:
            return {
                "status_code": 404,
                "body": {"error": f"未知端点函数: {func_name}"},
                "method": "",
                "path": "",
                "url": "",
            }

        path = ep.path
        query_params: dict[str, str] = {}
        body_params: dict[str, str] = {}

        for k, v in args.items():
            v = str(v)
            if f"{{{k}}}" in path:
                path = path.replace(f"{{{k}}}", v)
            elif ep.method in ("GET", "DELETE"):
                query_params[k] = v
            else:
                body_params[k] = v

        url = f"{self.warehouse_base_url}{path}"

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                if ep.method == "GET":
                    resp = await client.get(url, params=query_params)
                elif ep.method == "DELETE":
                    resp = await client.delete(url, params=query_params)
                elif ep.method == "POST":
                    resp = await client.post(url, json=body_params, params=query_params)
                else:
                    return {
                        "status_code": 400,
                        "body": {"error": f"不支持的方法: {ep.method}"},
                        "method": ep.method,
                        "path": path,
                        "url": url,
                    }
            except httpx.RequestError as e:
                return {
                    "status_code": 502,
                    "body": {"error": f"warehouse 请求失败: {e}"},
                    "method": ep.method,
                    "path": path,
                    "url": url,
                }

        try:
            body = resp.json()
        except Exception:  # noqa: BLE001
            body = resp.text

        return {
            "status_code": resp.status_code,
            "body": body,
            "method": ep.method,
            "path": path,
            "url": url,
        }
