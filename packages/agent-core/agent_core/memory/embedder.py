# -*- coding: utf-8 -*-
"""共享 Embedding 提供方（所有子包统一入口，消除各自为政）。

按配置动态选择来源（优先级从高到低）：
  - ``EMBEDDING_MODE=mock``（或 auto 且无远程密钥）→ ``MockEmbedder``（确定性 hash 向量，零成本、零网络）
  - 配了 ``SILICONFLOW_API_KEY``                           → 远程硅基流动 API（默认 BAAI/bge-m3，1024 维）
  - 否则                                                  → 本地 sentence-transformers（BAAI/bge-small-zh-v1.5，512 维）

维度由所选模型自动派生（mock 由 ``EMBEDDING_DIM`` 控制，默认 512），调用方无需关心。
依赖均为懒加载，缺包时抛出明确 ImportError，不阻断模块导入期。

此前该逻辑散落在 deepagents/classifier.py（本地）、deepagents/memory/vector_backends.py
（本地+远程）、zhanggui-zhiku/app/lm/siliconflow_client.py（远程）、app/rag/embed.py（mock+远程）
四处，现统一收口到内核，子包统一 import。
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import os
from typing import Any, Protocol

from agent_core.logging import get_logger

logger = get_logger(__name__)


class EmbeddingProvider(Protocol):
    """统一 embedding 接口：embed(texts) -> list[list[float]]（L2 归一化）。"""

    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class MockEmbedder:
    """确定性 mock embedding：基于内容哈希生成固定向量，零成本、零网络。

    用于开发/CI 零密钥环境跑通链路（语义相似度无意义，检索质量由上层兜底）。
    dim 由 ``EMBEDDING_DIM`` 控制，默认 512（与 app 的 vector_dim 对齐）。
    """

    def __init__(self, dim: int | None = None) -> None:
        self.dim = int(dim or int(os.getenv("EMBEDDING_DIM", "512")))

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for text in texts:
            vec: list[float] = []
            counter = 0
            while len(vec) < self.dim:
                digest = hashlib.sha256(f"{text}:{counter}".encode()).digest()
                vec.extend(b / 255.0 - 0.5 for b in digest)
                counter += 1
            vec = vec[: self.dim]
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            out.append([v / norm for v in vec])
        return out


# ── 模块级网络 / 向量辅助（远程提供方共享，且可在测试中 monkeypatch） ──
def _http_post_json(url, headers, payload, timeout=60.0, retries=2, backoff=0.5):
    """POST JSON 并返回解析后的响应（对 429/5xx/网络异常简单重试）。

    失败抛 RuntimeError；4xx 业务错误直接抛出不重试。可在测试中
    ``monkeypatch.setattr("agent_core.memory.embedder._http_post_json", fake)``。
    """
    import json
    import time
    import urllib.error
    import urllib.request

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
            last_err = RuntimeError(f"Embedding HTTP {e.code}: {detail[:500]}")
            if e.code not in (429, 500, 502, 503, 504) or attempt >= retries:
                break
            time.sleep(backoff * (attempt + 1))
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_err = RuntimeError(f"Embedding 网络请求失败: {e}")
            if attempt >= retries:
                break
            time.sleep(backoff * (attempt + 1))
    raise last_err


def _l2_normalize(vector: list[float]) -> list[float]:
    """L2 归一化；零向量原样返回。"""
    norm = math.sqrt(sum(float(x) * float(x) for x in vector))
    return [float(x) / norm for x in vector] if norm > 1e-9 else [0.0] * len(vector)


class RemoteEmbedder:
    """通用 OpenAI 兼容 /embeddings 远程提供方（仅依赖标准库 urllib）。

    配置（环境变量）：
      - ``EMBEDDING_API_KEY``  （必填）
      - ``EMBEDDING_BASE_URL``（默认 https://api.openai.com/v1）
      - ``EMBEDDING_MODEL``    （默认 bge-small-zh）
    维度由 ``EMBEDDING_DIM`` 控制（默认 512）；若返回向量维度不一致可显式设置。
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        model: str = "bge-small-zh",
        dim: int | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("EMBEDDING_API_KEY 未配置")
        self._url = base_url.rstrip("/") + "/embeddings"
        self._model = model
        self._dim = int(dim or int(os.getenv("EMBEDDING_DIM", "512")))
        self.dim = self._dim
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def embed(self, texts: list[str]) -> list[list[float]]:
        resp = _http_post_json(self._url, self._headers, {"model": self._model, "input": texts})
        data = resp.get("data")
        if not data:
            raise ValueError(f"Embedding API 返回格式异常（缺 data 字段）: {resp}")
        data = sorted(data, key=lambda d: int(d.get("index", 0)))
        return [_l2_normalize(d["embedding"]) for d in data]


