import asyncio
import shutil
from pathlib import Path

from agent_core.logging import get_logger
from agent_core.tracing import start_span

logger = get_logger(__name__)

import os

from deepagents import create_deep_agent

from agent.async_subagents import get_remote_subagents
from agent.cache.config import get_cache_config
from agent.cache.layers import _build_cache_key
from agent.cache.singleflight import singleflight
from agent.config import is_remote_mode
from agent.llm import model
from agent.prompts import main_agent_content, planner_content
from agent.subagents.database_query_agent import database_query_agent
from agent.subagents.knowledge_base_agent import knowledge_base_agent
from agent.subagents.network_search_agent import network_search_agent
from agent.tracing.langfuse_adapter import langfuse_observe
from api.context import reset_session_context, set_session_context, set_thread_context
from api.monitor import monitor
from tools.markdown_tools import generate_markdown
from tools.pdf_tools import convert_md_to_pdf
from tools.upload_file_read_tool import read_file_content

_main_agent = None
_main_agent_lock = asyncio.Lock()  # P1.1/1.4：保护 _main_agent 构造，防并发首请求重复构造
_main_checkpointer = None  # 缓存 get_main_agent 构造出的 checkpointer，供 checkpoint_cleaner 复用
_main_store = None  # 缓存 get_main_agent 构造出的长期记忆 store（P2.2）

# P1.6：per-thread_id 互斥锁 + 引用计数清理（避免锁对象生命周期 Bug）
_thread_locks: dict[str, asyncio.Lock] = {}
_thread_refcount: dict[str, int] = {}


# 阶段2 收尾：main_agent 推理流程接入类型化记忆（ADR-0004）。
# 接线逻辑独立到 agent.memory.main_agent_memory 以隔离重依赖（llm/langgraph）。
from agent.memory.main_agent_memory import (
    recall_typed_context,
    remember_episodic,
)


async def _create_checkpointer():
    """创建 checkpointer（会话历史持久化）。

    统一委托 agent-core 的 ``get_checkpointer`` 工厂（与 embedder 的
    ``get_embedder`` 同一收口模式）：
      1. 配置 ``MONGO_URL`` → ``MongoCheckpointer``（持久化到 MongoDB，重启不丢，
         按 ``tenant_id`` 隔离）。生产推荐。
      2. 否则降级 ``InMemorySaver``（纯内存，重启丢，开发/无 Mongo 环境）。
    """
    from agent_core.memory import get_checkpointer

    return get_checkpointer()


async def _create_store():
    """P2.2：构建长期记忆 store（跨会话语义检索）。

    收口到 langgraph.store，与 checkpointer 同工厂模式：
      1. 配置 ``STORE_POSTGRES_DSN`` → ``PostgresStore``（pgvector 索引 + bge 嵌入，
         持久化到 Postgres，跨会话语义检索，重启不丢）。生产推荐。
      2. 否则降级 ``InMemoryStore``（纯内存，重启丢，开发/无 PG 环境）。
    """
    from langgraph.store.memory import InMemoryStore

    dsn = os.getenv("STORE_POSTGRES_DSN", "")
    if dsn:
        from langgraph.store.postgres import PostgresStore
        from langgraph.store.postgres.base import PostgresIndexConfig

        async def _bge_embed(texts: list[str]) -> list[list[float]]:
            """用 agent-core 的 bge 嵌入，对齐 PostgresStore 索引维度。"""
            from agent_core.memory.embedder import get_embedder
            return get_embedder().embed(texts)

        _dims = None
        try:
            from agent_core.memory.embedder import get_embedder
            _dims = getattr(get_embedder(), "dim", None)
        except Exception:
            _dims = None
        _dims = int(_dims or int(os.getenv("STORE_EMBED_DIMS", "512")))

        # 语义记忆命名空间：按 (tenant, thread) 组织；向量索引用 bge 维度。
        store = PostgresStore.from_conn_string(
            dsn,
            index=PostgresIndexConfig(
                embed=_bge_embed,
                dims=_dims,
                fields=["content"],
            ),
        )
        logger.info("长期记忆 store：PostgresStore（pgvector + bge %d 维）", _dims)
        return store
    logger.info("长期记忆 store：InMemoryStore（无 STORE_POSTGRES_DSN，开发态）")
    return InMemoryStore(index=None)


