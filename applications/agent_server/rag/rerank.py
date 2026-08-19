"""Rerank 客户端：硅基流动 bge-reranker-v2-m3（OpenAI 兼容 /rerank）。

零第三方依赖（仅标准库 urllib），与 zhanggui-zhiku 的 ApiReranker 同语义；
放在 app 内自洽，避免跨子项目耦合。主 app RAG 在 RRF 融合后调用本模块对
候选 chunk 做相关性重排，提升 top-K 精度。

无 key / 未开启时由调用方跳过（回退到融合排序）。
"""

import json
import time
import urllib.error
import urllib.request
from functools import lru_cache

_DEFAULT_TIMEOUT_S = 30.0
_DEFAULT_RETRIES = 2
_DEFAULT_BACKOFF_S = 0.5
_DEFAULT_BATCH_SIZE = 64


class ApiReranker:
    """compute_score 与 FlagReranker 同签名/同语义。

    compute_score(sentence_pairs) -> list[float]
        入参 list[[query, doc], ...]，返回与输入一一对应的相关性分数（0~1，越高越相关）。
    """

    def __init__(
        self,
        api_key: str,
        base_url: str | None = None,
        model: str | None = None,
        batch_size: int = _DEFAULT_BATCH_SIZE,
        timeout: float = _DEFAULT_TIMEOUT_S,
    ):
        if not api_key:
            raise ValueError("rerank_api_key 未配置")
        self.api_key = api_key
        self.base_url = (base_url or "https://api.siliconflow.cn/v1").rstrip("/")
        self.model = model or "BAAI/bge-reranker-v2-m3"
        self.batch_size = max(1, int(batch_size))
        self.timeout = timeout
        self._url = f"{self.base_url}/rerank"
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def _post(self, payload: dict) -> dict:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(self._url, data=data, headers=self._headers, method="POST")
        last_err: Exception | None = None
        for attempt in range(_DEFAULT_RETRIES + 1):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                detail = ""
                try:
                    detail = e.read().decode("utf-8")
                except Exception:
                    pass
                last_err = RuntimeError(f"SiliconFlow rerank HTTP {e.code}: {detail[:500]}")
                if e.code not in (429, 500, 502, 503, 504) or attempt >= _DEFAULT_RETRIES:
                    break
                time.sleep(_DEFAULT_BACKOFF_S * (attempt + 1))
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
                last_err = RuntimeError(f"SiliconFlow rerank 网络请求失败: {e}")
                if attempt >= _DEFAULT_RETRIES:
                    break
                time.sleep(_DEFAULT_BACKOFF_S * (attempt + 1))
        raise last_err or RuntimeError("SiliconFlow rerank 请求失败")

    def compute_score(self, sentence_pairs: list[list[str]]) -> list[float]:
        scores = [0.0] * len(sentence_pairs)
        for i in range(0, len(sentence_pairs), self.batch_size):
            batch = sentence_pairs[i : i + self.batch_size]
            batch_pos = list(range(i, i + len(batch)))
            batch_docs = [p[1] for p in batch]
            payload = {
                "model": self.model,
                "query": batch[0][0],
                "documents": batch_docs,
                "return_documents": False,
            }
            resp = self._post(payload)
            results = resp.get("results", [])
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


@lru_cache
def get_reranker() -> ApiReranker | None:
    """按当前配置惰性构造 reranker；未开启/无 key 返回 None。"""
    from agent_server.config import get_settings

    s = get_settings()
    if not s.rerank_effective_enabled:
        return None
    return ApiReranker(
        api_key=s.rerank_api_key,
        base_url=s.rerank_base_url,
        model=s.rerank_model,
    )