class LocalEmbedder:
    """本地 sentence-transformers（离线、零成本）。

    默认 BAAI/bge-small-zh-v1.5（512 维）；可用 INTENT_EMBEDDING_MODEL 覆盖。
    """

    def __init__(self, model: str = "BAAI/bge-small-zh-v1.5") -> None:
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model)
        # sentence-transformers 近期将 get_sentence_embedding_dimension 重命名为
        # get_embedding_dimension，旧方法触发 FutureWarning；做兼容回退。
        _dim_fn = getattr(
            self._model,
            "get_embedding_dimension",
            self._model.get_sentence_embedding_dimension,
        )
        self.dim = int(_dim_fn())

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
        results: list[list[float]] = []
        for i in range(0, len(texts), self._batch_size):
            batch = texts[i : i + self._batch_size]
            resp = _http_post_json(self._url, self._headers, {"model": self._model, "input": batch})
            data = sorted(resp.get("data") or [], key=lambda it: int(it.get("index", 0)))
            if len(data) != len(batch):
                raise RuntimeError(
                    f"SiliconFlow embeddings 数量不匹配：请求{len(batch)}条，返回{len(data)}条"
                )
            for it in data:
                vec = it.get("embedding")
                if not isinstance(vec, list) or not vec:
                    raise RuntimeError("SiliconFlow embeddings 响应缺少 embedding 字段")
                results.append(_l2_normalize(vec))
        return results


_EMBEDDER: EmbeddingProvider | None = None


def get_embedder(force: bool = False) -> EmbeddingProvider:
    """按配置返回 embedding 提供方（统一入口）。

    ``force=True`` 时忽略缓存，重新读取环境配置（宿主在调用前已更新环境变量时使用，
    例如 app 把自身 ``embedding_*`` 配置映射为内核 env 后强制重建）。

    选择逻辑（优先级从高到低）：
      1. ``EMBEDDING_MODE=mock``（或 auto 且无远程密钥）→ ``MockEmbedder``（CI/零密钥）
      2. ``EMBEDDING_MODE=remote`` 或配了 ``EMBEDDING_API_KEY`` → 通用远程 ``RemoteEmbedder``
         （OpenAI 兼容 /embeddings；硅基流动等兼容服务只需填对应 BASE_URL）
      3. 仅配了 ``SILICONFLOW_API_KEY``（未配通用 ``EMBEDDING_API_KEY``）→ ``SiliconFlowEmbedder``
         （专用硅基流动实现，模型默认 bge-m3=1024，与既有向量数据维度一致）
      4. 否则 → 本地 sentence-transformers（``INTENT_EMBEDDING_MODEL`` 可覆盖）

    维度约定：mock/remote 由 ``EMBEDDING_DIM`` 控制（默认 512），
    本地/硅基流动由模型自动派生（bge-small-zh=512 / bge-m3=1024）。

    注意：``SILICONFLOW_API_KEY`` 既作为通用远程的别名（走 RemoteEmbedder），
    也可作为专用硅基流动实现（SiliconFlowEmbedder，1024 维）。为避免维度错配破坏
    既有向量数据，专用硅基流动实现优先级高于通用 RemoteEmbedder，仅当显式配置
    ``EMBEDDING_API_KEY`` 或 ``EMBEDDING_MODE=remote`` 时才走通用 RemoteEmbedder（512 维）。
    """
    global _EMBEDDER
    if _EMBEDDER is not None and not force:
        return _EMBEDDER
    mode = os.getenv("EMBEDDING_MODE", "auto").lower()
    api_key = os.getenv("EMBEDDING_API_KEY")
    siliconflow_key = os.getenv("SILICONFLOW_API_KEY")

    if mode == "mock" or (mode == "auto" and not api_key and not siliconflow_key):
        _EMBEDDER = MockEmbedder()
        logger.info("Embedding 使用 Mock（确定性 hash，dim=%s）", _EMBEDDER.dim)
        return _EMBEDDER
    if mode == "remote" or api_key:
        # 通用 OpenAI 兼容远程：EMBEDDING_* 优先
        _EMBEDDER = RemoteEmbedder(
            api_key=api_key or "",
            base_url=os.getenv("EMBEDDING_BASE_URL", "https://api.openai.com/v1"),
            model=os.getenv("EMBEDDING_MODEL", "bge-small-zh"),
        )
        logger.info("Embedding 使用远程（OpenAI 兼容，dim=%s）", _EMBEDDER.dim)
        return _EMBEDDER
    if siliconflow_key:
        # 专用硅基流动实现（1024 维 bge-m3），与既有向量数据维度一致
        _EMBEDDER = SiliconFlowEmbedder(
            api_key=siliconflow_key,
            base_url=os.getenv("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1"),
            model=os.getenv("SILICONFLOW_EMBEDDING_MODEL", "BAAI/bge-m3"),
        )
        logger.info("Embedding 使用远程硅基流动: %s", _EMBEDDER.dim)
        return _EMBEDDER
    _EMBEDDER = LocalEmbedder(os.getenv("INTENT_EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5"))
    logger.info("Embedding 使用本地模型: %s", _EMBEDDER.dim)
    return _EMBEDDER


