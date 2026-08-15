"""下载 BGE-Reranker-Large 重排模型到本地缓存目录（需完整依赖，手动运行）。

模型缓存目录优先使用 .env 中的 MODELSCOPE_CACHE，未配置则回退到 MODELS_DIR/modelscope_cache。
运行方式（在项目根目录）：python app/tool/download_reranker.py
"""

import os
import sys

# 确保可以从项目根目录以 `python app/tool/download_reranker.py` 运行
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from modelscope.hub.snapshot_download import snapshot_download  # noqa: E402

from app.core.config import settings  # noqa: E402

# 下载模型到统一缓存目录（替代原脚本中写死的本地绝对路径）
local_dir = settings.modelscope_cache

snapshot_download(
    model_id="BAAI/bge-reranker-large",
    cache_dir=local_dir,
)

print("下载完成，模型目录：", local_dir)
