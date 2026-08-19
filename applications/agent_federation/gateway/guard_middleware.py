"""DeepAgent Middleware 封装：输入护栏挂进 agent 栈。

优化 B 要点2：把内核 `guard_input`（PII 脱敏 + prompt injection 检测）从
`app` 侧手动函数调用，升级为 agent_federation 一等横切组件，使 agent_federation 视图的
agent 也默认经过输入护栏，消除双视图安全水位差，并与 TodoList / Rubric 等
middleware 共用 `create_deep_agent(middleware=[...])` 统一挂载点。

注意：`guard_input` 返回 dict（见 agent_core.guardrails.input_guard），
`blocked` 是否拦截由环境变量 `GUARD_BLOCK_INJECTION` 控制（默认 true）；
本中间件只接管「脱敏改写 + 命中拦截时替换入口文本」，不自行决定拦截策略。
"""

from __future__ import annotations

import logging

from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.messages import HumanMessage

from gateway.input_guard import guard_input

logger = logging.getLogger(__name__)


class GuardMiddleware(AgentMiddleware):
    """在 agent 启动前对入口 user 文本做脱敏改写，并检测注入。

    `before_agent` 只跑一次（agent 启动前）；对话式多轮中每条新 human message
    追加后重新 invoke，`before_agent` 会再次处理最新一条 human 文本，因此
    天然覆盖多轮入口。

    原地改写最后一条 HumanMessage.content（下游 model 看到脱敏文本），
    不额外追加消息，避免与 messages reducer 重复。
    """

    def before_agent(self, state, runtime):  # noqa: ANN001 - 与基类签名一致
        messages = state.get("messages") if isinstance(state, dict) else getattr(state, "messages", None)
        if not messages:
            return None

        last = messages[-1]
        if not isinstance(last, HumanMessage):
            return None

        try:
            result = guard_input(last.content)
        except Exception as e:  # 护栏自身失败不应阻断 agent
            logger.warning("[guard] guard_input 失败，跳过脱敏: %s", e)
            return None

        redacted = result.get("redacted_text", last.content)
        if redacted != last.content:
            last.content = redacted
            logger.info("[guard] 已在 deepagent 入口脱敏 PII")

        if result.get("blocked"):
            last.content = "[输入被护栏拦截：检测到疑似 prompt injection]"
            logger.warning("[guard] 入口文本命中 injection，已替换为拦截提示")

        return None
