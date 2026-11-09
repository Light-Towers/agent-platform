"""knowledge-service 图边界两条缺陷的行为级回归。

判定面本身已收敛到单一实现 `scripts/lint_graph_state_boundary.py`（进 `make lint`，
覆盖全仓 9 张 StateGraph），正反例见 `tests/governance/test_graph_state_boundary_gate.py`。
本文件只留**这两条修复各自的行为断言**——静态扫描换实现时，这两条仍会守住修复。

背景（同一失效形状的第五、六例）：`StateGraph(SomeState)` 只保留 schema 声明过的键，
未声明的键在图边界被**静默丢弃，不报错、不记日志**。
1. `node_search_embedding_hyde` 按自身 docstring 承诺返回 `hyde_doc`（"返回…假设文档，
   更新会话状态"），但该键不在 `QueryGraphState` ⇒ state 侧永远取不到；
2. `node_item_name_recognition` 的标题兜底读 `state["file_name"]`，而 `file_name` 只是
   `node_entry` 里的局部变量，从未进过 state ⇒ 那条兜底恒取空串，承诺不可达。
"""

from __future__ import annotations

from knowledge_service.import_process.agent.nodes.node_item_name_recognition import step_1_get_inputs
from knowledge_service.query_process.agent.state import QueryGraphState


def test_hyde_doc_is_declared_so_the_node_output_survives_the_boundary() -> None:
    """修复 1：节点出参契约里的 `hyde_doc` 必须声明，否则图边界静默丢弃。

    边界说明：本条证的是"键进了 schema"；`hyde_doc` 在**真图**上被后续消费者读到需要活
    Milvus + LLM（按设计不在 CI 里）。修复前它是节点返回但 schema 未声明，所以 span 侧
    `result.get("hyde_doc")` 拿得到、state 侧永远没有。
    """
    assert "hyde_doc" in QueryGraphState.__annotations__


def test_item_name_title_fallback_reads_a_declared_key() -> None:
    """修复 2：兜底改读已声明的 `local_file_path`（原读 `file_name` 恒取空）。"""
    title, chunks = step_1_get_inputs(
        {
            "file_title": "",
            "local_file_path": "/data/uploads/万用表RS-12.pdf",
            "chunks": [{"title": "t", "content": "c"}],
        }
    )
    assert title == "万用表RS-12.pdf"
    assert len(chunks) == 1


def test_never_written_key_is_no_longer_relied_on() -> None:
    """从未有写入点的键不再被依赖：传了也不生效，兜底落到切片标题（正向用例的反证）。"""
    title, _chunks = step_1_get_inputs(
        {
            "file_title": "",
            "file_name": "不该被读.pdf",
            "chunks": [{"title": "t", "content": "c", "file_title": "切片兜底标题"}],
        }
    )
    assert title == "切片兜底标题"


def test_import_state_still_has_no_file_name_channel() -> None:
    """判据的另一半：`file_name` 确实不属于 schema——若有人把它声明进 state 而不补写入点，
    门禁的"有读无写"登记面会要求当场清理，这里同时钉住当前形状。"""
    from knowledge_service.import_process.agent.state import ImportGraphState

    assert "file_name" not in ImportGraphState.__annotations__
    assert "local_file_path" in ImportGraphState.__annotations__
