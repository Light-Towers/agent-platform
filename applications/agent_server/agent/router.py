"""意图路由：LLM 结构化决策，失败时回退确定性启发式。

启发式是评测基线（eval 门禁直接测它），也是 LLM 不可用时的兜底，
必须保持无副作用、可复现。

TD-7：特征词外置到 ``data/route_hints.json``（数据驱动，新增词不改代码）；
LLM 路由为主路径，本词表仅作 LLM 不可用时的兜底。
"""

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

from agent_core.hot_text import load_hot_text

from agent_server.config import get_settings
from agent_server.schemas import Capability

_DATA_PATH = Path(__file__).resolve().parent / "data" / "route_hints.json"
# 路由 system prompt 外置（ADR 00XX）：生产由 ConfigMap volume 挂到 /run/app-prompts，
# 改 CM 即生效不重启；本地 dev/测试用仓库内文件。import 时选一次路径即可
# （挂载路径在容器生命周期内不变），热加载靠 load_hot_text 的 mtime 指纹。
_MOUNTED_PROMPT = Path("/run/app-prompts/router_system.prompt")
_LOCAL_PROMPT = Path(__file__).resolve().parent / "data" / "router_system.prompt"
_PROMPT_PATH = _MOUNTED_PROMPT if _MOUNTED_PROMPT.exists() else _LOCAL_PROMPT
# 文件缺失兜底（同 route_hints 的 _FALLBACK_HINTS 纪律：不因文件缺失启动失败）。
_FALLBACK_ROUTER_PROMPT = (
    "你是路由器。判断用户问题应走哪条能力链路：{capabilities}\n"
    "涉及业务/领域/文档内容的问题优先选 rag 检索本地知识库；纯闲聊才判 direct。"
)

# 代码兜底（数据文件缺失时使用，避免启动失败）
_FALLBACK_HINTS = {
    "sql": ("sql", "数据库", "表里", "表中", "统计", "多少条", "多少笔", "销售额", "订单", "销量", "库存"),
    "search": ("最新", "最近", "新闻", "github", "趋势", "今天", "本周", "发布", "开源项目", "联网"),
    "rag": ("知识库", "文档", "什么是", "解释", "原理", "怎么理解", "wiki", "笔记", "介绍"),
    "mcp": ("调用工具", "运行工具", "执行工具", "调用外部", "mcp", "调用 mcp"),
    "code_execution": ("执行代码", "运行代码", "跑一下代码", "跑这段", "python代码", "代码块", "帮我执行", "sandbox", "沙箱执行", "print("),
}


@lru_cache(maxsize=1)
def _load_hints() -> dict[str, tuple[str, ...]]:
    """加载路由特征词数据（TD-7）。lru_cache 避免每次请求读盘。"""
    try:
        with open(_DATA_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {
            key: tuple(words) for key, words in data.items()
            if key in ("sql", "search", "rag", "mcp", "code_execution") and isinstance(words, list)
        }
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("加载路由特征词失败，使用内置默认值: %s", e)
        return _FALLBACK_HINTS


def _hints(route: str) -> tuple[str, ...]:
    """读取指定路由的特征词元组。"""
    return _load_hints().get(route, ())


class RouteDecision(BaseModel):
    capability: Literal["search", "rag", "sql", "direct", "mcp", "code_execution"] = Field(
        description="应调用的能力：search=联网搜索, rag=本地知识库, sql=数据库查询, direct=直接回答, mcp=外部工具, code_execution=沙箱代码执行"
    )
    sub_query: str = Field(description="传给子能力的关键查询词")
    reason: str = Field(description="一句话路由理由")


def heuristic_route(question: str) -> RouteDecision:
    """确定性关键词路由；优先级 code_execution > mcp > sql > search > rag > direct。"""
    q = question.lower()
    if any(h in q for h in _hints("code_execution")):
        return RouteDecision(capability="code_execution", sub_query=question, reason="命中代码执行特征词")
    if get_settings().mcp_enabled and any(h in q for h in _hints("mcp")):
        return RouteDecision(capability="mcp", sub_query=question, reason="命中外部工具调用特征词")
    if any(h in q for h in _hints("sql")):
        return RouteDecision(capability="sql", sub_query=question, reason="命中数据查询特征词")
    if any(h in q for h in _hints("search")):
        return RouteDecision(capability="search", sub_query=question, reason="命中时效/联网特征词")
    if any(h in q for h in _hints("rag")):
        return RouteDecision(capability="rag", sub_query=question, reason="命中知识库特征词")
    return RouteDecision(capability="direct", sub_query=question, reason="无明确能力特征")


async def decide_route(llm, question: str) -> RouteDecision:
    """LLM 结构化路由；任何异常回退启发式（绝不让路由失败阻塞主链路）。"""
    if llm is None:
        return heuristic_route(question)
    # system prompt 从外置文件读（热加载，改文件不重启）；缺失时用兜底。
    # 不用 str.format（prompt 里可能有字面花括号），用 replace 白名单槽位。
    prompt_template = load_hot_text(_PROMPT_PATH, _FALLBACK_ROUTER_PROMPT)
    try:
        capabilities = "search=联网搜索, rag=本地知识库, sql=数据库查询, direct=直接回答, code_execution=沙箱代码执行"
        if get_settings().mcp_enabled:
            capabilities += ", mcp=调用外部工具"
        system_prompt = prompt_template.replace("{capabilities}", capabilities)
        # method 必须显式指定：langchain-openai 默认走 json_schema，而提供方是否支持该
        # response_format 类型按模型不同（126 现网 DeepSeek 稳定 400、同端点 Qwen 却可用），
        # 失败会被下面的宽 except 吞成"静默回退启发式"。tools 是实测唯一跨模型都合规的形态，
        # 且 tool_choice 要保持默认 auto（Qwen 侧 required 会 400）。
        structured = llm.with_structured_output(RouteDecision, method="function_calling")
        decision = await structured.ainvoke(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question},
            ]
        )
        if isinstance(decision, RouteDecision):
            if decision.capability == "mcp" and not get_settings().mcp_enabled:
                return heuristic_route(question)
            return decision
    except Exception as e:
        logger.warning("LLM 路由决策异常，回退启发式路由: %s", e)
    return heuristic_route(question)


def capability_label(cap: Capability) -> str:
    return {
        "search": "联网搜索",
        "rag": "知识库检索",
        "sql": "数据库查询",
        "direct": "直接回答",
        "mcp": "外部工具",
        "code_execution": "沙箱代码执行",
    }[cap]
