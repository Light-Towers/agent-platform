"""长期记忆：pgvector 语义召回 + 后台异步沉淀（兼容门面）。

实现统一收口到内核 ``agent_core.memory.typed``（经 ``memory_backend`` 门面），
typed PG 栈为唯一持久化记忆路径（Critical#3 收口：无池时不再退化无作用域的
内核后端，直接返回空/跳过，避免跨租户泄漏）。

隔离模型（优化 G + tenant）：复合隔离键 ``(tenant_id, workspace_id)``，
``workspace_id`` 复用为 memories 表 user_id 列值（跨会话流动、不同空间隔离），
并额外写入 ``memory_type``/``importance`` 元数据，recall 按类型加权融合。

开关语义（WS-1 收口）：本模块不设栈开关，读写与巩固统一按池存在性判定；
``SEMANTIC_MEMORY_TYPED`` 仅在内核控制召回是否加权融合，记忆总开关为
``SEMANTIC_MEMORY_ENABLED``（由调用方门控）。
"""

import json
import logging

from agent_server.config import get_settings
from agent_server.memory import memory_backend as _mb

logger = logging.getLogger(__name__)

_MEMORY_TYPES = ("episodic", "semantic", "procedural")

# 抽取系统提示：要求 LLM 产出结构化事实 JSON 数组（优化 H, D1 抽取不存原文）
# TD-8：示例泛化为中性模板，不内嵌具体职业/偏好（避免引导模型偏向特定偏好）。
# 注意：提示词内含 JSON 示例花括号，故用 %-格式化（而非 .format），避免 KeyError。
_EXTRACT_PROMPT = (
    "你是长期记忆抽取器。从一轮问答中提取对用户未来有用的长期记忆事实。\n"
    "每条事实归类为以下一种类型：\n"
    "  - episodic：特定发生过的事（含时间/事件/结果）\n"
    "  - semantic：用户稳定偏好/人设/事实（跨会话复用）\n"
    "  - procedural：该怎么做某事的方法论/指令\n"
    "仅输出 JSON 数组，元素形如 {\"type\":\"semantic\",\"importance\":0.8,"
    "\"fact\":\"<用户偏好或事实的中性描述>\"}。importance 为 0~1 重要性。\n"
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


async def recall(pool, workspace_id: str, question: str, k: int = 3, tenant_id: str = "default") -> list[str]:
    # WS-1 语义收口（Warning#7）：本模块不设栈开关——有池即走 tenant-scoped typed PG 路径
    # （仍用 app psycopg 池，遵守 ADR-0003）。``SEMANTIC_MEMORY_TYPED`` 只在内核控制
    # 召回加权融合（关闭退化为平权），不控制是否使用 typed 栈；记忆总开关为
    # ``SEMANTIC_MEMORY_ENABLED``（由调用方门控）。
    if pool is not None:
        try:
            return await _mb.recall_typed(pool, workspace_id, question, k=k, tenant_id=tenant_id)
        except Exception:
            logger.exception("类型感知召回失败，降级内核/空")
    # 无 pool 时没有持久化记忆；DB 模式统一经 tenant-scoped typed PG 路径。
    return []


async def remember(
    pool,
    workspace_id: str,
    content: str,
    facts: list[dict] | None = None,
    tenant_id: str = "default",
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
                        f.get("importance", 0.5), tenant_id=tenant_id,
                    )
                except Exception:
                    logger.exception("结构化记忆写入失败，跳过该条")
        else:
            # 无池（内存模式）无法落库，静默跳过
            logger.debug("内存模式：跳过结构化记忆落库")
        return
    # 退化路径：整条原文
    if pool is not None:
        # typed 表为唯一持久化记忆栈：原文退化写入也落 typed 表（semantic 类型），
        # 保证下一轮 typed recall 能命中（D1 抽取未开启时仍可用整条记忆）。
        # 不受 SEMANTIC_MEMORY_TYPED 门控——与 recall() 读写对称（WS-1 语义收口）。
        try:
            await _mb.remember_fact(
                pool, workspace_id, content, memory_type="semantic", importance=0.5,
                tenant_id=tenant_id,
            )
        except Exception:
            logger.exception("typed 退化写入失败，跳过")
        return
    # 无 pool 时没有持久化记忆；DB 模式统一经 tenant-scoped typed PG 路径。


# ADR-0004 阶段3：巩固/遗忘调度钩子（typed 闭环最后一块）
# 不在每条对话后都跑 consolidate（开销），用模块级计数器按频率触发。
_CONSOLIDATE_EVERY = 5  # 每 5 轮对话触发一次惰性遗忘
_consolidate_counter = 0


async def maybe_consolidate(pool, workspace_id: str, tenant_id: str = "default") -> int:
    """低频触发 typed 巩固/遗忘（旁路，失败不阻断，返回淘汰条数）。

    - 仅当 pool 存在时生效（巩固对象是 typed 表，无池即无持久化记忆）；
      WS-1 语义收口：不受 ``SEMANTIC_MEMORY_TYPED`` 门控——该开关只在内核控制
      召回加权融合，读写与巩固统一按池存在性判定，保持栈内语义一致；
    - 内部惰性淘汰 importance 低于阈值且超过老化天数（默认 30 天，
      可由 ``MEMORY_FORGET_AGE_DAYS`` 配置，TD-6）的低价值记忆；
    - 不抛错，异常吞掉（记忆维护是增强项，不应影响主链路）。
    """
    global _consolidate_counter
    if pool is None:
        return 0
    _consolidate_counter += 1
    if _consolidate_counter % _CONSOLIDATE_EVERY != 0:
        return 0
    try:
        threshold = get_settings().memory_forget_threshold
        return await _mb.consolidate_memories(pool, workspace_id, forget_threshold=threshold, tenant_id=tenant_id)
    except Exception:
        logger.exception("记忆巩固/遗忘失败，跳过（不阻断主链路）")
        return 0
