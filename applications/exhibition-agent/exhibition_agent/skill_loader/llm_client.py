"""LLM 客户端 — OpenAI 兼容 API 封装。

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
"""

from __future__ import annotations

import os

import httpx


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
        """调用 LLM chat completions，返回 assistant message（含 content 和 tool_calls）。"""
        if not self.configured:
            raise ValueError(
                "LLM_API_KEY 未配置，请在环境变量中设置 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL"
            )

        body: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                json=body,
                headers=headers,
            )
            if resp.status_code != 200:
                error_text = resp.text[:500]
                raise RuntimeError(
                    f"LLM 调用失败 (HTTP {resp.status_code}): {error_text}"
                )
            data = resp.json()

        choice = data["choices"][0]
        return choice["message"]
