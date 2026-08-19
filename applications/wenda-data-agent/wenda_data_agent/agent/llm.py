"""LLM 客户端：对齐 langchain-openai>=0.3。"""

from typing import Any

from agent_core.logging import get_logger

logger = get_logger(__name__)


class LLMClient:
    """LLM 客户端封装。"""

    def __init__(self, api_key: str = "", model: str = "gpt-4o-mini", base_url: str = "") -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url
        self._llm = None

    def _ensure_llm(self) -> Any:
        if self._llm is None:
            from langchain_openai import ChatOpenAI

            kwargs: dict[str, Any] = {"api_key": self._api_key, "model": self._model}
            if self._base_url:
                kwargs["base_url"] = self._base_url
            self._llm = ChatOpenAI(**kwargs)
        return self._llm

    async def invoke(self, prompt: str) -> str:
        if not self._api_key:
            return ""
        try:
            from langchain_core.messages import HumanMessage

            llm = self._ensure_llm()
            result = await llm.ainvoke([HumanMessage(content=prompt)])
            return result.content.strip()
        except Exception:
            logger.exception("LLM invoke failed")
            return ""

    @property
    def enabled(self) -> bool:
        return bool(self._api_key)


def build_llm() -> LLMClient:
    from wenda_data_agent.conf.settings import get_settings

    s = get_settings()
    return LLMClient(api_key=s.llm_api_key, model=s.llm_model, base_url=s.llm_base_url)
