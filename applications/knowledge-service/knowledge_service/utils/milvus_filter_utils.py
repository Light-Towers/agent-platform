"""
Milvus 检索过滤表达式构造工具（08+16 通用化）。

统一构造 item_name + tenant_id + scope_type 复合过滤表达式，
供 node_search_embedding / node_search_embedding_hyde / 检索压测档复用，
杜绝各节点各自拼字符串导致多租户隔离口径不一致（INV-8 ACL 前置）。
"""

from typing import Iterable, Optional

from knowledge_service.utils.escape_milvus_string_utils import escape_milvus_string
from knowledge_service.utils.item_name_normalize_utils import normalize_item_name


def build_item_name_filter(item_names: Optional[Iterable[str]]) -> Optional[str]:
    """
    构造 item_name in [...] 过滤表达式。
    :param item_names: 商品名列表（空或 None 返回 None）
    :return: Milvus filter 表达式或 None
    """
    if not item_names:
        return None
    quoted = ", ".join(f'"{escape_milvus_string(normalize_item_name(v))}"' for v in item_names if v)
    if not quoted:
        return None
    return f"item_name in [{quoted}]"


def build_tenant_filter(tenant_id: Optional[str], scope_type: Optional[str] = None) -> Optional[str]:
    """
    构造 tenant_id + scope_type 多租户隔离过滤表达式（ACL 前置，INV-8）。
    :param tenant_id: 租户 ID（空则不做租户隔离）
    :param scope_type: PUBLIC | PRIVATE（空则不做 scope 过滤）
    :return: Milvus filter 表达式片段或 None
    """
    parts = []
    if tenant_id:
        parts.append(f'tenant_id == "{escape_milvus_string(tenant_id)}"')
    if scope_type:
        parts.append(f'scope_type == "{escape_milvus_string(scope_type)}"')
    if not parts:
        return None
    return " and ".join(parts)


def build_knowledge_filter(knowledge_id: Optional[str]) -> Optional[str]:
    """
    构造 knowledge_id 知识库过滤表达式（v2 多知识库，plan-knowledge-base-model）。
    :param knowledge_id: 知识库 ID（空/None = 不做分库过滤，即全部知识库；
        老数据 knowledge_id 为空串，选库模式天然不召回它们——归属宁可不可见）
    :return: Milvus filter 表达式片段或 None
    """
    if not knowledge_id:
        return None
    return f'knowledge_id == "{escape_milvus_string(knowledge_id)}"'


def build_status_filter() -> str:
    """v3 软删除过滤：排除 status=REVOKED 的切片（plan-kb-delete-and-management P2）。

    用 != 而非 == active：老数据 status 为空/未设时仍可召回（重灌前兼容），只有显式
    REVOKED 被排除。两侧（KS 检索 / 平台 DocumentStore）口径必须一致。
    """
    return 'status != "REVOKED"'


def build_retrieval_filter(
    item_names: Optional[Iterable[str]] = None,
    tenant_id: Optional[str] = None,
    scope_type: Optional[str] = None,
    knowledge_id: Optional[str] = None,
) -> Optional[str]:
    """
    构造完整检索过滤表达式：item_name + tenant_id + scope_type + knowledge_id 复合过滤。
    各子句用 and 连接。v3 起至少含 status 软删除过滤，故永不返回 None。
    """
    clauses = [build_status_filter()]  # v3 软删除：所有检索都排除 REVOKED
    item_expr = build_item_name_filter(item_names)
    if item_expr:
        clauses.append(item_expr)
    tenant_expr = build_tenant_filter(tenant_id, scope_type)
    if tenant_expr:
        clauses.append(tenant_expr)
    knowledge_expr = build_knowledge_filter(knowledge_id)
    if knowledge_expr:
        clauses.append(knowledge_expr)
    return " and ".join(clauses)
