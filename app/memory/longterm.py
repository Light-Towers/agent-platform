"""长期记忆：pgvector 语义召回 + 后台异步沉淀（兼容门面）。

实现统一收口到内核 ``agent_core.memory.vector_backend.PgVectorMemoryBackend``
（app 的备选向量后端），并由 app 层类型感知读写扩展（优化 H）。

隔离模型（优化 G）：``workspace_id`` 是长期记忆的隔离主键（跨会话流动、不同空间隔离）。
- 降级路径（无 DB / 内核后端）：``workspace_id`` 透传为内核 ``recall/remember`` 的
  ``user_id`` 形参位，内核表结构与其余维度不变，零侵入。
- 类型增强路径（优化 H）：``workspace_id`` 复用为 memories 表 user_id 列值，并额外写入
  ``memory_type``/``importance`` 元数据，recall 按类型加权融合。

注意：内核 PgVectorMemoryBackend 使用独立 asyncpg 连接池（与 app 的 psycopg 池隔离），
降级路径调用时统一传 ``pool=None``，由内核自建/复用池；类型增强路径使用 app psycopg 池。
"""

import json
import logging

from agent_core.memory.typed import semantic_memory_typed_enabled

from app.config import get_settings
from app.memory import memory_backend as _mb

logger = logging.getLogger(__name__)

_MEMORY_TYPES = ("episodic", "semantic", "procedural")

# 抽取系统提示：要求 LLM 产出结构化事实 JSON 数组（优化 H, D1 抽取不存原文）
# 注意：提示词内含 JSON 示例花括号，故用 %-格式化（而非 .format），避免 KeyError。
_EXTRACT_PROMPT = (
    "你是长期记忆抽取器。从一轮问答中提取对用户未来有用的长期记忆事实。\n"
    "每条事实归类为以下一种类型：\n"
    "  - episodic：特定发生过的事（含时间/事件/结果）\n"
    "  - semantic：用户稳定偏好/人设/事实（跨会话复用）\n"
    "  - procedural：该怎么做某事的方法论/指令\n"
    "仅输出 JSON 数组，元素形如 {\"type\":\"semantic\",\"importance\":0.8,"
    "\"fact\":\"用户是财务，偏好简洁报表\"}。importance 为 0~1 重要性。\n"
    "若无有价值事实，输出 []\n"
    "不要输出原文寒暄，不要包含 PII 原文，只抽取可复用结论。\n"
    "问题：%(question)s\n回答：%(answer)s"
)


async def extract_memory_facts(llm, question: str, answer: str) -> list[dict]:
    """用 LLM 从问答中抽取结构化记忆事实（优化 H, D1）。

    返回 [{\"type\":..., \"importance\":float, \"fact\":str}, ...]。
    失败时返回 []，绝不抛出（记忆抽取是旁路，不应阻断主链路）。
    """
    if llm is None:
        return []
    try:
        prompt = _EXTRACT_PROMPT % {"question": question, "answer": answer}
        resp = await llm.ainvoke(prompt)
        text = getattr(resp, "content", resp) if not isinstance(resp, str) else resp
        text = text.strip()
        if text.startswith("```"):
            text = text.split("```", 2)[1]
            if text.startswith("json"):
                text = text[4:]
        data = json.loads(text)
        if not isinstance(data, list):
            return []
        out = []
        for item in data:
            if not isinstance(item, dict):
                continue
            t = item.get("type", "semantic")
            if t not in _MEMORY_TYPES:
                t = "semantic"
            imp = max(0.0, min(1.0, float(item.get("importance", 0.5))))
            fact = (item.get("fact") or "").strip()
            if fact:
                out.append({"type": t, "importance": imp, "fact": fact})
        return out
    except Exception:
        logger.exception("记忆事实抽取失败，返回空（不阻断主链路）")
        return []


async def recall(pool, workspace_id: str, question: str, k: int = 3) -> list[str]:
    # ADR-0004 阶段3：总开关由 SEMANTIC_MEMORY_TYPED 控制（与内核 typed 语义统一）。
    # 开启 → 走内核 typed 加权/平权召回（仍用 app psycopg 池，遵守 ADR-0003）；
    # 关闭或内存模式 → 退化内核后端平权召回（pool=None 由内核自建池）。
    if pool is not None and semantic_memory_typed_enabled():
        try:
            return await _mb.recall_typed(pool, workspace_id, question, k=k)
        except Exception:
            logger.exception("类型感知召回失败，降级内核/空")
    # 降级路径：内核后端（pool=None，内核自建 asyncpg 池）
    backend = _mb.get_default_backend()
    if backend is None:
        return []
    try:
        return await backend.recall(pool=None, user_id=workspace_id, question=question, k=k)
    except Exception:
        logger.exception("长期记忆召回失败，降级为空")
        return []


async def remember(
    pool,
    workspace_id: str,
    content: str,
    facts: list[dict] | None = None,
) -> None:
    """沉淀记忆（优化 H）。

    - 若 ``facts`` 提供（已由调用方经 ``extract_memory_facts`` 抽取），逐条写入带类型/
      重要性的结构化事实（D1 抽取不存原文）；
    - 否则退化：存整条原文（保持优化 G 之前行为，兼容 memory_extraction_enabled=False）。
    """
    if facts:
        if pool is not None:
            for f in facts:
                try:
                    await _mb.remember_fact(
                        pool, workspace_id, f["fact"], f.get("type", "semantic"),
                        f.get("importance", 0.5),
                    )
                except Exception:
                    logger.exception("结构化记忆写入失败，跳过该条")
        else:
            # 无池（内存模式）无法落库，静默跳过
            logger.debug("内存模式：跳过结构化记忆落库")
        return
    # 退化路径：整条原文
    if pool is not None and semantic_memory_typed_enabled():
        # ADR-0004 阶段3：typed 开关开启时，原文也落入 typed 表（semantic 类型），
        # 保证下一轮 typed recall 能命中（D1 抽取未开启时仍可用整条记忆）。
        try:
            await _mb.remember_fact(
                pool, workspace_id, content, memory_type="semantic", importance=0.5,
            )
        except Exception:
            logger.exception("typed 退化写入失败，跳过")
        return
    # 旧行为：内核后端平权存原文（内存模式或 typed 关闭）
    backend = _mb.get_default_backend()
    if backend is None:
        return
    backend.remember(pool=None, user_id=workspace_id, content=content)


# ADR-0004 阶段3：巩固/遗忘调度钩子（typed 闭环最后一块）
# 不在每条对话后都跑 consolidate（开销），用模块级计数器按频率触发。
_CONSOLIDATE_EVERY = 5  # 每 5 轮对话触发一次惰性遗忘
_consolidate_counter = 0


async def maybe_consolidate(pool, workspace_id: str) -> int:
    """低频触发 typed 巩固/遗忘（旁路，失败不阻断，返回淘汰条数）。

    - 仅当 ``SEMANTIC_MEMORY_TYPED`` 开启且 pool 存在时生效；
    - 内部惰性淘汰 importance 低于阈值且超过 30 天的低价值记忆；
    - 不抛错，异常吞掉（记忆维护是增强项，不应影响主链路）。
    """
    global _consolidate_counter
    if pool is None or not semantic_memory_typed_enabled():
        return 0
    _consolidate_counter += 1
    if _consolidate_counter % _CONSOLIDATE_EVERY != 0:
        return 0
    try:
        threshold = get_settings().memory_forget_threshold
        return await _mb.consolidate_memories(pool, workspace_id, forget_threshold=threshold)
    except Exception:
        logger.exception("记忆巩固/遗忘失败，跳过（不阻断主链路）")
        return 0
