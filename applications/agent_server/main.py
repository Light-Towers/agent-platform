"""应用工厂与生命周期：lifespan 内完成连接池 + 图的预热构建。

所有全局资源在 lifespan 一次性初始化（带锁），请求路径零懒加载竞态。
"""

import pathlib
from contextlib import asynccontextmanager

from agent_core.guardrails.app_factory import build_api_app
from agent_core.logging import configure_logging, get_logger
from agent_core.tracing import init_tracing, shutdown_tracing
from agent_runtime.identity import require_identity_startup_guard
from agent_runtime.identity_middleware import IdentityMiddleware

# 统一日志配置入口：必须在其它包 import 之前调用，使下列 format 优先生效
# （agent_runtime 等模块在 import 时即触发 get_logger → 惰性 configure_logging，
# 若晚于此调用则会用默认格式覆盖本 format）。配置 root + agent_core 子树
# （agent_core propagate=False，消除与宿主 double-handler 的重复日志），
# 级别可经环境变量 LOG_LEVEL 覆盖。
configure_logging(fmt="%(asctime)s %(levelname)s %(name)s: %(message)s")
from agent_runtime.admission import AdmissionQueue, RateLimiter
from agent_runtime.admission_gateway import PgAdmissionController
from agent_runtime.coordinator import SessionCoordinator
from agent_runtime.db import close_pool, get_pool, init_pool
from agent_runtime.mcp_client import MCPClientManager
from agent_runtime.planner.durability_pg import (
    PgCheckpointStore,
    PgExecutionOwnershipStore,
    PgIdempotencyStore,
)
from agent_runtime.revert import RevertHandler
from agent_runtime.skills.workflow import discover_workflows
from agent_runtime.trajectory import PgTrajectoryStore
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agent_server.agent.graph import DelegateRef, build_graph
from agent_server.agent.llm import build_chat_model
from agent_server.api.routes import router
from agent_server.config import get_settings
from agent_server.schemas import McpServerConfig

logger = get_logger(__name__)


async def _build_checkpointer():
    """有 DATABASE_URL 复用 PG 连接池走 Postgres checkpoint；否则内存版（开发模式）。

    统一委托内核 ``get_checkpointer(pg_pool=...)`` 工厂（C8 收口：避免各子包重复
    if MONGO_URL / if DATABASE_URL 样板）。PG 池由 app 自己的 init_pool() 管理，
    仅把池句柄透传给工厂；Mongo/InMemory 分支完全由内核负责降级。
    """
    pool = get_pool()  # db_enabled 为 False 时返回 None → 工厂降级 InMemorySaver
    if pool is None and get_settings().db_enabled:
        raise RuntimeError("db_enabled 但连接池未初始化，检查 lifespan 中 init_pool 顺序")
    from agent_core.memory import get_checkpointer

    saver = get_checkpointer(pg_pool=pool)
    # AsyncPostgresSaver 需要异步建表；InMemorySaver / MongoCheckpointer 无需 setup。
    if pool is not None:
        await saver.setup()
    return saver


def _build_payload_externalizer():
    """V3-6 Layer B：大 payload 外部化（缺口 7，opt-in）。关闭时返回 None ⇒ checkpoint 路径逐字不变。

    开了但没给目录 ⇒ **fail-fast**：静默退回"没开"会让运维以为大 payload 已经外置，
    而 JSONB 仍在膨胀。与 ``_build_checkpointer`` 里「db_enabled 但 pool 未初始化即抛」
    同一处置口径。
    """
    settings = get_settings()
    if not settings.payload_externalization_enabled:
        return None
    if not settings.payload_externalization_dir:
        raise RuntimeError(
            "PAYLOAD_EXTERNALIZATION_ENABLED=true 但未配 PAYLOAD_EXTERNALIZATION_DIR"
        )
    from agent_runtime.payload_externalization import (
        ExternalizationConfig,
        FileSystemPayloadStore,
        PayloadExternalizer,
    )

    return PayloadExternalizer(
        FileSystemPayloadStore(settings.payload_externalization_dir),
        config=ExternalizationConfig(
            threshold_bytes=settings.payload_externalization_threshold_bytes
        ),
    )


