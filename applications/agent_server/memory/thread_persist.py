"""对话线程历史持久化（Phase 3c）：Planner 路径下 checkpoint 的读/写。

Planner 协议中立（不持有 LangGraph 依赖），对话历史的线程语义由 app 层承担：
- 读：``checkpointer.alist_messages(thread_id)`` → ``PlannerContext.messages``
  （供 compaction / 多轮上下文；与 graph.astream 的 checkpoint 恢复行为等价）；
- 写：执行后把 (question, answer) 一轮追加回 checkpoint（``aget_tuple`` 模板 + ``aput``），
  保持 /history 与 revert 语义不回退（graph 保留为 general_qa Skill，checkpoint 格式同构）。

无 checkpointer（测试/降级）时读写均为空操作，不阻塞主链路。
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage

logger = logging.getLogger(__name__)


async def read_thread_messages(checkpointer: Any, thread_id: str) -> list[Any]:
    """读线程历史消息（BaseMessage 列表，供 PlannerContext.messages）。

    无历史 / 无 checkpointer / 读取异常时返回空列表，不抛错（降级为无上下文执行）。
    """
    if checkpointer is None:
        return []
    try:
        latest = await checkpointer.aget_tuple(
            {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
        )
        if latest is None:
            return []
        # checkpoint 的 channel_values.messages 即线程累积的完整历史（追加写）
        return list(latest.checkpoint.get("channel_values", {}).get("messages", []))
    except Exception as exc:  # noqa: BLE001 - 历史读取失败不影响主链路
        logger.warning("读取线程历史失败（忽略，无上下文执行）: %s", exc)
        return []


async def read_thread_snapshot(checkpointer: Any, thread_id: str) -> dict[str, Any] | None:
    """读上一轮执行的结构化快照（WS-2：供 PlannerContext.last_snapshot）。

    快照存在 checkpoint 的 ``channel_values.task_snapshot``（与 messages 同构的
    通道，按 thread 隔离）；无历史 / 异常时返回 None，不抛错。
    """
    if checkpointer is None:
        return None
    try:
        latest = await checkpointer.aget_tuple(
            {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
        )
        if latest is None:
            return None
        snapshot = latest.checkpoint.get("channel_values", {}).get("task_snapshot")
        return dict(snapshot) if isinstance(snapshot, dict) else None
    except Exception as exc:  # noqa: BLE001 - 快照读取失败不影响主链路
        logger.warning("读取线程快照失败（忽略，无快照执行）: %s", exc)
        return None


async def append_thread(
    checkpointer: Any,
    thread_id: str,
    question: str,
    answer: str,
    snapshot: dict[str, Any] | None = None,
) -> None:
    """把一轮 (user, assistant) 追加写回线程 checkpoint（可选携带本轮 snapshot）。

    以最新 checkpoint 为模板（aget_tuple）改 channel_values.messages 再 aput——
    与 graph.astream 写入的 checkpoint 结构同构；新线程用 empty_checkpoint() 初始化。
    ``snapshot`` 非空时同步写入 ``channel_values.task_snapshot``（覆盖式，只留最新
    一轮），供下一轮 ``read_thread_snapshot`` 读出注入 prompt（WS-2）。
    """
    if checkpointer is None or not answer:
        return
    # checkpoint_ns 为 LangGraph 线程的命名空间键（graph 执行时的默认值为空串）
    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    latest = await checkpointer.aget_tuple(config)
    if latest is not None:
        checkpoint = dict(latest.checkpoint)
        channel_versions = dict(checkpoint.get("channel_versions", {}))
        channel_values = dict(checkpoint.get("channel_values", {}))
        messages = list(channel_values.get("messages", []))
        metadata = dict(latest.metadata or {})
    else:
        from langgraph.checkpoint.base import empty_checkpoint

        checkpoint = empty_checkpoint()
        channel_versions = {}
        channel_values = {}
        messages = []
        metadata = {"source": "input", "step": -1, "writes": None, "score": None}
    # LangGraph saver 的 aput 要求 metadata 含 checkpoint_ns（缺省补空）
    metadata.setdefault("checkpoint_ns", "")
    # 关键：channel_values 由 saver 按 channel_versions + new_versions 落 blob 恢复，
    # 版本号必须推进（缺一则消息通道读不回）。
    messages_version = channel_versions.get("messages", 0) + 1
    channel_versions["messages"] = messages_version
    new_versions = {"messages": messages_version}
    messages.append(HumanMessage(content=question, id=str(uuid4())))
    messages.append(AIMessage(content=answer, id=str(uuid4())))
    channel_values["messages"] = messages
    if snapshot:
        # task_snapshot 通道：覆盖式写最新一轮快照，版本号同样须推进
        snapshot_version = channel_versions.get("task_snapshot", 0) + 1
        channel_versions["task_snapshot"] = snapshot_version
        new_versions["task_snapshot"] = snapshot_version
        channel_values["task_snapshot"] = dict(snapshot)
    checkpoint["channel_values"] = channel_values
    checkpoint["channel_versions"] = channel_versions
    try:
        await checkpointer.aput(config, checkpoint, metadata, new_versions)
    except Exception as exc:  # noqa: BLE001 - 历史写入失败不影响本次回答
        logger.warning("写入线程历史失败（忽略）: %s", exc)
