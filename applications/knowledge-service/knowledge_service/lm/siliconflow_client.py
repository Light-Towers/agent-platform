# -*- coding: utf-8 -*-
"""
knowledge_service/lm/siliconflow_client.py —— 硅基流动（SiliconFlow）API 客户端（M8）。

仅依赖 Python 标准库 urllib，不引入任何第三方网络依赖：
- 无 GPU / 未安装 FlagEmbedding / pymilvus.model 也能运行 api 模式（裸 venv 可测）；
- 所有网络请求收敛到 `_post_json`，单测以 mock 该函数验证，不真调网络。

能力：
1. SiliconFlowEmbeddingClient.embed(texts) -> list[list[float]]
   POST {BASE_URL}/embeddings（OpenAI 兼容），返回 **L2 归一化**稠密向量
   （硅基流动不保证返回向量已归一化，本地归一化与 local 模式 BGE-M3 产物语义对齐，
   适配 Milvus dense COSINE / IP 检索）。
2. ApiReranker.compute_score(sentence_pairs) -> list[float]
   POST {BASE_URL}/rerank，与 FlagReranker.compute_score **同签名 / 同语义**：
   入参 list[[query, doc], ...]，返回顺序与输入一一对应，分数越高越相关。

批量与重试：
- embedding 单批默认 16 条（上游 node_bge_embedding 按 5 条/批喂入，api 端一次多传）；
- rerank 单批默认 64 条（query 相同的一批 documents 一次调用）；
- 429/5xx/网络异常重试经 agent_core.resilience.retry（默认 2 次、指数退避 0.5s 起），不做熔断。
"""

import json
import math
import urllib.error
import urllib.request

from agent_core.resilience import retry

from knowledge_service.lm._logging import logger

DEFAULT_TIMEOUT_S = 30.0
DEFAULT_RETRIES = 2
DEFAULT_BACKOFF_S = 0.5
DEFAULT_EMBEDDING_BATCH_SIZE = 16
DEFAULT_RERANK_BATCH_SIZE = 64


def _post_json(url, headers, payload, timeout=DEFAULT_TIMEOUT_S, retries=DEFAULT_RETRIES, backoff=DEFAULT_BACKOFF_S):
    """
    POST JSON 请求并返回解析后的响应（429/5xx/网络异常重试，经 agent_core.resilience.retry）。

    :param url: 完整请求地址
    :param headers: 请求头（含 Authorization）
    :param payload: JSON 请求体（dict）
    :param timeout: 单次请求超时（秒）
    :param retries: 重试次数（在首次尝试之外）
    :param backoff: 退避基数（秒），指数退避 backoff * 2^(n-1)
    :return: 解析后的响应（dict / list）
    :raises RuntimeError: 429/5xx 重试耗尽后仍失败；HTTPError: 4xx 业务错误直接抛出
    """
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")

    @retry(
        max_attempts=retries + 1,
        backoff_base=backoff,
        exceptions=(
            urllib.error.URLError,
            TimeoutError,
            ConnectionError,
            OSError,
            RuntimeError,
        ),
    )
    def _do_post():
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw)
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8")
            except Exception as e:  # noqa: BLE001
                logger.warning("读取 SiliconFlow HTTP 错误详情失败: %s", e)
            if e.code in (429, 500, 502, 503, 504):
                raise RuntimeError(f"SiliconFlow HTTP {e.code}: {detail[:500]}") from e
            raise

    return _do_post()


def _l2_normalize(vector):
    """
    L2 归一化稠密向量（API 不保证归一化，需与 local 模式产物语义对齐）。

    :param vector: 稠密向量（数值列表）
    :return: 归一化后的向量（list[float]）；零向量原样返回
    """
    norm = math.sqrt(sum(float(x) * float(x) for x in vector))
    if norm < 1e-9:
        return [0.0] * len(vector)
    return [float(x) / norm for x in vector]


