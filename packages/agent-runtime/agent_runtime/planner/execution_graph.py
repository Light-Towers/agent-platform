"""动态执行图（Plan-F）：Planner 产出的 Skill 组合计划，Runtime 校验后分层并行执行。

与静态 DAG（``agent_server/agent/graph.py`` 编译期固定拓扑）的区别：ExecutionGraph
由 Planner 在决策期动态构建——节点是 Skill 调用，边是依赖关系（``dependent → dependency``
表示 dependency 须先完成）。``PolicyValidator`` 校验无环 / 深度 / 步数 / 权限后，
``execute_graph`` 按拓扑分层并行执行（同层 ``asyncio.gather``，层间顺序）。

架构契约：Planner 负责「提出计划」（构建 ExecutionGraph），Runtime 负责「验证 + 执行」
（PolicyValidator + execute_graph）——不把执行自由度完全交给 LLM。
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from agent_core.resilience import ErrorClass, classify_exception

from agent_runtime.effect_contract import FailureAction, decide_failure_action
from agent_runtime.forensic import ForensicContext
from agent_runtime.planner.durability import Checkpoint, FencedWriteError
from agent_runtime.planner.protocol import ExecutionSuspended, Plan, StreamEvent
from agent_runtime.trajectory.models import TrajectoryRecord

# 执行级业务重试上限（见 M1.1 重试边界：transport 1–2 < skill 级 2 < 本处 2，禁止叠加）
_NODE_BUSINESS_RETRY_MAX = 2
_NODE_BUSINESS_RETRY_BACKOFF = 0.2
logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from agent_runtime.planner.protocol import PlannerRuntime


def _usage_payload(runtime: PlannerRuntime) -> dict[str, Any]:
    """P2-2：把当前执行的累计 token / 费用带入 status 事件（无执行上下文时为 0）。"""
    ctx = runtime.context
    if ctx is None:
        return {"tokens_used": 0, "cost_used": 0.0}
    return {"tokens_used": ctx.tokens_used, "cost_used": ctx.cost_used}


async def _persist_trajectory(
    runtime: PlannerRuntime, plan: Plan, agent_ctx: Any, exec_ctx: Any
) -> None:
    """P3-1：持久化轨迹 + 触发 post-execution hooks（记忆自动沉淀）。

    trajectory_store 未注入时跳过持久化，但仍创建 record 并触发 hooks
    （使 EpisodicSink 等记忆沉淀不依赖 trajectory_store 的存在）。
    """
    if exec_ctx is None:
        return
    # V3-9: 执行级版本指纹
    _model = getattr(runtime.llm, "model", None) if runtime.llm else None
    forensic_ctx = ForensicContext(
        model=_model,
        planner_version=plan.planner_name or None,
    )
    # V3-3: 序列化 plan 时把 ExecutionGraph 转 dict（供 resume 重建）
    plan_dict = plan.model_dump()
    if plan.graph is not None and hasattr(plan.graph, "to_dict"):
        plan_dict["graph"] = plan.graph.to_dict()
    record = TrajectoryRecord(
        execution_id=exec_ctx.execution_id,
        session_id=plan.session_id or None,
        planner=plan.planner_name or None,
        plan=plan_dict,
        steps=list(exec_ctx.steps),
        total_tokens=exec_ctx.tokens_used,
        total_cost=exec_ctx.cost_used,
        snapshot=exec_ctx.metadata.get("snapshot") or agent_ctx.snapshot(),
        forensic=forensic_ctx.to_dict(),
    )
    store = runtime.trajectory_store
    if store is not None:
        await store.save(record)
    runtime.last_trajectory = record
    for hook in runtime.post_execution_hooks:
        try:
            await hook(record, runtime)
        except Exception:  # noqa: BLE001
            logger.warning("post-execution hook failed", exc_info=True)


@dataclass(frozen=True)
class GraphNode:
    """执行图节点：一次 Skill 调用。

    ``input_refs``：参数级的「上游节点输出引用」，值为 ``"node:<node_id>"``，
    在节点执行时从已完成节点的结果中解析（支持多 Skill 组合的依赖数据传递）。
    静态参数仍走 ``kwargs``；``"$query"`` 由组合器在构建期替换为原始问题。
    """

    node_id: str
    skill_name: str
    kwargs: dict[str, Any] = field(default_factory=dict)
    input_refs: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "skill_name": self.skill_name,
            "kwargs": self.kwargs,
            "input_refs": self.input_refs,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> GraphNode:
        return cls(
            node_id=d["node_id"],
            skill_name=d["skill_name"],
            kwargs=d.get("kwargs", {}),
            input_refs=d.get("input_refs", {}),
        )


class GraphCycleError(ValueError):
    """执行图存在循环依赖，无法分层排序。"""


class ExecutionGraph:
    """动态执行图：节点（Skill 调用）+ 依赖边（``dependent → dependency``，dependency 先执行）。

    用法::

        g = ExecutionGraph()
        g.add_node("a", "web_search", {"query": "..."})
        g.add_node("b", "analyze", {})
        g.add_edge("b", "a")  # b 依赖 a，a 先执行
        layers = g.topological_layers()  # [["a"], ["b"]]

    同层节点无依赖关系，可 ``asyncio.gather`` 并行执行。
    """

    def __init__(self) -> None:
        self._nodes: dict[str, GraphNode] = {}
        # node_id -> 前置依赖集合（dependent -> {dependencies}）
        self._deps: dict[str, set[str]] = {}

    def add_node(
        self,
        node_id: str,
        skill_name: str,
        kwargs: dict[str, Any] | None = None,
        input_refs: dict[str, str] | None = None,
    ) -> GraphNode:
        """添加节点：node_id 唯一，skill_name 为注册表中的能力名。

        ``input_refs``：参数 → ``"node:<node_id>"`` 引用，执行时从上游结果解析。
        """
        if node_id in self._nodes:
            raise ValueError(f"节点已存在: {node_id}")
        node = GraphNode(node_id, skill_name, kwargs or {}, input_refs or {})
        self._nodes[node_id] = node
        self._deps.setdefault(node_id, set())
        return node

    def add_edge(self, dependent: str, dependency: str) -> None:
        """声明依赖：``dependent`` 依赖 ``dependency``（dependency 先执行）。"""
        if dependent not in self._nodes or dependency not in self._nodes:
            raise ValueError(f"未知节点: {dependent} 或 {dependency}")
        if dependent == dependency:
            raise GraphCycleError(f"自环依赖: {dependent}")
        self._deps[dependent].add(dependency)

    @property
    def nodes(self) -> dict[str, GraphNode]:
        """全部节点（只读拷贝）。"""
        return dict(self._nodes)

    @property
    def edges(self) -> dict[str, set[str]]:
        """全部依赖边（只读拷贝）。"""
        return {k: set(v) for k, v in self._deps.items()}

    def detect_cycle(self) -> bool:
        """检测是否存在循环依赖（DFS 三色标记法）。"""
        white, gray, black = 0, 1, 2
        color = {nid: white for nid in self._nodes}

        def dfs(nid: str) -> bool:
            color[nid] = gray
            for dep in self._deps[nid]:
                if color[dep] == gray:
                    return True
                if color[dep] == white and dfs(dep):
                    return True
            color[nid] = black
            return False

        return any(color[nid] == white and dfs(nid) for nid in self._nodes)

    def topological_layers(self) -> list[list[str]]:
        """分层拓扑排序：同层节点无依赖关系，可并行执行。

        返回 ``list[layer]``，layer 是 node_id 列表（按名排序保证确定性）。
        第 0 层无依赖，第 i 层依赖第 <i 层。存在循环时抛 ``GraphCycleError``。
        """
        if self.detect_cycle():
            raise GraphCycleError("执行图存在循环依赖，无法分层排序")
        remaining = set(self._nodes)
        completed: set[str] = set()
        layers: list[list[str]] = []
        while remaining:
            layer = sorted(nid for nid in remaining if self._deps[nid] <= completed)
            if not layer:
                raise GraphCycleError("执行图存在循环依赖（分层求解失败）")
            layers.append(layer)
            completed |= set(layer)
            remaining -= set(layer)
        return layers

    def max_depth(self) -> int:
        """图的最大依赖链深度（层数，空图为 0）。"""
        return len(self.topological_layers()) if self._nodes else 0

    def step_count(self) -> int:
        """总节点数（Skill 调用步数）。"""
        return len(self._nodes)

    def to_dict(self) -> dict[str, Any]:
        """序列化为 dict（供 TrajectoryRecord 持久化 + resume 重建）。"""
        return {
            "nodes": {nid: node.to_dict() for nid, node in self._nodes.items()},
            "deps": {nid: sorted(deps) for nid, deps in self._deps.items()},
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ExecutionGraph:
        """从 dict 重建 ExecutionGraph。"""
        g = cls()
        for nid, node_d in d.get("nodes", {}).items():
            node = GraphNode.from_dict(node_d)
            g._nodes[node.node_id] = node
            g._deps.setdefault(node.node_id, set())
        for nid, deps in d.get("deps", {}).items():
            g._deps[nid] = set(deps)
        return g


async def _run_graph_in_place(
    graph: ExecutionGraph,
    runtime: PlannerRuntime,
    *,
    checkpoint_store: Any | None = None,
    execution_id: str | None = None,
) -> AsyncIterator[StreamEvent]:
    """分层并行执行核心循环（假设已在 ``runtime.execution()`` 边界内）。

    与 ``execute_graph`` 的区别：不创建新的执行边界、不做 ContextManager 快照与轨迹持久化
    —— 供嵌套场景（如 Workflow Skill 内部执行子图）复用调用方已有的执行上下文
    （预算 / 调用栈 / trace 连续累计，符合 doc §7「Skill→Skill 须经 Runtime」）。

    Durability（doc §11）：传入 ``checkpoint_store`` + ``execution_id`` 时，按节点落地
    checkpoint——已完成节点结果复用（崩溃后 resume 不重跑），未完成任务继续（尊重依赖边）。
    """
    # 1. 加载已完成的 checkpoint（resume 场景）：已完成节点直接复用结果，不重跑
    completed: dict[str, Any] = {}
    if checkpoint_store is not None and execution_id is not None:
        cp = await checkpoint_store.load(execution_id)
        if cp is not None:
            completed = dict(cp.completed)

    layers = graph.topological_layers()
    results: dict[str, Any] = dict(completed)
    for i, layer in enumerate(layers):
        exec_ctx = runtime.context
        # §HA split-brain 防护（A 侧）：心跳协程检测到租约被新 owner 接管后置
        # ownership_lost，此处逐层检查并协作式中止——旧 owner 不得继续产生副作用。
        if exec_ctx is not None and exec_ctx.ownership_lost:
            yield StreamEvent(
                type="error",
                payload={
                    "error": "执行所有权已丢失（lease 被新 owner 接管），协作式中止",
                    "completed": len(results),
                },
            )
            return
        # deadline 消费：超限时提前终止，产出 error 事件
        if exec_ctx is not None and exec_ctx.deadline is not None:
            if time.monotonic() > exec_ctx.deadline:
                yield StreamEvent(
                    type="error",
                    payload={"error": "执行超时（deadline 超限）", "completed": len(results)},
                )
                return

        # 已完成节点（来自 checkpoint）：直接复用结果 + 补发 evidence 事件，不再执行
        pending = [nid for nid in layer if nid not in results]

        async def _run(node_id: str) -> "tuple[str, Any, dict | None, bool]":
            node = graph.nodes[node_id]
            # 依赖前置检查：上游在图内但无结果（上游已失败）→ 本节点降级跳过，
            # 不把「依赖失败」误判为 Fatal；引用不存在的上游 = 构图编程错误 → Fatal。
            for arg, ref in node.input_refs.items():
                if ref.startswith("node:"):
                    upstream = ref[len("node:") :]
                    if upstream not in results:
                        if upstream not in graph.nodes:
                            return (
                                node_id,
                                None,
                                {"class": "fatal", "error": f"节点 {node_id} 引用不存在的上游节点 {upstream}"},
                                True,
                            )
                        return (
                            node_id,
                            None,
                            {"class": "recoverable", "error": f"节点 {node_id} 跳过：上游 {upstream} 未产出（依赖降级）"},
                            False,
                        )
            try:
                kwargs: dict[str, Any] = dict(node.kwargs)
                for arg, ref in node.input_refs.items():
                    if ref.startswith("node:"):
                        kwargs[arg] = results[ref[len("node:") :]]
                    else:
                        kwargs[arg] = ref
            except Exception as exc:  # noqa: BLE001
                cls = classify_exception(exc)
                return node_id, None, {"class": cls.value, "error": str(exc)}, cls is ErrorClass.FATAL
            # §HA（H3）：同层 asyncio.gather 期间若租约已被新 owner 接管，下一层边界才
            # 检查会放过本层在途节点继续发起副作用。此处 delegate 前先自查 ownership_lost，
            # 已丢失则中止本节点（不再产生新副作用），复用 fatal 终止分支做协作式中止。
            if exec_ctx is not None and exec_ctx.ownership_lost:
                return (
                    node_id,
                    None,
                    {"class": "ownership_lost", "error": "执行所有权已丢失，节点中止（不发起副作用）"},
                    True,
                )
            # 执行 + 业务级有限重试（V3-2：据 Skill 声明的 EffectContract 决策重试安全性；
            # 未声明时保持 v2 语义——仅瞬态可重试；transport 短重试已在底层 SDK 内，不叠加）
            contract = runtime.get_effect_contract(node.skill_name)
            attempt = 0
            last_exc: Exception | None = None
            while attempt <= _NODE_BUSINESS_RETRY_MAX:
                try:
                    result = await runtime.delegate(node.skill_name, **kwargs)
                    # §HA（H2）：副作用（Skill 落地效果）一旦成功，立即落审计/幂等记录。
                    # effect_key = execution_id:step_id:effect_type（唯一约束 → 重复 attempt 幂等去重）。
                    # 配合 checkpoint，B 接管 resume 时可据此判断哪些 step 已真正落地，不重跑。
                    # V3-2：effect_type 优先用 EffectContract.effect_key（语义化），未声明回退 skill:<name>。
                    if (
                        runtime.side_effect_store is not None
                        and execution_id is not None
                        and exec_ctx is not None
                    ):
                        effect_type = (
                            contract.effect_key
                            if contract is not None
                            else f"skill:{node.skill_name}"
                        )
                        await runtime.side_effect_store.record(
                            execution_id=execution_id,
                            step_id=node_id,
                            effect_type=effect_type,
                            owner=exec_ctx.lease_owner or "",
                        )
                    return node_id, result, None, False
                except ExecutionSuspended:
                    raise  # 控制流信号，不进入重试 / 异常分类
                except Exception as exc:  # noqa: BLE001
                    last_exc = exc
                    action = decide_failure_action(contract, classify_exception(exc))
                    if action is not FailureAction.RETRY_SAFE or attempt >= _NODE_BUSINESS_RETRY_MAX:
                        break
                    attempt += 1
                    await asyncio.sleep(_NODE_BUSINESS_RETRY_BACKOFF * (2 ** (attempt - 1)))
            # 重试耗尽或不可重试 → 按分类决定降级（继续）/ 终止（Fatal）
            assert last_exc is not None
            cls = classify_exception(last_exc)
            fatal = cls is ErrorClass.FATAL
            action = decide_failure_action(contract, cls)
            # 瞬态重试耗尽按 RECOVERABLE 降级（节点失败但执行继续）；Fatal 才终止。
            # failure_action 记入 error_info，供 Scheduler / Control Plane 消费
            # （QUERY_BEFORE_RETRY 在 V3-3 ExternalTask 落地后接入外部状态查询）。
            return (
                node_id,
                None,
                {
                    "class": "fatal" if fatal else "recoverable",
                    "error": str(last_exc),
                    "failure_action": action.value,
                },
                fatal,
            )

        if pending:
            try:
                layer_results = await asyncio.gather(*(_run(nid) for nid in pending))
            except ExecutionSuspended as exc:
                # V3-3: 执行挂起——保存 checkpoint（已完成节点，不含挂起节点）+ 产出 suspended 事件
                if checkpoint_store is not None and execution_id is not None:
                    try:
                        await checkpoint_store.save(
                            Checkpoint(
                                execution_id,
                                dict(results),
                                resumable=True,
                                generation=(
                                    exec_ctx.lease_generation
                                    if exec_ctx is not None
                                    else None
                                ),
                            )
                        )
                    except FencedWriteError:
                        pass  # stale writer，checkpoint 已被新 owner 覆盖
                yield StreamEvent(
                    type="suspended",
                    payload={
                        "task_id": exc.task_id,
                        "node_id": exc.node_id,
                        "execution_id": execution_id,
                    },
                )
                return
            for node_id, result, error_info, fatal in layer_results:
                payload_extra = {
                    "node": node_id,
                    "skill": graph.nodes[node_id].skill_name,
                    "layer": i,
                }
                if fatal:
                    err_class = (error_info or {}).get("class", "fatal")
                    fatal_payload = {
                        **payload_extra,
                        "error": (error_info or {}).get("error", ""),
                        "error_class": err_class,
                    }
                    if error_info and "failure_action" in error_info:
                        fatal_payload["failure_action"] = error_info["failure_action"]
                    yield StreamEvent(type="error", payload=fatal_payload)
                    # ownership_lost 是 §HA 协作式中止（split-brain A 侧），非业务 Fatal；
                    # 统一置位并终止，保证 single-active-owner，避免继续产生副作用。
                    if err_class == "ownership_lost" and exec_ctx is not None:
                        exec_ctx.ownership_lost = True
                    return  # 致命异常 / 所有权丢失 → 终止整次执行（已完成节点已 checkpoint，可 resume/诊断）
                if error_info is not None:
                    err_payload = {
                        **payload_extra,
                        "error": error_info["error"],
                        "error_class": error_info["class"],
                    }
                    if "failure_action" in error_info:
                        err_payload["failure_action"] = error_info["failure_action"]
                    yield StreamEvent(type="error", payload=err_payload)
                else:
                    results[node_id] = result
                    # checkpoint 落盘：每完成一个节点即持久化（崩溃后 resume 可复用）。
                    # §HA（C3）：save 带单调 version CAS，stale writer（已丢 lease 的旧
                    # owner）写入会被 PgCheckpointStore 拒绝并抛 FencedWriteError——此处
                    # 捕获并协作式中止，保持 single-active-owner，不降级覆盖新 owner 的
                    # checkpoint。
                    if checkpoint_store is not None and execution_id is not None:
                        try:
                            await checkpoint_store.save(
                                Checkpoint(
                                    execution_id,
                                    dict(results),
                                    generation=(
                                        exec_ctx.lease_generation
                                        if exec_ctx is not None
                                        else None
                                    ),
                                )
                            )
                        except FencedWriteError as exc:
                            if exec_ctx is not None:
                                exec_ctx.ownership_lost = True
                            yield StreamEvent(
                                type="error",
                                payload={
                                    "node": node_id,
                                    "error": f"checkpoint 写入被 fencing 拒绝（stale writer）: {exc}",
                                    "completed": len(results),
                                },
                            )
                            return
                    yield StreamEvent(
                        type="evidence",
                        payload={**payload_extra, "result": result},
                    )
        # 本层已完成的节点（来自 checkpoint）补发 evidence 事件，保持事件流完整
        for node_id in layer:
            if node_id in results and node_id not in pending:
                yield StreamEvent(
                    type="evidence",
                    payload={
                        "node": node_id,
                        "skill": graph.nodes[node_id].skill_name,
                        "layer": i,
                        "result": results[node_id],
                        "resumed": True,
                    },
                )
    yield StreamEvent(type="answer", payload={"results": results})


async def execute_graph(
    graph: ExecutionGraph,
    runtime: PlannerRuntime,
    *,
    checkpoint_store: Any | None = None,
    execution_id: str | None = None,
) -> AsyncIterator[StreamEvent]:
    """分层并行执行 ExecutionGraph（顶层入口）：创建 ``execution()`` 边界后执行核心循环。

    每个节点经 ``runtime.delegate()`` 调用 Skill（受 ``skill_guard`` 组合治理，
    计入步数 / 深度 / 循环预算）。事件透传给调用方（``execute_plan`` 负责 CM 快照与轨迹持久化）。

    嵌套场景（Workflow 内部子图）应改用 ``_run_graph_in_place`` 复用调用方已有的执行上下文，
    避免重复创建边界导致预算复位。传 ``checkpoint_store`` + ``execution_id`` 启用执行级
    checkpoint/resume（doc §11 / Phase E）。
    """
    async with runtime.execution(execution_id=execution_id):
        async for event in _run_graph_in_place(
            graph, runtime, checkpoint_store=checkpoint_store, execution_id=execution_id
        ):
            yield event


async def execute_plan(
    plan: Plan,
    runtime: PlannerRuntime,
    *,
    caller_permissions: frozenset[str] | set[str] | None = None,
    max_parallel: int | None = None,
) -> AsyncIterator[StreamEvent]:
    """执行 Plan 的通用入口：带 graph 时 validate → execute_graph，否则单 route delegate。

    架构契约（Plan-F 执行链打通）：Planner 产出 Plan 后，可经此入口执行——

    - ``plan.graph`` 非空：经 ``PolicyValidator`` 校验（循环 / 深度 / 步数 / 权限）后，
      在 ``execution()`` 边界内分层并行执行；
    - ``plan.graph`` 为 None：退化为单 route delegate 调用（通用入口，不替代
      deterministic/agentic planner 的丰富编排——它们有自己的 execute 实现）。

    本函数内部创建 ``execution()`` 边界，调用方无须自行包裹。
    执行过程中经 ``ContextManager`` 记录 task/execution 状态，结束时产出
    ``status`` 事件含结构化 snapshot（供调用方持久化或注入下一轮 prompt）。
    """
    from agent_runtime.planner.context_manager import ContextManager
    from agent_runtime.planner.policy import PolicyValidator

    cm = ContextManager()
    ctx = cm.create_context(
        goal=plan.sub_query or plan.route,
        constraints=plan.constraints or None,
    )
    # WS-2：compacted 标记回填——上游（Planner 路由期经 ContextAssembler 压缩）
    # 在 Plan.compacted 标记后，由这里写入 ConversationContext，保持三层契约一致。
    if plan.compacted:
        ctx.conversation.compacted = True

    if plan.graph is not None:
        validator = PolicyValidator(runtime.registry)
        validator.validate(
            plan.graph,
            max_depth=runtime.max_skill_depth,
            max_steps=runtime.max_steps,
            caller_permissions=caller_permissions,
            max_parallel=max_parallel,
        )
        yield StreamEvent(type="route", payload={"capability": "graph", "reason": plan.reason})
        async with runtime.execution():
            # snapshot 消费（Plan-F Context Pipeline）：执行中把结构化快照写入
            # ExecutionContext.metadata，供下一轮组装（ContextAssembler 读 task/execution
            # 层注入）或持久化消费——修掉「status 事件产出 snapshot 但无人消费」。
            # 注意：直接复用 _run_graph_in_place（不套 execute_graph），避免嵌套 execution() 边界。
            exec_ctx = runtime.context
            assert exec_ctx is not None  # 在 execution() 边界内必然已设置
            async for event in _run_graph_in_place(
                plan.graph,
                runtime,
                checkpoint_store=runtime.checkpoint_store,
                execution_id=exec_ctx.execution_id,
            ):
                if event.type == "evidence":
                    cm.record_skill(
                        ctx, event.payload.get("skill", ""), result=event.payload.get("result")
                    )
                elif event.type == "error":
                    cm.record_skill(
                        ctx, event.payload.get("skill", ""), error=event.payload.get("error", "")
                    )
                yield event
            exec_ctx = runtime.context
            if exec_ctx is not None:
                snapshot = cm.snapshot(ctx)
                exec_ctx.metadata["snapshot"] = snapshot
                # 记录到 runtime，供 execution 边界退出后（context 复位前）消费
                runtime.last_snapshot = snapshot
                await _persist_trajectory(runtime, plan, ctx, exec_ctx)
        yield StreamEvent(
            type="status",
            payload={
                "snapshot": cm.snapshot(ctx),
                **_usage_payload(runtime),
            },
        )
    else:
        yield StreamEvent(type="route", payload={"capability": plan.route, "reason": plan.reason})
        async with runtime.execution():
            kwargs = plan.kwargs
            result = await runtime.delegate(plan.route, **kwargs)
            cm.record_skill(ctx, plan.route, result=result)
            yield StreamEvent(type="evidence", payload={"node": plan.route, "result": result})
            yield StreamEvent(type="answer", payload={"text": str(result)})
            exec_ctx = runtime.context
            if exec_ctx is not None:
                await _persist_trajectory(runtime, plan, ctx, exec_ctx)
        yield StreamEvent(
            type="status",
            payload={"snapshot": cm.snapshot(ctx), **_usage_payload(runtime)},
        )
