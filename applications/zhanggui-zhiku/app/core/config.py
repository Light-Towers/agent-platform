# -*- coding: utf-8 -*-
"""
项目统一配置中心（唯一一次加载 .env）

本模块是整个项目的「唯一配置入口」：
1. 在模块导入时**仅此一次**调用 load_dotenv()，避免各模块重复加载 .env；
2. 使用 @dataclass 定义 Settings，所有字段均来自环境变量（os.getenv），并带默认值；
3. 导出单例 `settings` 与 `PROJECT_ROOT`，供全项目 import 使用；
4. 不引入 pydantic-settings，保持零额外依赖、易于离线部署。

字段命名约定：属性名 == 环境变量 key（ENV key），便于维护对照。
布尔/整型字段在需要 bool/int 的原始代码处用辅助函数解析（见下方 _as_bool / _as_int）。
"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# ===================== 唯一一次加载 .env =====================
# 仅在此处调用，确保全项目只有一次 load_dotenv；其余模块直接 from app.core.config import settings
load_dotenv()


def _as_bool(value: str, default: bool = False) -> bool:
    """将环境变量字符串解析为 bool。支持 'True'/'true'/'1'（大小写不敏感）。"""
    if value is None:
        return default
    return str(value).strip().lower() in ("true", "1")


def _as_int(value: str, default: int) -> int:
    """将环境变量字符串解析为 int，解析失败时回退到默认值。"""
    if value is None:
        return default
    try:
        return int(str(value).strip())
    except (ValueError, TypeError):
        return default


@dataclass
class Settings:
    # -------------------------- 应用 --------------------------
    app_host: str = os.getenv("APP_HOST", "0.0.0.0")
    app_port: int = _as_int(os.getenv("APP_PORT"), 8000)
    _project_root_env = os.environ.get("PROJECT_ROOT")
    project_root: Path = Path(_project_root_env) if _project_root_env else Path(__file__).resolve().parent.parent.parent
    cors_origins: str = os.getenv("CORS_ORIGINS", "http://localhost:8000")
    cors_allow_credentials: bool = _as_bool(os.getenv("CORS_ALLOW_CREDENTIALS"), True)

    # -------------------------- 模型 / 路径 --------------------------
    models_dir: str = os.getenv("MODELS_DIR", "./models")
    modelscope_cache: str = os.getenv(
        "MODELSCOPE_CACHE", str(Path(os.getenv("MODELS_DIR", "./models")) / "modelscope_cache")
    )
    hf_home: str = os.getenv("HF_HOME", str(Path(os.getenv("MODELS_DIR", "./models")) / "huggingface_cache"))
    md_root_dir: str = os.getenv("MD_ROOT_DIR", "./temp-files")
    mineru_model_source: str = os.getenv("MINERU_MODEL_SOURCE", "modelscope")
    modelscope_offline: str = os.getenv("MODELSCOPE_OFFLINE", "1")

    # -------------------------- LLM --------------------------
    openai_base_url: str = os.getenv("OPENAI_BASE_URL", "")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    vl_model: str = os.getenv("VL_MODEL", "")
    llm_default_model: str = os.getenv("LLM_DEFAULT_MODEL", "")
    llm_default_temperature: str = os.getenv("LLM_DEFAULT_TEMPERATURE", "0.7")
    item_name_diag: str = os.getenv("ITEM_NAME_DIAG", "1")

    # -------------------------- Embedding --------------------------
    bge_m3_path: str = os.getenv("BGE_M3_PATH", str(Path(os.getenv("MODELS_DIR", "./models")) / "bge-m3"))
    bge_m3: str = os.getenv("BGE_M3", "BAAI/bge-m3")
    bge_device: str = os.getenv("BGE_DEVICE", "cpu")
    bge_fp16: str = os.getenv("BGE_FP16", "0")

    # -------------------------- Milvus --------------------------
    milvus_url: str = os.getenv("MILVUS_URL", "http://localhost:19530")
    chunks_collection: str = os.getenv("CHUNKS_COLLECTION", "kb_chunks")
    entity_name_collection: str = os.getenv("ENTITY_NAME_COLLECTION", "kb_entity_names")
    item_name_collection: str = os.getenv("ITEM_NAME_COLLECTION", "kb_item_names")
    embedding_dim: str = os.getenv("EMBEDDING_DIM", "1024")

    # -------------------------- Milvus 索引生命周期版本化（M2） --------------------------
    # 集合名拼装约定：{collection_prefix}_{schema_version}_{embedding_model}，
    # 例如 product_manual_v1_bge_m3。embedding_model 取 embedding_config.bge_m3 的末段。
    milvus_collection_prefix: str = os.getenv("MILVUS_COLLECTION_PREFIX", "product_manual")
    milvus_schema_version: str = os.getenv("MILVUS_SCHEMA_VERSION", "v1")
    # chunk 切分策略版本：切分逻辑变更即升版，随 chunk 元数据写入（§5.3）
    chunk_version: str = os.getenv("CHUNK_VERSION", "v1-title-aware")

    # -------------------------- Neo4j --------------------------
    neo4j_uri: str = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    neo4j_database: str = os.getenv("NEO4J_DATABASE", "neo4j")
    neo4j_username: str = os.getenv("NEO4J_USERNAME", "neo4j")
    # 安全：密码不提供默认值，部署时必须显式设置。本地开发可用 .env 文件配置。
    neo4j_password: str = os.getenv("NEO4J_PASSWORD", "")

    # -------------------------- Mongo --------------------------
    mongo_url: str = os.getenv("MONGO_URL", "mongodb://localhost:27017")
    mongo_db_name: str = os.getenv("MONGO_DB_NAME", "zhanggui-zhiku")

    # -------------------------- MinIO --------------------------
    minio_endpoint: str = os.getenv("MINIO_ENDPOINT", "localhost:9000")
    # 安全：凭据不提供默认值，部署时必须显式设置。
    minio_access_key: str = os.getenv("MINIO_ACCESS_KEY", "")
    minio_secret_key: str = os.getenv("MINIO_SECRET_KEY", "")
    minio_bucket_name: str = os.getenv("MINIO_BUCKET_NAME", "kb-import-bucket")
    minio_img_dir: str = os.getenv("MINIO_IMG_DIR", "images")
    minio_secure: str = os.getenv("MINIO_SECURE", "False")
    minio_pdf_dir: str = os.getenv("MINIO_PDF_DIR", "pdf_files")

    # -------------------------- Reranker --------------------------
    bge_reranker_large: str = os.getenv(
        "BGE_RERANKER_LARGE", str(Path(os.getenv("MODELS_DIR", "./models")) / "bge-reranker-large")
    )
    bge_reranker_device: str = os.getenv("BGE_RERANKER_DEVICE", "cpu")
    bge_reranker_fp16: str = os.getenv("BGE_RERANKER_FP16", "0")

    # -------------------------- 硅基流动 API 模式（M8） --------------------------
    # 无 GPU / 未安装本地模型（FlagEmbedding、pymilvus.model）时，可把 embedding / rerank
    # 切换到硅基流动 OpenAI 兼容 API：
    #   EMBEDDING_MODE / RERANK_MODE 取值 local（默认，行为与 M7 及之前完全一致）或 api。
    # api 模式下稀疏向量由 app/lm/sparse_vectorizer.py 本地生成（B 路线），保住双路混合检索。
    embedding_mode: str = os.getenv("EMBEDDING_MODE", "local")
    rerank_mode: str = os.getenv("RERANK_MODE", "local")
    siliconflow_api_key: str = os.getenv("SILICONFLOW_API_KEY", "")
    siliconflow_base_url: str = os.getenv("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1")
    siliconflow_embedding_model: str = os.getenv("SILICONFLOW_EMBEDDING_MODEL", "BAAI/bge-m3")
    siliconflow_rerank_model: str = os.getenv("SILICONFLOW_RERANK_MODEL", "BAAI/bge-reranker-v2-m3")

    # -------------------------- MCP / MinerU --------------------------
    mcp_dashscope_base_url: str = os.getenv("MCP_DASHSCOPE_BASE_URL", "")
    mineru_base_url: str = os.getenv("MINERU_BASE_URL", "")
    mineru_api_token: str = os.getenv("MINERU_API_TOKEN", "")

    # -------------------------- 入站安全护栏（M5，方案 §9） --------------------------
    # API Key 鉴权：为空 → 鉴权关闭（向后兼容既有行为）；非空时请求需带
    # X-API-Key 或 Authorization: Bearer <key>。/health、静态页面与 /stream SSE 免鉴权。
    zhanggui_api_key: str = os.getenv("ZHANGUI_API_KEY", "")
    # 入站限流（进程内滑动窗口；数值可 env 覆盖，多副本部署需外置共享存储，见 CHANGELOG）
    zhanggui_rate_limit_per_client: int = _as_int(os.getenv("ZHANGUI_RATE_LIMIT_PER_CLIENT"), 20)
    zhanggui_rate_limit_global: int = _as_int(os.getenv("ZHANGUI_RATE_LIMIT_GLOBAL"), 500)
    zhanggui_rate_limit_window_s: int = _as_int(os.getenv("ZHANGUI_RATE_LIMIT_WINDOW_S"), 60)
    # 输入长度护栏：query 长度上限在 Pydantic 层强制（512）；历史轮数 / 请求体大小可配置
    zhanggui_max_history_rounds: int = _as_int(os.getenv("ZHANGUI_MAX_HISTORY_ROUNDS"), 20)
    zhanggui_max_body_bytes: int = _as_int(os.getenv("ZHANGUI_MAX_BODY_BYTES"), 65536)

    # -------------------------- 导入：图片摘要（可选增强） --------------------------
    # 图片摘要需多模态（VL）模型；缺省关闭：无 VL 能力时跳过摘要（图片标题用默认值
    # "图片描述"），避免不可用/收费的 VL 模型拖慢或阻塞导入主链路（正文检索不依赖摘要）。
    img_summary_enabled: bool = os.getenv("IMG_SUMMARY_ENABLED", "").lower() in ("1", "true", "yes", "on")

    # -------------------------- 日志 --------------------------
    log_console_enable: str = os.getenv("LOG_CONSOLE_ENABLE", "True")
    log_file_enable: str = os.getenv("LOG_FILE_ENABLE", "True")
    log_console_level: str = os.getenv("LOG_CONSOLE_LEVEL", "INFO")
    log_file_level: str = os.getenv("LOG_FILE_LEVEL", "INFO")
    log_file_retention: str = os.getenv("LOG_FILE_RETENTION", "7 days")


# 全局单例：所有模块统一从此处读取配置
settings = Settings()


def validate_credentials() -> list[str]:
    """检查必要凭据是否已配置。

    返回缺失凭据列表。调用方（如应用启动时）可根据返回结果决定是否 fail-fast。
    本地开发环境可忽略警告，生产部署必须确保凭据已设置。
    """
    missing = []
    if not settings.neo4j_password:
        missing.append("NEO4J_PASSWORD")
    if not settings.minio_access_key:
        missing.append("MINIO_ACCESS_KEY")
    if not settings.minio_secret_key:
        missing.append("MINIO_SECRET_KEY")
    return missing

# 项目根目录（供全项目统一使用，避免各模块自行推导）
PROJECT_ROOT: Path = settings.project_root