def _build_subagents():
    """根据 AGENT_MODE 构建 subagents 列表。

    remote 模式：3 个 AsyncSubAgent（Agent Protocol 连接子服务）
    local 模式：3 个本地 SubAgent（现有行为，默认）
    """
    if is_remote_mode():
        logger.info("AGENT_MODE=remote，使用远程 AsyncSubAgent")
        return get_remote_subagents()
    logger.info("AGENT_MODE=local，使用本地 SubAgent")
    return [
        database_query_agent,
        network_search_agent,
        knowledge_base_agent,
    ]


def _build_middleware():
    """Phase 4：构建 middleware 列表（TodoListMiddleware + RubricMiddleware + GuardMiddleware）。

    PLANNER_ENABLED=true → TodoListMiddleware（思考规划）
    REFLEXION_ENABLED=true → RubricMiddleware（Reflexion 自评估迭代）
    GUARD_ENABLED=true → GuardMiddleware（输入护栏：PII 脱敏 + injection 检测，优化 B 要点2）
    三者都可独立开关，失败时降级为空列表（不影响现有栈）。
    """
    middleware = []

    if os.getenv("GUARD_ENABLED", "false").lower() == "true":
        try:
            from deepagents.gateway.guard_middleware import GuardMiddleware

            middleware.append(GuardMiddleware())
            logger.info("GuardMiddleware 已启用（输入护栏挂入 deepagents 栈）")
        except Exception as e:
            logger.warning("GuardMiddleware 启用失败: %s", e)

    if os.getenv("PLANNER_ENABLED", "false").lower() == "true":
        try:
            from langchain.agents.middleware import TodoListMiddleware

            planner_prompt = ""
            if planner_content and "planner" in planner_content:
                planner_prompt = planner_content["planner"].get("system_prompt_addition", "")

            middleware.append(TodoListMiddleware())
            logger.info("TodoListMiddleware 已启用（planner_prompt=%d chars）", len(planner_prompt))
        except Exception as e:
            logger.warning("TodoListMiddleware 启用失败: %s", e)

    if os.getenv("REFLEXION_ENABLED", "false").lower() == "true":
        try:
            from deepagents.middleware import RubricMiddleware

            rubric_prompt = None
            max_iter = 3
            if planner_content and "rubric" in planner_content:
                rubric_prompt = planner_content["rubric"].get("system_prompt")
                max_iter = planner_content["rubric"].get("max_iterations", 3)

            middleware.append(RubricMiddleware(
                model=model,
                system_prompt=rubric_prompt,
                max_iterations=max_iter,
            ))
            logger.info("RubricMiddleware 已启用（max_iterations=%d）", max_iter)
        except Exception as e:
            logger.warning("RubricMiddleware 启用失败: %s", e)

    return middleware if middleware else None


