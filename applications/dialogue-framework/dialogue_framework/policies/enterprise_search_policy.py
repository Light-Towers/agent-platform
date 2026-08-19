"""EnterpriseSearchPolicy：企业搜索策略，依赖 retrieval/。"""

from typing import Any

from dialogue_framework.policies.base_policy import Action


class EnterpriseSearchPolicy:
    def __init__(self, retriever) -> None:
        self._retriever = retriever

    async def predict(self, state: dict[str, Any]) -> list[Action]:
        query = state.get("user_message", "")
        if not query:
            return []
        results = await self._retriever.retrieve(query)
        if results:
            return [Action(name="search", params={"results": results})]
        return []
