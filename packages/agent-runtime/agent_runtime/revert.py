"""会话回退 revert：将会话状态回退至之前某一 checkpoint。

- 原子回退（单事务）
- 不删除历史 checkpoint（支持 redo）
- 跨用户/跨租户禁止（G3/T1.2：operator 与 thread 归属比对，FORBIDDEN）
- 内存模式仅对存活会话有效
"""

import logging
import uuid

from agent_core.guardrails.auth import THREAD_ID_PREFIX

from agent_runtime.cache import spawn_background
from agent_runtime.schemas import RevertResult

logger = logging.getLogger(__name__)


class RevertHandler:
    """Checkpoint 级原子回退 + 审计日志。"""

    def __init__(self, checkpointer, pool=None) -> None:
        self._checkpointer = checkpointer
        self._pool = pool
        self._logger = logging.getLogger(__name__)

    async def revert(
        self,
        operator: str,
        session_id: str,
        checkpoint_id: str,
    ) -> RevertResult:
        """执行回退。

        归属断言（G3/T1.2）：``tenant-`` 前缀是**身份命名空间**（``tenant-<principal>``
        整串，见 ``agent_core.guardrails.auth.resolve_thread_identity``），占用该
        前缀却不属于 operator 的 thread 一律 FORBIDDEN——此前 operator 只进审计、
        从不参与判定，``session_router`` 的 FORBIDDEN 分支是死码。无前缀的自定义
        值（开发模式客户端自由命名）放行，与 ``/query`` 在开发模式信任客户端值
        的语义一致。主防线在路由层 ``resolve_thread_id``（认证启用即归一化为
        operator 自身线程），本断言为其纵深防御。
        """
        expected_thread = f"{THREAD_ID_PREFIX}{operator}"
        if session_id.startswith(THREAD_ID_PREFIX) and session_id != expected_thread:
            return RevertResult(
                success=False,
                session_id=session_id,
                checkpoint_id=checkpoint_id,
                context_summary="",
                error="FORBIDDEN",
            )
        source_checkpoint_id = ""
        try:
            # 定位目标 checkpoint
            config = {"configurable": {"thread_id": session_id, "checkpoint_id": checkpoint_id}}
            tpl = await self._checkpointer.aget_tuple(config)
            if tpl is None:
                return RevertResult(
                    success=False,
                    session_id=session_id,
                    checkpoint_id=checkpoint_id,
                    context_summary="",
                    error="CHECKPOINT_NOT_FOUND",
                )

            # parent_config 属性可能存在但值为 None（LangGraph checkpoint tuple 常见情况），
            # 必须先 or {} 再 .get，否则 None.get(...) 抛 AttributeError 被外层吞成 REVERT_FAILED
            source_checkpoint_id = (getattr(tpl, "parent_config", None) or {}).get(
                "configurable", {}
            ).get("checkpoint_id", "")

            # 原子回退：写入「新」checkpoint 作为最新指针，内容为目标 checkpoint 状态。
            # 关键：必须生成新 id，否则 aput 会按 checkpoint["id"] 原地 UPSERT 覆写
            # 目标行（langgraph MemorySaver/PostgresSaver 均以 checkpoint["id"] 为 key），
            # 会话最新指针不变 → success=True 但状态未回退（静默 no-op）。
            new_checkpoint = {**tpl.checkpoint, "id": str(uuid.uuid4())}
            await self._checkpointer.aput(
                {
                    "configurable": {
                        "thread_id": session_id,
                        "checkpoint_id": new_checkpoint["id"],
                        "parent_checkpoint_id": checkpoint_id,
                        "checkpoint_ns": "",
                    }
                },
                new_checkpoint,
                {**tpl.metadata, "reverted_from": checkpoint_id},
                {},
            )

            # 生成上下文摘要
            messages = getattr(tpl, "channel_values", {}).get("messages", [])
            msg_count = len(messages) if messages else 0
            last_question = ""
            if messages:
                last_msg = messages[-1]
                last_question = getattr(last_msg, "content", str(last_msg))[:100]

            context_summary = f"回退至 checkpoint {checkpoint_id[:8]}...（{msg_count} 条消息，最近：{last_question}）"

            # 异步审计
            spawn_background(
                self._write_audit(
                    operator, session_id, source_checkpoint_id, checkpoint_id, "success"
                )
            )

            return RevertResult(
                success=True,
                session_id=session_id,
                checkpoint_id=checkpoint_id,
                context_summary=context_summary,
            )

        except Exception:
            self._logger.warning(
                "revert failed session=%s checkpoint=%s",
                session_id,
                checkpoint_id,
                exc_info=True,
            )
            spawn_background(
                self._write_audit(
                    operator, session_id, source_checkpoint_id, checkpoint_id, "failed"
                )
            )
            return RevertResult(
                success=False,
                session_id=session_id,
                checkpoint_id=checkpoint_id,
                context_summary="",
                error="REVERT_FAILED",
            )

    async def _write_audit(
        self,
        operator: str,
        session_id: str,
        source_checkpoint_id: str,
        target_checkpoint_id: str,
        status: str,
    ) -> None:
        """异步审计日志写入。"""
        revert_id = str(uuid.uuid4())

        if self._pool is not None:
            try:
                async with self._pool.connection() as conn:
                    await conn.execute(
                        "INSERT INTO revert_audit "
                        "(revert_id, operator, session_id, source_checkpoint_id, "
                        "target_checkpoint_id, reverted_at, status) "
                        "VALUES (%s, %s, %s, %s, %s, now(), %s)",
                        (
                            revert_id,
                            operator,
                            session_id,
                            source_checkpoint_id,
                            target_checkpoint_id,
                            status,
                        ),
                    )
            except Exception:
                self._logger.warning("revert audit write failed", exc_info=True)
        else:
            self._logger.info(
                "revert_audit revert_id=%s operator=%s session=%s source=%s target=%s status=%s",
                revert_id,
                operator,
                session_id,
                source_checkpoint_id,
                target_checkpoint_id,
                status,
            )