def _build_pg_stores(pool, externalizer=None):
    """构建 PG 持久化后端（§20.1/20.2 + P3-1）。

    ``externalizer`` 可注入（缺口 7：reaper 的 GC sweep 与 checkpoint 外部化
    共用同一实例/同一 blob 目录）；缺省 None 时自建（禁用态返回 None）。
    仅在 pool 非 None 时创建；返回 (checkpoint_store, idempotency_store, ownership_store, trajectory_store)。
    """
    if pool is None:
        return None, None, None, None
    # V3-6 Layer B：不传 migrator 则 load() 的 schema 迁移分支恒不执行（默认 None）
    from agent_runtime.state_migration import get_default_migrator

    if externalizer is None:
        externalizer = _build_payload_externalizer()

    checkpoint_store = PgCheckpointStore(
        pool,
        migrator=get_default_migrator(),
        externalizer=externalizer,
    )
    idempotency_store = PgIdempotencyStore(pool)
    ownership_store = PgExecutionOwnershipStore(pool)
    trajectory_store = PgTrajectoryStore(pool)
    return checkpoint_store, idempotency_store, ownership_store, trajectory_store


def _warm_embedding_backend() -> tuple[str, bool]:
    """启动期解析一次实际 embedder，返回 (类型名, 是否真实语义后端)。

    刻意不因失败而中断启动：EMBEDDING_REQUIRE_REAL=true 且后端退化为 Mock 时，
    resolve_provider() 会抛错——那是**调用期**既有的硬失败护栏（检索真的算不出来就该失败，
    而不是静默按字面比对）。若把它升级成启动期 crash-loop，反而会让"配了开关但镜像缺依赖"
    这种现场直接起不来。折中形态：进程照常起来，红灯如实亮 unknown/false，任何真实检索仍硬失败。

    失败必须留日志——静默降级正是「关了和坏了分不清」的来源。
    """
    try:
        from agent_core.memory.embedder import MockEmbedder

        from agent_server.rag.embed import resolve_provider

        provider = resolve_provider()
        return type(provider).__name__, not isinstance(provider, MockEmbedder)
    except Exception:  # noqa: BLE001 —— 后端预热失败不阻断启动：红灯如实亮 unknown/false，且必留日志
        logger.exception("embedding 后端预热失败：/health 报 embedding_backend=unknown / embedding_real=false")
        return "unknown", False


def _build_memory_hooks(pool):
    """构建执行后记忆沉淀 hooks（EpisodicSink + ProceduralSink + MemoryDecayManager）。

    pool 非 None 时用 PG 后端，否则 InMemory。使记忆框架"越用越好"——
    执行完成后自动沉淀 Episode → 定期挖掘候选 Skill → 衰减清理。
    """
    from agent_runtime.episodic_memory import EpisodicMemory, InMemoryEpisodicStore
    from agent_runtime.memory_decay import MemoryDecayManager
    from agent_runtime.memory_sink import EpisodicSink, ProceduralSink
    from agent_runtime.procedural_memory import InMemoryProceduralStore

    if pool is not None:
        from agent_runtime.memory_pg import PgEpisodicStore, PgProceduralStore

        ep_store = PgEpisodicStore(pool)
        proc_store = PgProceduralStore(pool)
    else:
        ep_store = InMemoryEpisodicStore()
        proc_store = InMemoryProceduralStore()

    ep_mem = EpisodicMemory(ep_store)
    return [
        EpisodicSink(ep_mem),
        ProceduralSink(ep_mem, proc_store, trigger_interval=10),
        MemoryDecayManager(ep_store, cleanup_interval=50),
    ]


