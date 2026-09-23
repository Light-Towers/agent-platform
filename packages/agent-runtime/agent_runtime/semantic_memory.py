"""Semantic Memory 边界声明（四类 Memory 阶段 1B）：已知的事实/知识是什么。

显式区分两个层级，避免"一库化"混淆：

- ``SharedSemantic``：平台级共享知识（knowledge-service：Milvus + Neo4j + MinIO）
  — 业务文档 / 行业知识 / Ontology，按 knowledge_id / tenant_id 隔离
- ``UserSemantic``：用户级事实记忆（agent-core memory typed.SEMANTIC）
  — 用户偏好 / 对话中提取的事实，按 user_id / workspace_id 隔离

两者层级不同、写入机制不同、召回策略不同，不应混入同一个 Vector DB。
"""

from __future__ import annotations

import abc
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SemanticRecallRequest:
    """语义记忆召回请求。"""

    query: str
    tenant_id: str | None = None
    user_id: str | None = None
    workspace_id: str | None = None
    knowledge_id: str | None = None  # 限定知识库
    top_k: int = 10
    filters: dict[str, Any] = field(default_factory=dict)


@dataclass
class SemanticRecallResult:
    """语义记忆召回结果。"""

    content: str
    source: str = ""  # "shared" / "user"
    score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "source": self.source,
            "score": self.score,
            "metadata": self.metadata,
        }


class SharedSemanticStore(abc.ABC):
    """平台级共享语义记忆契约（knowledge-service 后端）。

    存储的是"文档知识"——经过 RAG 导入流程（PDF→MD→split→embed→Milvus）
    治理后的结构化知识，非原始聊天记录。
    """

    @abc.abstractmethod
    async def recall(self, request: SemanticRecallRequest) -> list[SemanticRecallResult]:
        """从共享知识库召回。"""


class UserSemanticStore(abc.ABC):
    """用户级语义记忆契约（agent-core memory typed.SEMANTIC）。

    存储的是"用户事实"——从对话中 LLM 提取的结构化事实
    （如 preferred_city = Shanghai），非全文记忆。
    """

    @abc.abstractmethod
    async def recall(self, request: SemanticRecallRequest) -> list[SemanticRecallResult]:
        """从用户事实记忆召回。"""

    @abc.abstractmethod
    async def remember(
        self,
        user_id: str,
        content: str,
        importance: float = 0.5,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """沉淀用户事实。"""

    @abc.abstractmethod
    async def forget(self, user_id: str, content: str) -> bool:
        """遗忘用户事实。"""


class SemanticMemory:
    """Semantic Memory 门面：统一共享 + 用户两级语义记忆。

    用法：
    ```
    sem = SemanticMemory(shared_store=..., user_store=...)
    results = await sem.recall(request)
    # results 自动标注 source="shared" / "user"
    ```
    """

    def __init__(
        self,
        shared_store: SharedSemanticStore | None = None,
        user_store: UserSemanticStore | None = None,
    ) -> None:
        self._shared = shared_store
        self._user = user_store

    async def recall(
        self, request: SemanticRecallRequest
    ) -> list[SemanticRecallResult]:
        """统一召回：并行查共享 + 用户，合并排序。

        共享知识（文档/行业知识）和用户事实（偏好/提取事实）
        分属不同层级，各自召回后合并。
        """
        results: list[SemanticRecallResult] = []

        if self._shared is not None:
            try:
                shared_results = await self._shared.recall(request)
                for r in shared_results:
                    r.source = "shared"
                    results.append(r)
            except Exception:
                logger.warning("shared semantic recall failed", exc_info=True)

        if self._user is not None and request.user_id is not None:
            try:
                user_results = await self._user.recall(request)
                for r in user_results:
                    r.source = "user"
                    results.append(r)
            except Exception:
                logger.warning("user semantic recall failed", exc_info=True)

        results.sort(key=lambda r: r.score, reverse=True)
        return results[: request.top_k]

    async def remember_fact(
        self,
        user_id: str,
        content: str,
        importance: float = 0.5,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """沉淀用户事实（仅 UserSemantic）。"""
        if self._user is None:
            return
        await self._user.remember(user_id, content, importance, metadata)

    async def forget_fact(self, user_id: str, content: str) -> bool:
        """遗忘用户事实。"""
        if self._user is None:
            return False
        return await self._user.forget(user_id, content)


__all__ = [
    "SemanticRecallRequest",
    "SemanticRecallResult",
    "SharedSemanticStore",
    "UserSemanticStore",
    "SemanticMemory",
]