class SiliconFlowEmbeddingClient:
    """硅基流动 embeddings API 客户端（稠密向量，本地 L2 归一化）。

    实现已委托内核 agent_core.memory.embedder.SiliconFlowEmbedder（零依赖 urllib +
    L2 归一化 + index 重排统一收口，消除与 knowledge_service 等子项目各自为政的重复实现）。
    本类仅保留批量切分与响应数量校验（内核基础能力之上），向后兼容 embedding_utils 调用。
    """

    def __init__(self, api_key, base_url=None, model=None, batch_size=DEFAULT_EMBEDDING_BATCH_SIZE):
        """
        :param api_key: 硅基流动 API Key（必填）
        :param base_url: OpenAI 兼容基础地址（默认 https://api.siliconflow.cn/v1）
        :param model: embedding 模型（默认 BAAI/bge-m3）
        :param batch_size: 单次 API 调用最大文本条数（默认 16）
        """
        if not api_key:
            raise ValueError("SILICONFLOW_API_KEY 未配置")
        self.batch_size = max(1, int(batch_size))
        # 委托内核统一实现（维度/归一化/请求逻辑与 local BGE-M3 稠密语义对齐）
        from agent_core.memory.embedder import SiliconFlowEmbedder

        self._inner = SiliconFlowEmbedder(
            api_key=api_key,
            base_url=base_url or "https://api.siliconflow.cn/v1",
            model=model or "BAAI/bge-m3",
        )

    def embed(self, texts):
        """
        为文本列表生成 L2 归一化稠密向量（按 batch_size 切批调用内核实现）。

        :param texts: 非空文本列表（与 local 模式 generate_embeddings 入参一致）
        :return: list[list[float]]，与输入一一对应
        :raises ValueError: 入参不合法；RuntimeError: API 响应缺失/数量不匹配
        """
        if not isinstance(texts, list) or len(texts) == 0:
            raise ValueError("参数texts必须是非空列表")
        results = []
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i : i + self.batch_size]
            vecs = self._inner.embed(batch)
            if len(vecs) != len(batch):
                raise RuntimeError(
                    f"SiliconFlow embeddings 响应数量不匹配：请求{len(batch)}条，返回{len(vecs)}条"
                )
            results.extend(vecs)
        return results


class ApiReranker:
    """
    硅基流动 rerank API 客户端，compute_score 与 FlagReranker **同签名 / 同语义**。

    compute_score(sentence_pairs)：
        - 入参：list[[query, doc], ...]（与 node_rerank 传法一致，query 在前、doc 在后）；
        - 返回：list[float]，顺序与输入 sentence_pairs 一一对应，分数越高越相关（0~1）。
    """

    def __init__(self, api_key, base_url=None, model=None, batch_size=DEFAULT_RERANK_BATCH_SIZE):
        """
        :param api_key: 硅基流动 API Key（必填）
        :param base_url: OpenAI 兼容基础地址（默认 https://api.siliconflow.cn/v1）
        :param model: rerank 模型（默认 BAAI/bge-reranker-v2-m3）
        :param batch_size: 同一 query 单次 API 调用最大文档数（默认 64）
        """
        if not api_key:
            raise ValueError("SILICONFLOW_API_KEY 未配置")
        self.api_key = api_key
        self.base_url = (base_url or "https://api.siliconflow.cn/v1").rstrip("/")
        self.model = model or "BAAI/bge-reranker-v2-m3"
        self.batch_size = max(1, int(batch_size))
        self._url = f"{self.base_url}/rerank"
        self._headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    def compute_score(self, sentence_pairs):
        """
        计算 (query, doc) 对的相关性分数。

        :param sentence_pairs: 二元组/二元列表列表，形如 [[query, doc], ...]
        :return: list[float]，顺序与输入一一对应，分数越高越相关
        :raises ValueError: 元素非二元组；RuntimeError: API 响应缺失/数量不匹配
        """
        if not isinstance(sentence_pairs, list) or len(sentence_pairs) == 0:
            return []
        pairs = [tuple(p) for p in sentence_pairs]
        for p in pairs:
            if len(p) != 2:
                raise ValueError(f"sentence_pairs 元素必须为 (query, doc) 二元组: {p}")

        # 按 query 分组（保持首次出现顺序）：同一 query 的 documents 一次批量调用，
        # 减少 API 往返；同时记录每个 pair 的原始位置，返回时按位置回填，
        # 保证返回顺序与输入 sentence_pairs 严格一致。
        query_groups = []
        query_index = {}
        for pos, (query, doc) in enumerate(pairs):
            if query not in query_index:
                query_index[query] = len(query_groups)
                query_groups.append([query, []])
            query_groups[query_index[query]][1].append((pos, doc))

        scores = [0.0] * len(pairs)  # 按输入顺序占位
        for query, pos_docs in query_groups:
            docs = [d for _, d in pos_docs]
            for i in range(0, len(docs), self.batch_size):
                batch_pos = [p for p, _ in pos_docs[i : i + self.batch_size]]
                batch_docs = docs[i : i + self.batch_size]
                resp = _post_json(
                    self._url,
                    self._headers,
                    {"model": self.model, "query": query, "documents": batch_docs},
                )
                results = resp.get("results") or []
                # 兼容返回乱序：按 index 重排（缺失 index 时稳定排序保持原序）
                results = sorted(results, key=lambda r: int(r.get("index", 0)))
                if len(results) != len(batch_docs):
                    raise RuntimeError(
                        f"SiliconFlow rerank 响应数量不匹配：请求{len(batch_docs)}条，返回{len(results)}条"
                    )
                for r, pos in zip(results, batch_pos):
                    score = r.get("relevance_score")
                    if score is None:
                        raise RuntimeError(f"SiliconFlow rerank 响应缺少 relevance_score: {r}")
                    scores[pos] = float(score)
        return scores
