# -*- coding: utf-8 -*-
"""
知识图谱导入全流程测试：PDF 导入 → Milvus 入库 → KG 导入完整链路。

归并自：`test/05-test-main-graph.py`（原为 `if __name__ == "__main__"` 手测脚本）。

原脚本动作：
1. 用 `doc/hak180产品安全手册.pdf` 构造测试 PDF 路径，`output/` 作为中间文件目录；
2. 校验测试 PDF 是否存在，不存在则打印错误提示并退出；
3. 构造 `ImportGraphState`（task_id / user_id / 文件路径 / 输出目录 / 两个解析开关）；
4. `kb_import_app.stream(..., stream_mode="values")` 流式执行，逐节点打印进度；
5. 打印核心结果指标：MD 内容预览、切片数、是否完成向量化、是否含 chunk_id、KG ID。

改造要点：
- 全栈重型依赖（langgraph / magic-pdf / pymilvus / neo4j）import 下沉到函数体内；
- 用 `ZHIKU_INTEGRATION` 守卫；
- 原脚本用 try/except 把执行异常吞掉后仅打印日志——作为测试用例这会**永远为绿**，
  故移除该吞异常逻辑，让失败真实暴露（这是把手测脚本变成 CI 用例的关键差异）；
- 测试 PDF 缺失时用 `pytest.skip` 而非打印错误，语义为「前置数据缺失」而非「测试失败」。
"""

import os

import pytest

#: 集成测试总开关。
INTEGRATION_ENABLED = bool(os.environ.get("ZHIKU_INTEGRATION", "").strip())

SKIP_REASON = "需要 Milvus / Neo4j / MinIO 全栈与测试 PDF 素材，设置 ZHIKU_INTEGRATION=1 后启用"


@pytest.mark.skipif(not INTEGRATION_ENABLED, reason=SKIP_REASON)
def test_kg_import_full_workflow():
    """全流程测试：验证 PDF 导入 → Milvus 入库 → KG 导入完整链路。"""
    from app.core.logger import logger
    from app.import_process.agent.main_graph import kb_import_app
    from app.import_process.agent.state import ImportGraphState
    from app.utils.path_util import PROJECT_ROOT

    logger.info("===== 开始执行知识图谱导入全流程测试 =====")

    # 1. 构造测试文件路径（复用项目的 doc 目录，和 pdf2md 测试文件一致）
    test_pdf_name = os.path.join("doc", "hak180产品安全手册.pdf")
    test_pdf_path = os.path.join(PROJECT_ROOT, test_pdf_name)

    # 2. 构造输出目录（存放 MD/图片等中间文件）
    test_output_dir = os.path.join(PROJECT_ROOT, "output")
    os.makedirs(test_output_dir, exist_ok=True)  # 不存在则创建

    # 3. 校验测试 PDF 文件是否存在：缺素材属于前置条件不满足，跳过而非失败
    if not os.path.exists(test_pdf_path):
        pytest.skip(f"测试 PDF 文件不存在，路径：{test_pdf_path}（请将测试文件放入项目根目录的 doc 文件夹）")

    # 4. 构造测试状态（贴合实际业务入参）
    test_state = ImportGraphState(
        {
            "task_id": "test_kg_import_workflow_001",  # 测试任务 ID
            "user_id": "test_user",  # 测试用户 ID
            "local_file_path": test_pdf_path,  # 测试 PDF 文件路径
            "local_dir": test_output_dir,  # 中间文件输出目录
            "is_pdf_read_enabled": False,  # PDF 解析开关
            "is_md_read_enabled": False,  # MD 解析开关
        }
    )

    logger.info(f"测试任务启动，PDF 文件路径：{test_pdf_path}")
    logger.info(f"中间文件输出目录：{test_output_dir}")
    logger.info("开始执行全流程节点，依次执行：entry→pdf2md→md_img→split→item_name→embedding→milvus→kg")

    # 5. 执行 LangGraph 全流程（流式执行，打印节点执行进度）
    final_state = None
    for step in kb_import_app.stream(test_state, stream_mode="values"):
        # 打印当前执行完成的节点（流式输出更直观）
        current_node = list(step.keys())[-1] if step else "未知节点"
        logger.info(f"✅ 节点执行完成：{current_node}")
        final_state = step  # 保存最终状态

    # 6. 全流程执行完成，结果预览和核心指标打印
    assert final_state is not None, "全流程未产出任何状态，图可能未执行"

    logger.info("-" * 80)
    logger.info("===== 全流程测试执行成功，核心结果预览 =====")

    # 提取核心结果指标
    chunks = final_state.get("chunks", [])
    chunk_count = len(chunks)
    md_content = final_state.get("md_content", "")[:150]  # MD 内容前 150 字符
    has_embedding = all("dense_vector" in c and "sparse_vector" in c for c in chunks) if chunks else False
    has_chunk_id = all("chunk_id" in c for c in chunks) if chunks else False
    kg_id = final_state.get("kg_id", "未生成")  # KG 导入生成的 ID（按实际业务字段调整）

    # 打印核心指标
    logger.info(f"📄 PDF 转 MD 内容预览（前 150 字符）：{md_content}...")
    logger.info(f"📝 文档切分总切片数：{chunk_count}")
    logger.info(f"🔍 所有切片是否完成向量化：{'是' if has_embedding else '否'}")
    logger.info(f"🗄️  所有切片是否完成 Milvus 入库（含 chunk_id）：{'是' if has_chunk_id else '否'}")
    logger.info(f"🧠 知识图谱导入 ID：{kg_id}")
    logger.info(f"📂 最终状态包含的核心键：{list(final_state.keys())}")
    logger.info("-" * 80)
    logger.info("===== 知识图谱导入全流程测试结束 =====")

    # 7. 核心断言：切分产出非空，且每个切片都完成了向量化与入库标识
    assert chunk_count > 0, "文档切分结果为空"
    assert has_embedding, "存在未完成向量化（缺 dense_vector / sparse_vector）的切片"
    assert has_chunk_id, "存在未完成 Milvus 入库（缺 chunk_id）的切片"