async def get_main_agent(checkpointer=None):
    """返回单例 main_agent。

    P1.1/1.4：用 ``_main_agent_lock`` 保护构造，消除并发首请求的重复构造竞态。
    ``checkpointer`` 由 lifespan 预初始化阶段注入（规划 1.1/1.2）；为 None 时
    回退到 ``_create_checkpointer()``（Mongo/InMemory），保证本地无 PG 测试态可跑。
    """
    global _main_agent, _main_store
    if _main_agent is not None:
        return _main_agent
    async with _main_agent_lock:
        # 双重检查：持锁后可能已被其他协程构造完成
        if _main_agent is not None:
            return _main_agent
        logger.info("初始化 main_agent（lifespan 预初始化 或 首次懒加载）")

        _system_prompt = main_agent_content['system_prompt']
        if os.getenv("PLANNER_ENABLED", "false").lower() == "true" and planner_content:
            _addition = planner_content.get("planner", {}).get("system_prompt_addition", "")
            if _addition:
                _system_prompt = _system_prompt + "\n\n" + _addition

        # P2.2：长期记忆说明（跨部门/跨会话语义检索能力的提示注入）
        _system_prompt = _system_prompt + (
            "\n\n# 长期记忆\n"
            "你具备跨会话的长期记忆（语义记忆 + 情景记忆）。历史任务沉淀的要点可在后续"
            "会话中经语义检索复用，无需用户重复提供背景。涉及用户偏好、项目背景、反复出现的"
            "领域知识时，主动利用长期记忆以保持连续性与一致性。"
        )

        # P3.3：子 Agent 失败处理策略（主管如何应对委派降级/不可用）
        _system_prompt = _system_prompt + (
            "\n\n# 子 Agent 委派失败处理策略\n"
            "当子服务（数据分析 / 知识库 / 客服）探活不健康、触发熔断或远程调用失败时，"
            "平台会自动降级：要么路由到本地兜底子 Agent，要么返回带 `degraded: true` 的降级回答。"
            "此时你应注意：\n"
            "1. 若子 Agent 返回内容含 `degraded` 标记，应如实告知用户该部分结果来自降级路径，"
            "可能不完整或未经远程服务校验，请用户稍后重试或补充背景。\n"
            "2. 不要对降级结果过度承诺；能基于本地/通用知识直接回答的，优先直接作答并标注不确定性。\n"
            "3. 仅在确有必要时才依赖子 Agent 的硬性数据；无法确认时主动说明限制，避免编造。"
        )

        _cp = checkpointer if checkpointer is not None else await _create_checkpointer()
        _main_checkpointer = _cp
        _store = await _create_store()
        _main_store = _store
        _main_agent = create_deep_agent(
            model=model,
            system_prompt=_system_prompt,
            tools=[generate_markdown, convert_md_to_pdf, read_file_content],
            checkpointer=_cp,
            store=_store,
            subagents=_build_subagents(),
            middleware=_build_middleware(),
        )
    return _main_agent


def get_main_checkpointer():
    """返回当前 main_agent 使用的 checkpointer（供 P1.3 定时清理复用）。"""
    return _main_checkpointer


def get_main_store():
    """返回当前 main_agent 使用的长期记忆 store（P2.2）。"""
    return _main_store


# P1.6：per-thread_id 互斥锁 + 引用计数清理
async def _get_thread_lock(thread_id: str) -> asyncio.Lock:
    """获取（或新建）指定 thread_id 的串行锁，并递增引用计数。"""
    lock = _thread_locks.get(thread_id)
    if lock is None:
        lock = asyncio.Lock()
        _thread_locks[thread_id] = lock
        _thread_refcount[thread_id] = 0
    _thread_refcount[thread_id] += 1
    return lock


def _release_thread_lock(thread_id: str) -> None:
    """引用计数减一，归零时清理锁，避免锁对象无限堆积。"""
    _thread_refcount[thread_id] = _thread_refcount.get(thread_id, 1) - 1
    if _thread_refcount[thread_id] <= 0:
        _thread_locks.pop(thread_id, None)
        _thread_refcount.pop(thread_id, None)


project_root_path = Path(__file__).parents[1].resolve()