def _build_context_governor(pool, llm):
    """构建 Context 治理管道（ContextGovernor）：Select → Recall → Authorize → Validate → Score。

    pool 非 None 时用 PG 后端 Memory，否则 InMemory。Governor 挂 app.state，
    供 routes.py 在构建 PlannerContext 前调 govern_memories() 注入已治理的记忆。
    """
    from agent_runtime.context.assembler import ContextAssembler
    from agent_runtime.context.authorizer import ContextAuthorizer
    from agent_runtime.context.budget import ContextBudget
    from agent_runtime.context.governor import ContextGovernor
    from agent_runtime.context.quality import ContextQualityScorer
    from agent_runtime.context.validator import ContextValidator
    from agent_runtime.episodic_memory import EpisodicMemory, InMemoryEpisodicStore
    from agent_runtime.memory_types import ContextSelector, MemoryRetriever
    from agent_runtime.procedural_memory import (
        InMemoryProceduralStore,
        ProceduralMemory,
    )

    if pool is not None:
        from agent_runtime.memory_pg import PgEpisodicStore, PgProceduralStore

        ep_store = PgEpisodicStore(pool)
        proc_store = PgProceduralStore(pool)
    else:
        ep_store = InMemoryEpisodicStore()
        proc_store = InMemoryProceduralStore()

    ep_mem = EpisodicMemory(ep_store)
    proc_mem = ProceduralMemory(proc_store)
    retriever = MemoryRetriever(episodic=ep_mem, procedural=proc_mem)

    budget = ContextBudget(model_window=32_000)
    assembler = ContextAssembler(budget, llm=llm)

    return ContextGovernor(
        assembler=assembler,
        retriever=retriever,
        selector=ContextSelector(),
        validator=ContextValidator(),
        authorizer=ContextAuthorizer(),
        quality_scorer=ContextQualityScorer(),
    )


