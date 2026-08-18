"""把 agent-platform 的混合检索（retrieve_chunks）适配为 FlashRAG 的 BaseTextRetriever。

FlashRAG 约定：
- 子类实现 _search(query, num, return_score) 与 _batch_search(...)
- 检索结果写回 Item.retrieval_result，格式为 [{"contents": str, ...}, ...]
- rerank 开关由 app 的 .env (RERANK_ENABLED) 控制：本适配器不改配置，
  只在 run_eval.py 里分别用「关 rerank」与「开 rerank」两次运行来做对照实验。
"""

import asyncio
import threading
from typing import List, Optional

from flashrag.retriever.retriever import BaseTextRetriever


class _LoopThread(threading.Thread):
    """独立线程跑一个常驻 event loop，供同步接口安全地提交 coroutine。

    FlashRAG 的 retriever.search 是同步的，而底层 retrieve_chunks 是 async。
    若在主线程已有的 running loop 里再 run_until_complete 会抛
    'This event loop is already running'。把 loop 放到独立线程即可解耦：
    主线程同步调用 search -> run_coroutine_threadsafe 投递到 loop 线程 -> 拿到结果。
    """

    def __init__(self):
        super().__init__(daemon=True)
        self.loop = asyncio.new_event_loop()
        self._ready = threading.Event()

    def run(self):
        asyncio.set_event_loop(self.loop)
        self._ready.set()
        self.loop.run_forever()

    def submit(self, coro):
        self._ready.wait()
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        return future.result()


class AgentRetriever(BaseTextRetriever):
    """委托给 app.rag.store.retrieve_chunks 的混合检索器。"""

    def __init__(self, config, pool=None):
        super().__init__(config)
        self.pool = pool
        self._lt = _LoopThread()
        self._lt.start()

    def _to_flashrag_docs(self, chunks: List[dict]) -> List[dict]:
        docs = []
        for c in chunks:
            docs.append(
                {
                    "contents": c.get("content", ""),
                    "title": c.get("heading") or c.get("source") or "",
                    "id": c.get("id"),
                    "score": c.get("score"),
                }
            )
        return docs

    def _search(self, query: str, num: int = None, return_score: bool = False):
        if num is None:
            num = self.topk
        chunks = self._lt.submit(retrieve_chunks_safe(self.pool, query, k=num))
        docs = self._to_flashrag_docs(chunks)
        if return_score:
            return docs, [d.get("score") for d in docs]
        return docs

    def _batch_search(self, query_list, num: int = None, return_score: bool = False):
        if num is None:
            num = self.topk
        out_docs, out_scores = [], []
        for q in query_list:
            docs = self._search(q, num=num, return_score=return_score)
            if return_score:
                out_docs.append(docs[0])
                out_scores.append(docs[1])
            else:
                out_docs.append(docs)
        if return_score:
            return out_docs, out_scores
        return out_docs


async def retrieve_chunks_safe(pool, query: str, k: int):
    from app.rag.store import retrieve_chunks

    return await retrieve_chunks(pool, query, k=k)