@langfuse_observe(name="agent.run", as_type="span")
async def run_deep_agent(task_query, workspace_id):
    # 隔离策略（与全局一致）：统一以 workspace_id 作为类型化记忆隔离主键。
    # deepagents 单进程单池，一个 thread_id 即代表一个 workspace 工作空间，
    # 调用方（api/server、eval）传入的即该 workspace 的稳定标识。
    with start_span("agent.run", attrs={"workspace_id": workspace_id, "query_len": len(task_query)}):
        logger.info("开始执行 main_agent workspace_id=%s", workspace_id)

        # Phase 6：输入 guardrail（PII 脱敏 + injection 检测）
        if os.getenv("GUARD_ENABLED", "false").lower() == "true":
            try:
                from gateway.input_guard import guard_input
                guard_result = guard_input(task_query)
                if guard_result["blocked"]:
                    logger.warning("输入被 guardrail 拦截: injection=%s", guard_result["injection_pattern"])
                    monitor.report_task_result("抱歉，您的输入包含不安全的内容，请重新描述。")
                    return
                task_query = guard_result["redacted_text"]
                if guard_result["pii_types"]:
                    logger.info("PII 已脱敏: %s", guard_result["pii_types"])
            except Exception as e:
                logger.warning("输入 guardrail 失败（非致命）: %s", e)

        # Phase 3：意图识别 + short-circuit
        _cached_intent = "unknown"
        intent_config = os.getenv("INTENT_ENABLED", "false").lower() == "true"
        if intent_config:
            try:
                from agent_core.intent import classify_intent, is_chitchat

                if is_chitchat(task_query):
                    logger.info("L1 short-circuit: chitchat 直出")
                    monitor.report_task_result(task_query)
                    monitor._emit('intent', {"intent": "chitchat", "source": "l1_short_circuit"})
                    return

                intent_result = await classify_intent(task_query)
                _cached_intent = intent_result.primary.value
                monitor._emit('intent', {
                    "intent": intent_result.primary.value,
                    "confidence": intent_result.confidence,
                    "source": intent_result.source,
                })

                if intent_result.need_clarify and len(intent_result.candidates) >= 2:
                    c0 = intent_result.candidates[0].intent.value
                    c1 = intent_result.candidates[1].intent.value
                    clarify_msg = f"您是想查询{c0}还是{c1}相关的内容呢？请具体描述一下您的需求。"
                    monitor.report_task_result(clarify_msg)
                    return

                # Query 改写
                from agent.rewrite.rewrite_node import rewrite_query
                rewritten = await rewrite_query(task_query)
                if rewritten != task_query:
                    task_query = rewritten
                    logger.info("Query 已改写: %s", rewritten)

            except Exception as e:
                logger.warning("意图识别/改写失败（非致命），继续走 LLM 路由: %s", e)

        # Phase 5：语义缓存查询
        _cache_hit = None
        _final_answer = ""
        if os.getenv("CACHE_ENABLED", "false").lower() == "true":
            try:
                from agent.cache.semantic_cache import SemanticCache
                _cache_hit = await SemanticCache.get(_cached_intent, task_query)
                if _cache_hit is not None:
                    logger.info("缓存命中（%s）: %s", _cache_hit.get("_layer", "?"), task_query[:50])
                    monitor.report_task_result(_cache_hit.get("answer", ""))
                    monitor._emit('cache', {"layer": _cache_hit.get("_layer"), "hit": True, **SemanticCache.get_stats()})
                    return
                monitor._emit('cache', {"layer": "miss", "hit": False})
            except Exception as e:
                logger.warning("缓存查询失败（非致命）: %s", e)

        # P4：缓存击穿防护。缓存 miss 后，用 singleflight 以 cache key 去重：
        # 同一 query 的并发请求只真正执行一次 Agent（LLM），其余等同一结果，
        # 避免热点 query 把 LLM/子服务打爆。cache key 与语义缓存一致（含 kb 版本/租户/灰度）。
        cache_key = _build_cache_key(
            _cached_intent, task_query,
            *(lambda c: (c.kb_versions, c.tenant_id, c.gray_pct))(get_cache_config())
            if os.getenv("CACHE_ENABLED", "false").lower() == "true"
            else ("", "", ""),
        )
        _final_answer = await singleflight(
            cache_key, _execute_agent_core, task_query, workspace_id,
        )

        # 统一收尾：监控上报 + 阶段2 记忆沉淀 + 语义缓存写入（无论是否经 singleflight 合并，
        # 每个 run_deep_agent 调用方都基于最终答案补齐自身指标与记忆，写入幂等无害）。
        if _final_answer:
            monitor.report_task_result(_final_answer)
            await remember_episodic(workspace_id, task_query, _final_answer)
            if _cache_hit is None and os.getenv("CACHE_ENABLED", "false").lower() == "true":
                try:
                    from agent.cache.semantic_cache import SemanticCache
                    await SemanticCache.set_async(
                        _cached_intent, task_query,
                        {"answer": _final_answer, "trace_id": workspace_id},
                    )
                except Exception:
                    pass


