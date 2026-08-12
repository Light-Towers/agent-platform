# 导入核心依赖：数据类、统一配置
from dataclasses import dataclass
from app.core.config import settings


# 定义minerU服务配置
@dataclass
class LLMConfig:
    base_url: str
    api_key: str
    lv_model: str
    llm_model: str
    llm_temperature: float


lm_config = LLMConfig(
    base_url=settings.openai_base_url,
    api_key=settings.openai_api_key,
    lv_model=settings.vl_model,
    llm_model=settings.llm_default_model,
    llm_temperature=float(settings.llm_default_temperature),
)