async def embed_one(embedder: EmbeddingProvider, text: str) -> list[float]:
    """嵌入单条文本：统一 aembed / 同步 embed 分支（各向量后端共享入口）。

    - 提供方有 ``aembed``（异步，如 LocalFnEmbedder）→ 直接 await；
    - 否则同步 ``embed`` 丢到默认线程池（``asyncio.to_thread``），不阻塞事件循环。

    取代各向量后端各自的实现（原 MilvusMemoryBackend._aembed /
    PgVectorMemoryBackend._embed_one，二者逻辑相同）。以后接入 OpenAI / BGE /
    Jina / 本地等新提供方，后端无需感知。
    """
    if hasattr(embedder, "aembed"):
        return (await embedder.aembed([text]))[0]
    return (await asyncio.to_thread(embedder.embed, [text]))[0]


__all__ = [
    "EmbeddingProvider",
    "MockEmbedder",
    "LocalEmbedder",
    "SiliconFlowEmbedder",
    "RemoteEmbedder",
    "LocalFnEmbedder",
    "embed_one",
    "get_embedder",
]


class LocalFnEmbedder:
    """适配宿主自有 embedding 函数（async ``embed_texts(texts) -> list[list[float]]``）。

    用于宿主已有稳定 embedding 实现（如 app 的 RAG embed，含 mock/OpenAI 兼容 +
    特定 dim），避免内核后端强制使用共享 embedder 造成维度/CI 不一致。宿主只需提供
    函数与声明 dim。结果按 L2 归一化（与内置提供方一致，保证余弦相似度语义正确）。
    """

    def __init__(self, embed_fn: Any, dim: int) -> None:
        self._fn = embed_fn
        self.dim = int(dim)

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        raw = await self._fn(texts)
        out: list[list[float]] = []
        for vec in raw:
            norm = math.sqrt(sum(float(v) * float(v) for v in vec)) or 1.0
            out.append([float(v) / norm for v in vec])
        return out

    async def aembed(self, texts: list[str]) -> list[list[float]]:
        """异步 embedding（async 后端直接 await，无嵌套事件循环死锁风险）。"""
        return await self._embed(texts)

    def embed(self, texts: list[str]) -> list[list[float]]:
        """同步 embedding：仅在无运行中的事件循环时调用（如离线脚本）。

        已在事件循环内时，调用方应使用 ``aembed``（异步路径），避免嵌套
        ``asyncio.run`` 死锁。此处保留同步入口，便于非 async 上下文复用。
        """
        import asyncio

        return asyncio.run(self._embed(texts))
