# 导入核心依赖（和其他配置类共用，只需导入一次）
import os
import re
from dataclasses import dataclass

from app.core.config import settings
from app.conf.embedding_config import embedding_config


# ===================== 其他配置类（LLM/Embedding）可放在上方，保持原有代码不变 =====================
# ... 你的LLMConfig、EmbeddingConfig代码 ...


def sanitize_model_name(model_name: str) -> str:
    """
    将 embedding 模型标识转换为集合名可用的后缀。

    例：
        "BAAI/bge-m3"  -> "bge_m3"
        "BAAI/bge-reranker-v2-m3" -> "bge_reranker_v2_m3"
        "" / None      -> "unknown_model"

    规则：取 '/' 之后的最后一段，转小写，非字母数字下划线统一替换为 '_'。
    注意：Milvus 集合名只允许字母 / 数字 / 下划线，必须剔除 '-' / '.' 等字符。
    """
    name = (model_name or "").strip()
    if not name:
        return "unknown_model"
    base = name.split("/")[-1]
    return re.sub(r"[^A-Za-z0-9_]", "_", base).lower()


def build_chunks_collection_name(prefix: str, schema_version: str, embedding_model: str) -> str:
    """
    按约定拼装版本化集合名：{prefix}_{schema_version}_{embedding_model}。

    例如：
        prefix="product_manual", schema_version="v1", embedding_model="BAAI/bge-m3"
        -> "product_manual_v1_bge_m3"

    导入侧（node_import_milvus）与检索侧（node_search_embedding / node_search_embedding_hyde）
    必须统一通过 milvus_config.chunks_collection 读取，杜绝两侧各自写死不一致。
    """
    return f"{prefix}_{schema_version}_{sanitize_model_name(embedding_model)}"


# 定义Milvus向量数据库配置类
@dataclass
class MilvusConfig:
    milvus_url: str  # Milvus服务端连接地址
    chunks_collection: str  # 存储切片的集合名称（版本化命名，见 build_chunks_collection_name）
    entity_name_collection: str  # 预留-实体名称集合
    item_name_collection: str  # 存储文档对应实体类的集合名称
    collection_prefix: str  # 集合名前缀（如 product_manual）
    schema_version: str  # 索引 schema 版本（如 v1，schema/切分策略变更即升版）
    chunk_version: str  # chunk 切分策略版本（如 v1-title-aware，随 chunk 元数据写入）
    embedding_model: str  # 向量产出模型标识（如 BAAI/bge-m3，防止混模型污染）


# 默认（版本化）集合名：{prefix}_{schema_version}_{embedding_model}
_default_chunks_collection = build_chunks_collection_name(
    prefix=settings.milvus_collection_prefix,
    schema_version=settings.milvus_schema_version,
    embedding_model=embedding_config.bge_m3,
)

# 实例化Milvus配置对象（和其他配置对象命名风格统一）
# 兼容性：若用户显式设置 CHUNKS_COLLECTION 环境变量（既有部署/既有数据），则优先沿用，
# 未显式设置时默认落到版本化集合名。
milvus_config = MilvusConfig(
    milvus_url=settings.milvus_url,
    chunks_collection=os.getenv("CHUNKS_COLLECTION") or _default_chunks_collection,
    entity_name_collection=settings.entity_name_collection,
    item_name_collection=settings.item_name_collection,
    collection_prefix=settings.milvus_collection_prefix,
    schema_version=settings.milvus_schema_version,
    chunk_version=settings.chunk_version,
    embedding_model=embedding_config.bge_m3,
)