def _build_admission_controller(pool, settings):
    """构建 admission 控制器：distributed 模式用 PgAdmissionController，其余用 AdmissionQueue。"""
    if pool is None:
        return None
    if settings.runtime_mode == "distributed":
        return PgAdmissionController(
            pool,
            capacity=settings.admission_queue_capacity,
            timeout_s=settings.admission_queue_timeout_seconds,
        )
    # single_node / local：继续用现有 AdmissionQueue（内存调度 + PG 持久化队列）
    if settings.admission_effective_enabled:
        limiter = RateLimiter(
            per_user=settings.admission_rate_limit_per_user,
            per_session=settings.admission_rate_limit_per_session,
            global_=settings.admission_rate_limit_global,
        )
        return AdmissionQueue(
            pool=pool,
            capacity=settings.admission_queue_capacity,
            timeout_seconds=settings.admission_queue_timeout_seconds,
            rate_limiter=limiter,
            effective_enabled=True,
        )
    return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    # §20 C4: distributed 模式必须有 PG，否则 fail fast
    if settings.runtime_mode == "distributed" and not settings.db_enabled:
        raise RuntimeError(
            "runtime_mode=distributed 要求配置 DATABASE_URL，当前为空。"
            "请设置 DATABASE_URL 或改用 runtime_mode=single_node/local。"
        )

    # ADR-0007 A3: 身份启动守卫——既无 RS256 验签公钥又未声明 SINGLE_TENANT 且
    # DEPLOY_ENFORCE_IDENTITY=true → 拒绝启动（封死 auth.py 未配 key 即不校验旁路）。
    require_identity_startup_guard("agent_server")

    await init_pool(
        database_url=settings.database_url,
        db_pool_max_size=settings.db_pool_max_size,
    )
    pool = get_pool()
    checkpointer = await _build_checkpointer()

    # §20.1/20.2 + P3-1: 构建 PG 持久化后端
    # 缺口 7（2026-10-19）：externalizer 提前构建——checkpoint 外部化与 reaper 的
    # blob GC sweep 共用同一实例（同一 FileSystemPayloadStore 目录）。仅 pool 在场
    # 时构建：保持「开了没配目录即 fail-fast」的原触发时序（pool 缺席不提前炸）。
    payload_externalizer = _build_payload_externalizer() if pool is not None else None
    checkpoint_store, idempotency_store, ownership_store, trajectory_store = _build_pg_stores(
        pool, externalizer=payload_externalizer
    )

    # Phase 2: OTel 接线（opt-in）；观测单状态机在 kernel（S1），请求级 span 由
    # build_api_app(enable_tracing=True) 装配的 TracingMiddleware 创建（S2），
    # 不再往 app.state 挂 tracer 散点取用（lint L-2 拦截）。
    # 门面退役（2026-09-30）：原 agent_runtime.otel.init_otel 参数映射内联至装配点，
    # 直调 kernel init_tracing（jaeger thrift exporter 已归档 → 映射 OTLP 接收端）。
    #
    # 【顺序是硬约束，别挪到下面去】必须在 build_chat_model() **之前**：
    # Langfuse 客户端的构造会把全局 TracerProvider 换成它自己那份（processors 只有
    # LangfuseSpanProcessor），kernel 的 init_tracing 遇到"已存在非 Proxy provider"会复用而不覆盖
    # ⇒ 本平台的 OTLP 导出器永远挂不上，Jaeger 面整体静默而 /health 仍报 ACTIVE
    # （2026-10-13 现网实测，缺陷 D-LF-1，方案 §7）。反序则 Langfuse 复用我们的 provider
    # 并把它的 processor 追加进去 = 一棵 span 树、两个后端。
    if settings.otel_effective_enabled:
        if settings.otel_exporter == "console":
            try:
                from opentelemetry.sdk.trace.export import ConsoleSpanExporter

                _otel_exporter = ConsoleSpanExporter()
            except ImportError:
                _otel_exporter = None  # kernel 记 DEGRADED（R5：可区分显式关与坏了）
            init_tracing(
                service_name=settings.otel_service_name,
                enabled=True,
                exporter=_otel_exporter,
                sampling_rate=settings.otel_sampling_rate,
            )
        else:
            # otlp / jaeger→otlp：endpoint 为空传 None 让 kernel 回退标准 env
            # （OTEL_EXPORTER_OTLP_ENDPOINT）；仍为空则记 DEGRADED=no_export_endpoint。
            init_tracing(
                service_name=settings.otel_service_name,
                otel_endpoint=settings.otel_endpoint or None,
                enabled=True,
                sampling_rate=settings.otel_sampling_rate,
            )

    llm = build_chat_model()

    # Langfuse 观测面两盏灯（方案 docs/plans/plan-langfuse-wiring-2026-10-13.md §2.2）。
    # langfuse_enabled 只是"三个配置项非空"= 意愿；langfuse_ready 读**已装配的运行态**——
    # callbacks 是否在 ChatOpenAI 构造期真挂上（装配点唯一：agent/llm.py:build_chat_model）。
    # enabled=true 而 ready=false 就是"配了但没接上"，这是镜像没装客户端包时唯一的可见信号
    #（此前它只记一行 warning 就静默不报，"关了"与"坏了"分不清）。
    # 判据必须在启动期算：绝不在 /health 探针路径上调 get_langfuse_callbacks()——
    # 那会让每次探测构造一个 Langfuse 客户端，与"不在探针里加载 embedder"是同一条红线。
    app.state.langfuse_enabled = settings.langfuse_enabled
    app.state.langfuse_ready = bool(llm is not None and getattr(llm.primary, "callbacks", None))

    # 语义检索后端：启动期解析一次并把实际类型名存进 app.state，/health 只读该已存值。
    # 放在 lifespan 而不是 /health 里现算，是因为集群存活/就绪探针的 timeoutSeconds 为 1、
    # liveness 连错 3 次即杀容器，而本地 embedder 的构造是同步加载模型——在探针路径里
    # 装模型等于自己造一次「探针连错三次 → 被 SIGKILL」。
    app.state.embedding_backend, app.state.embedding_real = _warm_embedding_backend()

    # Phase 2: 会话并发协调
    if settings.coordination_enabled:
        app.state.coordinator = SessionCoordinator(
            policy=settings.coordination_policy,
            enabled=True,
        )
    else:
        app.state.coordinator = None

    # Phase 2: admission 控制器（按 runtime_mode 选择实现）
    admission_controller = _build_admission_controller(pool, settings)
    if admission_controller is not None:
        recovered = await admission_controller.recover_on_startup()
        if recovered:
            logger.info("admission recovered %d interrupted requests", recovered)
        app.state.admission_controller = admission_controller
    else:
        app.state.admission_controller = None

    # Phase 2: 会话回退 revert
    if settings.revert_enabled:
        app.state.revert_handler = RevertHandler(checkpointer, pool)
    else:
        app.state.revert_handler = None

    # Phase 2: OTel 接线已上移到 build_chat_model() 之前（缺陷 D-LF-1，方案 §7）——
    # 那里写着顺序为什么是硬约束。

    # Phase 2: MCP client（opt-in）
    mcp_manager = None
    if settings.mcp_enabled and settings.mcp_servers:
        try:
            import json

            configs = [McpServerConfig(**c) for c in json.loads(settings.mcp_servers)]
            mcp_manager = MCPClientManager(
                server_configs=configs,
                pool=pool,
                breaker_failure_threshold=settings.breaker_failure_threshold,
                breaker_recovery_seconds=settings.breaker_recovery_seconds,
            )
            await mcp_manager.connect_all()
        except Exception:
            logger.warning("MCP init failed, degrading", exc_info=True)
            mcp_manager = None
    app.state.mcp_manager = mcp_manager

    # delegate_ref 延迟绑定：graph 节点经 runtime.delegate 调用能力（受 skill_guard 组合治理），
    # 解决循环依赖（graph → registry → runtime → graph）——先传空 holder，runtime 创建后填充。
    delegate_ref = DelegateRef()
    app.state.graph = build_graph(
        llm, checkpointer=checkpointer, mcp_manager=mcp_manager, delegate_ref=delegate_ref
    )
    app.state.checkpointer = checkpointer
    # Plan-F Phase 2: Planner 实现（PLANNER env 选择，Phase 3 统一 SSE 出口后供 api 消费）
    # Plan-F Phase 3: PlannerRuntime——注册表注入 graph（含 general_qa Workflow Skill），
    # llm/mcp_manager/pool 一并装配；组合治理（max_skill_depth/max_steps）约束 agentic 路径。
    from agent_runtime.planner.protocol import PlannerRuntime

    from agent_server.capabilities import get_registry
    from agent_server.planners import get_planner

    # 装配顺序：registry 先于 planner（GraphPlanner plan() 需 registry 做 discover）
    registry = get_registry(graph=app.state.graph)

    # §20 演进：自动发现并注册 Workflows 目录（声明式 YAML → Skill）
    try:
        import agent_runtime
        _wf_dir = str(pathlib.Path(agent_runtime.__file__).parent / "workflows")
        wf_skills = discover_workflows(
            _wf_dir,
            registry=registry,
        )
        for sk in wf_skills:
            registry.register(sk)
        logger.info("auto-registered %d workflow skills from %s", len(wf_skills), _wf_dir)
    except Exception:
        logger.warning("workflow auto-discovery failed", exc_info=True)

    # MCP 工具自动注册为 Skill（每个工具 → SkillKind.REMOTE Skill）
    if mcp_manager is not None:
        from agent_runtime.skills.mcp import register_mcp_skills

        mcp_count = register_mcp_skills(mcp_manager, registry)
        logger.info("auto-registered %d MCP tool skills", mcp_count)

    # 沙箱代码执行 Skill（Docker 优先 subprocess 降级）
    from agent_runtime.skills.sandbox import as_sandbox_skill

    sandbox_skill = as_sandbox_skill(timeout=settings.max_execution_seconds or 30)
    if sandbox_skill.name not in registry:
        registry.register(sandbox_skill)
        logger.info("registered sandbox skill (backend=%s)", sandbox_skill.metadata.get("backend"))

    # AgenticPlanner → SkillKind.AGENT 收敛（entry_points 不可用时跳过）
    try:
        from agent_runtime.planner.agentic import AgenticPlanner

        agentic_skill = AgenticPlanner().to_skill()
        if agentic_skill.name not in registry:
            registry.register(agentic_skill)
            logger.info("registered agentic skill (SkillKind.AGENT)")
    except Exception:
        # entry_points 不可用是常见预期（非 agentic 部署）；仅当运行时实际需要
        # agentic/auto planner 时才值得警告，否则 DEBUG 记录（T1.2c / B2 评审结论）
        if settings.planner in ("agentic", "auto"):
            logger.warning(
                "agentic skill 注册失败（planner=%s 运行时需要该 skill）",
                settings.planner,
                exc_info=True,
            )
        else:
            logger.debug("agentic skill registration skipped (entry_points unavailable)", exc_info=True)

    app.state.registry = registry
    app.state.planner = get_planner(settings, registry=registry)
    post_execution_hooks = _build_memory_hooks(pool)
    app.state.context_governor = _build_context_governor(pool, llm)
    # V3-3: AwaitableTask 持久化（PG 优先，InMemory 降级）
    if pool is not None:
        from agent_runtime.awaitable_task_pg import PgAwaitableTaskStore

        awaitable_task_store = PgAwaitableTaskStore(pool)
    else:
        from agent_runtime.awaitable_task import InMemoryAwaitableTaskStore

        awaitable_task_store = InMemoryAwaitableTaskStore()
    app.state.awaitable_task_store = awaitable_task_store
    # V3 补-1: 人工审批（HumanTaskStore 复用同一个 awaitable store）。resolver 要等
    # status_store 建好后再装（见下方 scheduler 块之后），此处先占位避免属性缺失。
    from agent_runtime.human_task import HumanTaskStore

    app.state.human_task_store = HumanTaskStore(awaitable_task_store)
    app.state.human_task_resolver = None
    app.state.planner_runtime = PlannerRuntime(
        registry=registry,
        llm=llm,
        mcp_manager=mcp_manager,
        pool=pool,
        max_skill_depth=settings.max_skill_depth,
        max_steps=settings.max_steps,
        max_duration_seconds=settings.max_execution_seconds or None,
        checkpoint_store=checkpoint_store,
        ownership_store=ownership_store,
        trajectory_store=trajectory_store,
        enable_loop_fingerprint=settings.enable_loop_fingerprint,
        workspace_id="default",
        user_id="default",
        post_execution_hooks=post_execution_hooks,
        awaitable_task_store=awaitable_task_store,
        human_task_store=app.state.human_task_store,
    )
    # 绑定 delegate：graph 节点的 _invoke 此后经 runtime.delegate 调用
    delegate_ref.delegate = app.state.planner_runtime.delegate
    # Langfuse LLM 观测不在 lifespan 装配 callbacks：原 app.state.callbacks 装配后
    # 无消费方（断线），已收敛到 build_chat_model() 构造期单点注入（覆盖 planner /
    # graph / bind_tools 全部 LLM 调用路径），见 agent_server/agent/llm.py。
    # V3 Phase 2: ExecutionScheduler + ExecutionStatusStore（opt-in）
    if settings.scheduler_enabled:
        from agent_runtime.execution_scheduler import (
            ExecutionScheduler,
            InMemorySchedulerStore,
            SchedulerConfig,
        )
        from agent_runtime.execution_status import InMemoryExecutionStatusStore

        if pool is not None:
            from agent_runtime.execution_scheduler import PgSchedulerStore
            from agent_runtime.execution_state_pg import PgExecutionStatusStore

            scheduler_store = PgSchedulerStore(pool)
            status_store = PgExecutionStatusStore(pool)
        else:
            scheduler_store = InMemorySchedulerStore()
            status_store = InMemoryExecutionStatusStore()
        scheduler = ExecutionScheduler(
            scheduler_store,
            config=SchedulerConfig(
                max_concurrent=settings.scheduler_max_concurrent,
                max_concurrent_per_tenant=settings.scheduler_max_concurrent_per_tenant,
                queue_capacity=settings.scheduler_queue_capacity,
            ),
        )
        app.state.scheduler = scheduler
        app.state.status_store = status_store
        # V3-4B: 恢复编排器（缺口 4 的 reschedule）。默认关：开启后 retry 分支会向队列
        # 新入一条 `:retry:N`，重试消耗队列容量（QueueFull 时静默失败）；
        # 关闭时 Reaper 逐字保持旧行为（只标 FAILED + 释放 slot）。
        recovery = None
        if settings.scheduler_recovery_enabled:
            from agent_runtime.execution_recovery import (
                ReaperConfig,
                RecoveryOrchestrator,
                make_trajectory_contract_resolver,
            )

            # 缺口 4 残差（2026-10-19，#99）：接生产 contract_resolver——读轨迹取
            # plan.route 经 registry 查 Effect Contract，让四类 FailureRecovery
            # 恢复语义真正生效（此前契约恒 None，决策恒退化为默认可重试）。
            # trajectory_store 缺席（无 PG）时不接：保持现状语义，不造内存替身。
            contract_resolver = None
            if trajectory_store is not None:
                contract_resolver = make_trajectory_contract_resolver(
                    trajectory_store, registry
                )

            recovery = RecoveryOrchestrator(
                scheduler,
                config=ReaperConfig(max_retries=settings.scheduler_recovery_max_retries),
                contract_resolver=contract_resolver,
                # 缺口 3（2026-10-19）：QUERY_STATUS 执行体——查外部任务真实状态
                # 并按态动作（completed→resume 续跑 / failed→FAILED / 在途→不动防
                # 重复副作用）。store 已在同一 lifespan 装配（PG 或内存）。
                awaitable_store=awaitable_task_store,
            )
        # V3 Phase 3: Scheduler Reaper（lease-based 回收）
        if ownership_store is not None:
            from agent_runtime.execution_scheduler import SchedulerReaper

            # 缺口 7（2026-10-19）：externalization 启用时才挂 GC sweep 回调
            # （特性默认关 ⇒ 无回调，reaper 行为逐字不变）。
            sweep_callbacks = (
                [payload_externalizer.sweep] if payload_externalizer is not None else None
            )
            reaper = SchedulerReaper(
                scheduler,
                ownership_store,
                recovery=recovery,
                sweep_callbacks=sweep_callbacks,
            )
            reaper.start()
            app.state.scheduler_reaper = reaper
            logger.info(
                "V3 scheduler reaper started (lease-based, recovery=%s)",
                "on" if recovery is not None else "off",
            )
        else:
            app.state.scheduler_reaper = None
        # V3 Phase 4: Control Plane（组合 scheduler + status_store + checkpoint_store
        # + awaitable_store + recovery）。awaitable_store 此前未传 ⇒ inspect 的
        # external_tasks 段恒为空（能力在而装配漏接），本批补齐。
        from agent_runtime.control_plane import ControlPlane

        app.state.control_plane = ControlPlane(
            scheduler=scheduler,
            status_store=status_store,
            checkpoint_store=checkpoint_store,
            awaitable_store=awaitable_task_store,
            recovery=recovery,
        )
        logger.info(
            "V3 scheduler enabled: max_concurrent=%d per_tenant=%d queue=%d backend=%s",
            settings.scheduler_max_concurrent,
            settings.scheduler_max_concurrent_per_tenant,
            settings.scheduler_queue_capacity,
            "pg" if pool is not None else "memory",
        )
    else:
        app.state.scheduler = None
        app.state.status_store = None
    # V3 补-1: 人工审批 resolver。status_store 仅在 scheduler 开启时存在，而 resolver 容忍
    # None ⇒ 未开 scheduler 时审批仍能收敛任务状态，只是不做 WAITING_HUMAN → RUNNING 的
    # 状态机推进（那条推进本来就依赖 ExecutionStatus 面）。
    from agent_runtime.human_task import HumanTaskResolver

    app.state.human_task_resolver = HumanTaskResolver(
        app.state.human_task_store,
        status_store=getattr(app.state, "status_store", None),
    )
    # V3 Phase 4: Cost Governance（opt-in）
    if settings.cost_governance_enabled:
        from agent_runtime.cost_governance import (
            BudgetDimension,
            BudgetLimit,
            CostGovernance,
            InMemoryBudgetStore,
        )

        limits: dict[BudgetDimension, BudgetLimit] = {}
        if settings.budget_limit_requests > 0:
            limits[BudgetDimension.REQUESTS] = BudgetLimit(
                BudgetDimension.REQUESTS, settings.budget_limit_requests,
                window_seconds=settings.budget_window_seconds,
            )
        if settings.budget_limit_tokens > 0:
            limits[BudgetDimension.TOKENS] = BudgetLimit(
                BudgetDimension.TOKENS, settings.budget_limit_tokens,
                window_seconds=settings.budget_window_seconds,
            )
        if settings.budget_limit_cost > 0:
            limits[BudgetDimension.COST] = BudgetLimit(
                BudgetDimension.COST, settings.budget_limit_cost,
                window_seconds=settings.budget_window_seconds,
            )
        if pool is not None:
            from agent_runtime.cost_governance_pg import PgBudgetStore

            budget_store = PgBudgetStore(pool)
        else:
            budget_store = InMemoryBudgetStore()
        app.state.cost_governance = CostGovernance(budget_store, limits)
        logger.info(
            "V3 cost governance enabled: limits=%s backend=%s",
            {dim.value: lim.limit for dim, lim in limits.items()},
            "pg" if pool is not None else "memory",
        )
    else:
        app.state.cost_governance = None
    logger.info(
        "agent-platform 就绪 storage=%s llm=%s pool=%s coordination=%s admission=%s revert=%s otel=%s mcp=%s planner=%s runtime_mode=%s",
        "postgres" if settings.db_enabled else "memory",
        settings.llm_enabled,
        pool is not None,
        settings.coordination_enabled,
        admission_controller is not None,
        settings.revert_enabled,
        settings.otel_effective_enabled,
        mcp_manager is not None,
        getattr(app.state.planner, "kind", "unknown"),
        settings.runtime_mode,
    )
    yield
    # V3 Phase 3: Scheduler Reaper 停止
    reaper = getattr(app.state, "scheduler_reaper", None)
    if reaper is not None:
        await reaper.stop()
    # Phase 2: OTel 统一退出（kernel flush+shutdown provider，尾批 span 不丢）
    shutdown_tracing()
    # Phase 2: MCP close
    mcp_mgr = getattr(app.state, "mcp_manager", None)
    if mcp_mgr is not None:
        await mcp_mgr.close_all()
    # checkpointer 复用 init_pool 的连接池（db_enabled 时 conn 即 _pool），
    # 生命周期归 close_pool() 统一管理，此处不再单独关闭连接。
    await close_pool()


def create_app() -> FastAPI:
    app = build_api_app(title="agent-platform", version="0.1.0", lifespan=lifespan, enable_tracing=True)
    # CORS：允许前端跨域调用 /query 等接口；allow_origins 应从环境变量注入，
    # 默认为回环，避免开发期浏览器被阻断的同时不暴露给任意来源。
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            o.strip()
            for o in (get_settings().cors_allow_origins or "http://127.0.0.1:5173").split(",")
            if o.strip()
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # ADR-0007 A3: 入站租户身份断言中间件（observe 默认：有 Bearer 则验签绑定 tenant，
    # 无凭据交下游既有 provided>default 语义 → 零行为变更；配 TENANT_JWT_PUBLIC_KEYS_FILE/SINGLE_TENANT 后激活）。
    app.add_middleware(IdentityMiddleware)
    app.include_router(router)
    return app


app = create_app()
