# 导入核心依赖：数据类、统一配置
from dataclasses import dataclass
from app.core.config import settings


@dataclass
class RerankerConfig:
    bge_reranker_large: str  # 本地模型路径
    bge_reranker_device: str  # 模型仓库标识
    bge_reranker_fp16: bool  # 是否开启半精度（1=True/0=False）
    # M8：硅基流动 API 模式（api 模式下无需本地模型，rerank 走硅基流动 /rerank 接口）
    rerank_mode: str  # local（默认，与之前完全一致）| api
    siliconflow_api_key: str  # 硅基流动 API Key（api 模式必填）
    siliconflow_base_url: str  # 硅基流动 OpenAI 兼容基础地址（默认 https://api.siliconflow.cn/v1）
    siliconflow_rerank_model: str  # 硅基流动 rerank 模型（默认 BAAI/bge-reranker-v2-m3）


# 实例化配置对象，和原代码lm_config风格保持一致
reranker_config = RerankerConfig(
    bge_reranker_large=settings.bge_reranker_large,
    bge_reranker_device=settings.bge_reranker_device,
    # 特殊处理：将settings中的1/0转为布尔值，兼容常见的数字/字符串格式
    bge_reranker_fp16=settings.bge_reranker_fp16 in ("1", "True", "true", 1),
    # M8：api 模式配置直接透传 settings 字符串
    rerank_mode=settings.rerank_mode,
    siliconflow_api_key=settings.siliconflow_api_key,
    siliconflow_base_url=settings.siliconflow_base_url,
    siliconflow_rerank_model=settings.siliconflow_rerank_model,
)
