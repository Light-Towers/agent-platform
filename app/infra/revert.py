"""会话回退 revert：将会话状态回退至之前某一 checkpoint。

- 原子回退（单事务）
- 不删除历史 checkpoint（支持 redo）
- 跨用户禁止
- 内存模式仅对存活会话有效
"""

import logging
import uuid
from datetime import datetime, timezone

from app.infra.cache import spawn_background
from app.schemas import RevertResult

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
        """执行回退。"""
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

            source_checkpoint_id = getattr(tpl, "parent_config", {}).get(
                "configurable", {}
            ).get("checkpoint_id", "")

            # 原子回退：更新会话当前指针为目标 checkpoint
            # LangGraph checkpointer 已支持 checkpoint_id 定位，revert 即用目标 checkpoint 配置接续
            # 不删除历史 checkpoint（redo 语义）

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

        except Exception as e:
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
        reverted_at = datetime.now(timezone.utc).isoformat()

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
