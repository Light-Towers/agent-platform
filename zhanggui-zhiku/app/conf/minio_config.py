# 导入核心依赖：数据类、统一配置
from dataclasses import dataclass
from app.core.config import settings


# 定义MinIO对象存储服务配置（与LLMConfig风格一致，字段对应.env配置项）
@dataclass
class MinIOConfig:
    endpoint: str  # MinIO服务地址（含http/https和端口）
    access_key: str  # MinIO访问密钥（对应MINIO_ACCESS_KEY）
    secret_key: str  # MinIO秘钥（对应MINIO_SECRET_KEY）
    bucket_name: str  # MinIO默认存储桶名（知识库文件专用）
    minio_img_dir: str  # Minio存储图片的文件夹
    minio_secure: bool  # 是否使用ssl加密 http 还是 https


# 实例化MinIO配置对象，自动从统一配置读取并绑定
minio_config = MinIOConfig(
    endpoint=settings.minio_endpoint,
    access_key=settings.minio_access_key,
    secret_key=settings.minio_secret_key,
    bucket_name=settings.minio_bucket_name,
    minio_img_dir=settings.minio_img_dir,
    minio_secure=settings.minio_secure.strip().lower() in ("1", "true", "yes", "on"),
)
