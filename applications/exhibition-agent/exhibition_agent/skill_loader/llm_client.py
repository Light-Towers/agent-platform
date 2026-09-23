"""LLM 客户端 — 已收敛到 agent_core.llm（OpenAICompatibleProvider + FallbackChatModel）。

支持任何兼容 OpenAI Chat Completions 格式的 provider：
- OpenAI: https://api.openai.com/v1
- 通义千问: https://dashscope.aliyuncs.com/compatible-mode/v1
- 智谱: https://open.bigmodel.cn/api/paas/v4
- Moonshot: https://api.moonshot.cn/v1
- DeepSeek: https://api.deepseek.com/v1
- 本地 Ollama: http://localhost:11434/v1

环境变量：
- LLM_API_KEY：API 密钥（必填）
- LLM_BASE_URL：API 地址（默认 https://api.openai.com/v1）
- LLM_MODEL：模型名（默认 gpt-4o-mini）

经 agent_core.llm.OpenAICompatibleProvider 构造 ChatOpenAI，
经 agent_core.llm.FallbackChatModel 包装主备降级 + 熔断 + usage 回调。
接口保持 chat_completion(messages, tools) → dict 不变，ExhibitionAgent 无需改。
"""

from __future__ import annotations

import os
from typing import Any


class LLMClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ):
        self.api_key = api_key or os.environ.get("LLM_API_KEY", "")
        self.base_url = (
            base_url
            or os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1")
        ).rstrip("/")
        self.model = model or os.environ.get("LLM_MODEL", "gpt-4o-mini")
        self._llm: Any = None
        if self.configured:
            self._llm = self._build_llm()

    def _build_llm(self) -> Any:
        from agent_core.llm import OpenAICompatibleProvider
        from agent_core.llm.fallback import FallbackChatModel

        provider = OpenAICompatibleProvider()
        primary = provider.build(
            model=self.model,
            api_key=self.api_key,
            base_url=self.base_url,
            temperature=0.3,
        )
        fallback = provider.build(
            model="gpt-4o-mini",
            api_key=self.api_key,
            base_url=self.base_url,
            temperature=0.3,
        )
        return FallbackChatModel(primary, fallback)

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def config_info(self) -> dict:
        return {
            "configured": self.configured,
            "model": self.model,
            "base_url": self.base_url,
            "api_key_set": bool(self.api_key),
        }

    async def chat_completion(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float = 0.3,
        timeout: float = 60.0,
    ) -> dict:
        """调用 LLM chat completions，返回 assistant message（含 content 和 tool_calls）。

        内部经 agent_core.llm.FallbackChatModel → ChatOpenAI.ainvoke()，
        消息格式 dict ↔ LangChain BaseMessage 自动转换。
        """
        if not self.configured or self._llm is None:
            raise ValueError(
                "LLM_API_KEY 未配置，请在环境变量中设置 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL"
            )

        from langchain_core.messages import (
            AIMessage,
            HumanMessage,
            SystemMessage,
            ToolMessage,
        )

        # dict messages → LangChain messages
        lc_messages: list[Any] = []
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            if role == "system":
                lc_messages.append(SystemMessage(content=content))
            elif role == "user":
                lc_messages.append(HumanMessage(content=content))
            elif role == "assistant":
                ai_msg = AIMessage(content=content)
                if m.get("tool_calls"):
                    ai_msg.additional_kwargs["tool_calls"] = m["tool_calls"]
                lc_messages.append(ai_msg)
            elif role == "tool":
                lc_messages.append(ToolMessage(content=content, tool_call_id=m.get("tool_call_id", "")))
            else:
                lc_messages.append(HumanMessage(content=content))

        # bind tools + invoke
        llm = self._llm
        if tools:
            # tools 是 OpenAI function calling 格式，ChatOpenAI.bind_tools 接受此格式
            bound = llm.primary.bind_tools(tools)
            resp = await bound.ainvoke(lc_messages)
        else:
            resp = await llm.ainvoke(lc_messages)

        # AIMessage → dict（OpenAI assistant message 格式）
        result: dict[str, Any] = {"role": "assistant", "content": resp.content or ""}
        tool_calls = getattr(resp, "tool_calls", None)
        if tool_calls:
            result["tool_calls"] = [
                {
                    "id": tc.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": tc.get("name", ""),
                        "arguments": tc.get("args", "{}") if isinstance(tc.get("args"), str) else
                            __import__("json").dumps(tc.get("args", {}), ensure_ascii=False),
                    },
                }
                for tc in tool_calls
            ]
        return result
