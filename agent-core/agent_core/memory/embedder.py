# -*- coding: utf-8 -*-
"""共享 Embedding 提供方（所有子包统一入口，消除各自为政）。

按配置动态选择来源：
  - 配了 SILICONFLOW_API_KEY → 远程硅基流动 API（默认 BAAI/bge-m3，1024 维）
  - 否则                   → 本地 sentence-transformers（BAAI/bge-small-zh-v1.5，512 维）

维度由所选模型自动派生，调用方无需关心。依赖均为懒加载，缺包时抛出明确 ImportError，
不阻断模块导入期。

此前该逻辑散落在 deepagents/classifier.py（本地）、deepagents/memory/vector_backends.py
（本地+远程）、zhanggui-zhiku/app/lm/siliconflow_client.py（远程）三处，现统一收口到内核。
"""

from __future__ import annotations

import os
from typing import Protocol

from agent_core.logging import get_logger

logger = get_logger(__name__)


class EmbeddingProvider(Protocol):
    """统一 embedding 接口：embed(texts) -> list[list[float]]（L2 归一化）。"""

    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class LocalEmbedder:
    """本地 sentence-transformers（离线、零成本）。

    默认 BAAI/bge-small-zh-v1.5（512 维）；可用 INTENT_EMBEDDING_MODEL 覆盖。
    """

    def __init__(self, model: str = "BAAI/bge-small-zh-v1.5") -> None:
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model)
        self.dim = int(self._model.get_sentence_embedding_dimension())

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self._model.encode(texts, normalize_embeddings=True).tolist()


class SiliconFlowEmbedder:
    """远程硅基流动 embeddings API（仅依赖标准库 urllib）。

    返回 L2 归一化向量。默认模型 BAAI/bge-m3（1024 维）。
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.siliconflow.cn/v1",
        model: str = "BAAI/bge-m3",
        batch_size: int = 16,
    ) -> None:
        if not api_key:
            raise ValueError("SILICONFLOW_API_KEY 未配置")
        self._api_key = api_key
        self._url = base_url.rstrip("/") + "/embeddings"
        self._model = model
        self._batch_size = max(1, int(batch_size))
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        # bge-m3 输出 1024 维；其他模型可按需扩展映射。
        self.dim = 1024 if "bge-m3" in model else 512

    def embed(self, texts: list[str]) -> list[list[float]]:
        import json
        import math
        import time
        import urllib.error
        import urllib.request

        def _post_json(url, headers, payload, timeout=30.0, retries=2, backoff=0.5):
            body = json.dumps(payload).encode("utf-8")
            last_err: Exception | None = None
            for attempt in range(retries + 1):
                req = urllib.request.Request(url, data=body, headers=headers, method="POST")
                try:
                    with urllib.request.urlopen(req, timeout=timeout) as resp:
                        return json.loads(resp.read().decode("utf-8"))
                except urllib.error.HTTPError as e:
                    detail = ""
                    try:
                        detail = e.read().decode("utf-8")
                    except Exception:
                        pass
                    last_err = RuntimeError(f"SiliconFlow HTTP {e.code}: {detail[:500]}")
                    if e.code not in (429, 500, 502, 503, 504) or attempt >= retries:
                        break
                    time.sleep(backoff * (attempt + 1))
                except (urllib.error.URLError, TimeoutError, OSError) as e:
                    last_err = RuntimeError(f"SiliconFlow 网络请求失败: {e}")
                    if attempt >= retries:
                        break
                    time.sleep(backoff * (attempt + 1))
            raise last_err

        def _l2(v):
            norm = math.sqrt(sum(float(x) * float(x) for x in v))
            return [float(x) / norm for x in v] if norm > 1e-9 else [0.0] * len(v)

        results: list[list[float]] = []
        for i in range(0, len(texts), self._batch_size):
            batch = texts[i : i + self._batch_size]
            resp = _post_json(self._url, self._headers, {"model": self._model, "input": batch})
            data = sorted(resp.get("data") or [], key=lambda it: int(it.get("index", 0)))
            if len(data) != len(batch):
                raise RuntimeError(
                    f"SiliconFlow embeddings 数量不匹配：请求{len(batch)}条，返回{len(data)}条"
                )
            for it in data:
                vec = it.get("embedding")
                if not isinstance(vec, list) or not vec:
                    raise RuntimeError("SiliconFlow embeddings 响应缺少 embedding 字段")
                results.append(_l2(vec))
        return results


_EMBEDDER: EmbeddingProvider | None = None


def get_embedder() -> EmbeddingProvider:
    """按配置返回 embedding 提供方：有 SILICONFLOW_API_KEY 用远程，否则本地。"""
    global _EMBEDDER
    if _EMBEDDER is not None:
        return _EMBEDDER
    api_key = os.getenv("SILICONFLOW_API_KEY")
    if api_key:
        _EMBEDDER = SiliconFlowEmbedder(
            api_key=api_key,
            base_url=os.getenv("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1"),
            model=os.getenv("SILICONFLOW_EMBEDDING_MODEL", "BAAI/bge-m3"),
        )
        logger.info("Embedding 使用远程硅基流动: %s", _EMBEDDER.dim)
    else:
        _EMBEDDER = LocalEmbedder(os.getenv("INTENT_EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5"))
        logger.info("Embedding 使用本地模型: %s", _EMBEDDER.dim)
    return _EMBEDDER


__all__ = ["EmbeddingProvider", "LocalEmbedder", "SiliconFlowEmbedder", "get_embedder"]
