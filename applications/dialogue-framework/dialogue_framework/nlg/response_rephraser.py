"""ResponseRephraser：LLM 响应重写，依赖 shared/llm。"""

from dialogue_framework.shared.llm.langchain_client import build_chat_model


async def rephrase(text: str, style: str = "友好") -> str:
    llm = build_chat_model()
    if llm is None:
        return text
    from langchain_core.messages import HumanMessage

    prompt = f"以{style}的语气重写以下回复，保持原意：\n{text}"
    resp = await llm.ainvoke([HumanMessage(content=prompt)])
    return resp.content if hasattr(resp, "content") else str(resp)
