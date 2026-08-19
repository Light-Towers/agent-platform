# 导入核心依赖：数据类、统一配置
from dataclasses import dataclass
from app.core.config import settings


# 定义mcp的服务配置
@dataclass
class McpConfig:
    mcp_base_url: str
    api_key: str


mcp_config = McpConfig(mcp_base_url=settings.mcp_dashscope_base_url, api_key=settings.openai_api_key)
