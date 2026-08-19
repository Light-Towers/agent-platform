"""Supervisor 图状态定义。

AgentState 采用 Pydantic ``BaseModel``（而非 TypedDict），以获得：
- 字段默认值（替代 TypedDict ``total=False`` 的可选语义），节点局部返回
  部分字段时不再因缺字段而校验失败；
- 明确的 schema 契约，便于序列化/校验与未来分层持久化。

唯一 reducer 字段 ``messages`` 保留 ``Annotated[list, add_messages]`` 注解，
LangGraph 能从 Pydantic 字段的 Annotated 元数据中识别 channel reducer。
``model_config.arbitrary_types_allowed`` 允许 messages 承载 LangChain
BaseMessage 对象（Pydantic 不强制校验其元素类型）。
"""

from typing import Annotated, Any, Literal

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, ConfigDict

# 路由分支键：与 graph.py 的 add_conditional_edges 分支键集合一一对应。
# 枚举化可在节点写入非法 route 时立即由 Pydantic 校验拦截，
# 避免脏值穿透到 synthesize 才在条件路由处崩溃。
Route = Literal["search", "rag", "sql", "direct", "mcp", "blocked"]


class AgentState(BaseModel):
    """Supervisor 图状态：route -> (search|rag|sql|direct|mcp) -> synthesize。"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    # 对话历史（checkpoint 持久化），add_messages reducer 累加
    messages: Annotated[list[BaseMessage], add_messages] = []
    question: str = ""
    user_id: str = "default"
    workspace_id: str = "default"
    route: Route = "direct"
    sub_query: str = ""
    route_reason: str = ""
    memory_notes: list[str] = []
    evidence: list[str] = []
    answer: str = ""
    iterations: int = 0
    mcp_server: str = ""
    mcp_tool: str = ""
    mcp_params: dict[str, Any] = {}


def _validate_state(state: AgentState) -> None:
    """节点入口运行期断言：必填字段 + 枚举已在类型层约束。

    优化 A 要点2：AgentState 已 Pydantic 化且 route 已枚举化，
    此处做轻量入口校验，脏 state 在节点边界即时暴露，
    避免「脏数据穿透到 synthesize」类偶发 bug。
    """
    if not state.question:
        raise ValueError("AgentState.question 不可为空")
