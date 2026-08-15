import time
import sys
from app.utils.task_utils import add_running_task, add_done_task
from app.core.logger import logger
from app.core.tracing import traced_span


def _kg_span_attrs(*args, result=None, **kwargs):
    """retrieval.kg span 动态属性（M4，方案 §8.2 表：entities_n / hits）。

    诚实标注：当前 KG 节点为占位实现（未接 Neo4j，仅 time.sleep(1)），
    entities_n / hits 如实记为 0，不凭空造节点数据。
    """
    return {
        "entities_n": 0,
        "hits": 0,
        "note": "stub node: KG 检索当前为占位实现（未接 Neo4j）",
    }


@traced_span("retrieval.kg", attributes_fn=_kg_span_attrs)
def node_query_kg(state):
    """
    节点功能：在 Neo4j 知识图谱中查询实体关系。
    """
    logger.info("=== node_query_kg 图谱查询处理 ===")
    add_running_task(state["session_id"], sys._getframe().f_code.co_name, state.get("is_stream"))

    time.sleep(1)
    # ...
    add_done_task(state["session_id"], sys._getframe().f_code.co_name, state.get("is_stream"))
