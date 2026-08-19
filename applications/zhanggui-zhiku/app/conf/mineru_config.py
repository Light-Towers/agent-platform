# 导入核心依赖：数据类、统一配置
from dataclasses import dataclass
from app.core.config import settings


# 定义minerU服务配置
@dataclass
class MineruConfig:
    base_url: str
    api_key: str


mineru_config = MineruConfig(base_url=settings.mineru_base_url, api_key=settings.mineru_api_token)
