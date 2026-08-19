# -*- coding: utf-8 -*-
"""
知识库导入图（kb_import_app）的流式执行与图结构打印。

归并自：`test/04-test_graph_flow.py`（原为模块级直接跑图的手测脚本）。

原脚本动作：
1. `create_default_state(local_file_path="万用表RS-12的使用.pdf")` 构造初始状态；
2. `kb_import_app.stream(initial_state)` 流式执行，逐节点打印节点名，记录最终状态；
3. `json.dumps` 格式化输出最终状态；
4. `kb_import_app.get_graph().print_ascii()` 打印图结构（依赖 grandalf）。

改造要点：
- 依赖 langchain / langgraph / magic-pdf / Milvus 全栈，重型 import 全部下沉到
  函数体内，保证无依赖环境下 pytest **收集阶段不报错**；
- 用 `ZHIKU_INTEGRATION` 守卫，未开启时跳过；
- 保留原有执行流程与最终状态打印，仅把「跑完不报错 + 拿到最终状态」变成断言。
"""

import json
import os

import pytest

#: 集成测试总开关。
INTEGRATION_ENABLED = bool(os.environ.get("ZHIKU_INTEGRATION", "").strip())

SKIP_REASON = "需要 Milvus / MinIO / Mongo 等完整技术栈与模型依赖，设置 ZHIKU_INTEGRATION=1 后启用"


@pytest.mark.skipif(not INTEGRATION_ENABLED, reason=SKIP_REASON)
def test_kb_import_graph_stream_reaches_final_state():
    """导入图可流式执行到底，并产出非空最终状态。"""
    from app.core.logger import logger
    from app.import_process.agent.main_graph import kb_import_app
    from app.import_process.agent.state import create_default_state

    logger.info("===== 开始测试 =====")

    initial_state = create_default_state(local_file_path="万用表RS-12的使用.pdf")
    final_state = None

    # 只输出更最终的状态值（字典形式），不包含节点名称、执行日志、元数据等额外信息
    for event in kb_import_app.stream(initial_state):
        for key, value in event.items():
            logger.info(f"节点: {key}")
            final_state = value

    # 格式化输出最终状态
    logger.info(f"最终状态: \n {json.dumps(final_state, indent=4, ensure_ascii=False)}")
    logger.info("===== 测试结束 =====")

    assert final_state is not None, "导入图未产出任何节点输出，最终状态为空"


@pytest.mark.skipif(not INTEGRATION_ENABLED, reason=SKIP_REASON)
def test_kb_import_graph_structure_printable():
    """导入图的 ASCII 结构可打印（依赖 grandalf）。"""
    from app.core.logger import logger
    from app.import_process.agent.main_graph import kb_import_app

    logger.info("图结构:")
    graph = kb_import_app.get_graph()

    # uv add grandalf
    graph.print_ascii()

    assert graph.nodes, "导入图节点集合为空"