async def _execute_agent_core(task_query: str, workspace_id: str) -> str:
    """P4：Agent 核心执行（供 singleflight 去重包裹）。

    与 run_deep_agent 解耦：负责 session 目录准备、上下文注入、per-thread 串行锁、
    agent astream 执行并收集最终答案，**返回**最终答案字符串。流式过程中的子服务
    路由监控保留在此（仅真正执行的请求上报）；最终答案的统一监控上报/记忆沉淀/缓存
    写入由 run_deep_agent 在拿到结果后负责，避免 singleflight 合并时重复或缺失。

    Args:
        task_query: 经意图改写后的最终 query
        workspace_id: 工作空间/thread_id 标识

    Returns:
        最终答案；执行异常时返回空串（由调用方决定降级行为）
    """
    session_dir = project_root_path / "output" / f"session_{workspace_id}"
    session_dir.mkdir(parents=True, exist_ok=True)
    session_dir_str = str(session_dir).replace("\\", "/")
    relative_session_dir_str = str(session_dir.relative_to(project_root_path)).replace("\\", "/")

    updated_dir_path = project_root_path / "updated" / f"session_{workspace_id}"
    updated_info_prompt = ""
    if updated_dir_path.exists():
        files = [f.name for f in updated_dir_path.iterdir() if f.is_file()]
        if files:
            for filename in files:
                shutil.copy2(updated_dir_path / filename, session_dir / filename)
            updated_info_prompt = (
                "\n    [已上传文件] 已加载到工作目录:\n"
                + "\n".join([f"    - {f}" for f in files])
                + "\n    请优先使用工具（read_file_content）读取并参考这些文件。"
            )

    session_dir_token = set_session_context(session_dir_str)
    session_id_token = set_thread_context(workspace_id)
    monitor.report_session_dir(session_dir_str)

    config = {"configurable": {"thread_id": workspace_id}}

    path_instruction = f"""
    【工作环境指令】
    工作目录: {relative_session_dir_str}
    {updated_info_prompt}

    规则：
    1. 新生成文件必须保存到工作目录：'{relative_session_dir_str}/filename'
    2. 读取已上传的文件时，请直接将文件名作为 filename 参数传入（read_file_content）读取工具，不要带上任何目录前缀。
    3. 使用相对路径，禁止使用绝对路径
    4. 若存在上传文件，请先分析内容
    """

    memory_ctx = await recall_typed_context(workspace_id, task_query)

    final_answer = ""
    # P1.6：同一 workspace_id（thread_id）串行执行，避免并发撕裂 checkpointer 状态。
    lock = await _get_thread_lock(workspace_id)
    try:
        async with lock:
            main_agent = await get_main_agent()
            async for chunk in main_agent.astream(
                {"messages": [{"role": "user", "content": task_query + path_instruction + memory_ctx}]},
                config=config,
            ):
                for node_name, state in chunk.items():
                    if not state or "messages" not in state:
                        continue
                    messages = state["messages"]
                    if messages and isinstance(messages, list):
                        last_msg = messages[-1]
                        if node_name == 'model':
                            if last_msg.tool_calls:
                                for tool_call in last_msg.tool_calls:
                                    if tool_call['name'] == 'task':
                                        subagent_type = tool_call['args']['subagent_type']
                                        logger.info("委派子智能体: %s", subagent_type)
                                        monitor.report_assistant(
                                            subagent_type,
                                            {'description': tool_call['args']['description']}
                                        )
                                        if is_remote_mode():
                                            monitor._emit('subservice_route', {
                                                'subagent': subagent_type,
                                                'mode': 'remote',
                                                'description': tool_call['args']['description'],
                                            })
                                        else:
                                            monitor._emit('subservice_route', {
                                                'subagent': subagent_type,
                                                'mode': 'local',
                                                'description': tool_call['args']['description'],
                                            })
                            elif last_msg.content:
                                final_answer = last_msg.content
                                if os.getenv("GUARD_ENABLED", "false").lower() == "true":
                                    try:
                                        from gateway.output_guard import guard_output
                                        _og = guard_output(final_answer)
                                        if not _og["safe"]:
                                            logger.warning("输出 guardrail 拦截: pii=%s", _og["pii_leaked"])
                                    except Exception:
                                        pass
    except Exception as e:
        logger.exception("main_agent 执行异常 workspace_id=%s", workspace_id)
        monitor.report_error(f"执行主智能发生异常信息：{str(e)}")
    finally:
        reset_session_context(session_dir_token, session_id_token)
        _release_thread_lock(workspace_id)  # P1.6：归零清理锁

    return final_answer
