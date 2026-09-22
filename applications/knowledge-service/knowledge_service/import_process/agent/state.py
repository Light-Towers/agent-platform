import copy
from typing import TypedDict

from knowledge_service.core.logger import logger


class ImportGraphState(TypedDict):
    """
    图的状态定义，包含所有节点产生和消费的数据字段。
    TypedDict 让我们在代码中能有自动补全和类型检查。
    使用字典式访问（如state["session_id"]、state.get("embedding_chunks")）
    """

    task_id: str  # 任务唯一ID，用于追踪日志

    # --- 流程控制标记 ---
    is_md_read_enabled: bool  # 是否启用 Markdown 读取路径
    is_pdf_read_enabled: bool  # 是否启用 PDF 读取路径

    # --- 切块相关 ---
    is_normal_split_enabled: bool
    is_silicon_flow_api_enabled: bool
    is_advanced_split_enabled: bool
    is_vllm_enabled: bool

    # --- 路径相关 ---
    local_dir: str  # 当前工作目录或输出目录
    local_file_path: str  # 原始输入文件路径
    file_title: str  # 文件标题（文件名去后缀）
    pdf_path: str  # PDF 文件路径 (如果输入是PDF)
    md_path: str  # Markdown 文件路径 (转换后或直接输入的)
    split_path: str  # 分块后的文件路径
    embeddings_path: str  # 向量数据库文件路径

    # --- 内容数据 ---
    md_content: str  # Markdown 的全文内容
    chunks: list  # 切片后的文本列表，包含 metadata
    item_name: str  # 识别出的主体名称 (如: "万用表")，用于增强检索

    # --- 数据库相关 ---
    embeddings_content: list  # 包含向量数据的列表，准备写入 Milvus

    # --- 可插拔开关（08+16 通用化） ---
    # item_name NER 节点可插拔：默认 True 保持向后兼容；False 时图跳过 node_item_name_recognition
    enable_item_name_recognition: bool

    # --- Metadata 参数化（08+16 通用化） ---
    # 知识生命周期与多租户隔离入参，由 /upload 路由透传，非硬编码
    knowledge_id: str  # 知识条目唯一标识（生命周期审计依据）
    scope_type: str  # PUBLIC | PRIVATE（多知识空间隔离）
    tenant_id: str  # 租户 ID（多租户隔离，ACL 前置 INV-8）
    tenant_type: str  # 租户类型（如 enterprise/personal，预留）
    effective_from: str  # 生效起始日（ISO yyyy-MM-dd，生命周期校验）
    effective_to: str  # 生效截止日（ISO yyyy-MM-dd，生命周期校验）
    version: str  # 知识版本号（如 v1，变更追溯）
    authority: str  # 发布授权方（生命周期校验，缺则不得 PUBLISHED）
    status: str  # 生命周期状态：DRAFT/REVIEWING/PUBLISHED/EXPIRED/REVOKED/SUPERSEDED
    constraint_kind: str  # 约束类型（如 free/commercial，预留）
    exhibition_id: str  # 会展 ID（生命周期校验，通用知识库可设 general）
    venue_id: str  # 场馆 ID（生命周期校验，通用知识库可设 general）


# 建议定一个初始化对象，方便后续使用
# 定义图状态的默认初始值
graph_default_state: ImportGraphState = {
    "task_id": "",
    "is_pdf_read_enabled": False,
    "is_md_read_enabled": False,
    "is_normal_split_enabled": True,
    "is_silicon_flow_api_enabled": True,
    "is_advanced_split_enabled": False,
    "is_vllm_enabled": False,
    "local_dir": "",
    "local_file_path": "",
    "pdf_path": "",
    "md_path": "",
    "file_title": "",
    "split_path": "",
    "embeddings_path": "",
    "md_content": "",
    "chunks": [],
    "item_name": "",
    "embeddings_content": [],
    # 可插拔开关：默认启用，保持既有部署行为不变
    "enable_item_name_recognition": True,
    # Metadata 默认值：status 默认 DRAFT（未发布不进生产检索）
    "knowledge_id": "",
    "scope_type": "PRIVATE",
    "tenant_id": "",
    "tenant_type": "",
    "effective_from": "",
    "effective_to": "",
    "version": "",
    "authority": "",
    "status": "DRAFT",
    "constraint_kind": "",
    "exhibition_id": "",
    "venue_id": "",
}


def create_default_state(**overrides) -> ImportGraphState:
    """
    创建默认状态，支持覆盖

    Args:
        **overrides: 要覆盖的字段（关键字参数解包）

    Returns:
        新的状态实例

    Examples:
        state = create_default_state(task_id="task_001", local_file_path="doc.pdf")
    """

    # 默认状态
    state = copy.deepcopy(graph_default_state)
    # 用 overrides 覆盖
    state.update(overrides)
    # 返回创建好的状态字典实例
    return state


def get_default_state() -> ImportGraphState:
    """
    返回一个新的状态实例，避免全局变量污染
    """
    return copy.deepcopy(graph_default_state)


if __name__ == "__main__":
    """
    测试
    """
    # 创建默认状态
    state = create_default_state(local_file_path="万用表RS-12的使用.pdf")
    logger.info(state)
