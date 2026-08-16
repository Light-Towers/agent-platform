import shutil
from pathlib import Path

from agent_core.logging import get_logger
from agent_core.tracing import start_span

logger = get_logger(__name__)

import os

from deepagents import create_deep_agent

from agent.async_subagents import get_remote_subagents
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


async def _create_checkpointer():
    """创建 checkpointer。

    使用 InMemorySaver：纯内存、同步/异步均可（提供 aget_tuple/aput_writes），
    无需 SQLite 连接或异步上下文管理器，可被全局缓存的 agent 安全复用。
    """
    try:
        from langgraph.checkpoint.memory import InMemorySaver
        return InMemorySaver()
    except ImportError:
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        saver = AsyncSqliteSaver.from_conn_string(":memory:")
        await saver.__aenter__()
        return saver


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


async def get_main_agent():
    global _main_agent
    if _main_agent is None:
        logger.info("初始化 main_agent（懒加载）")

        _system_prompt = main_agent_content['system_prompt']
        if os.getenv("PLANNER_ENABLED", "false").lower() == "true" and planner_content:
            _addition = planner_content.get("planner", {}).get("system_prompt_addition", "")
            if _addition:
                _system_prompt = _system_prompt + "\n\n" + _addition

        _main_agent = create_deep_agent(
            model=model,
            system_prompt=_system_prompt,
            tools=[generate_markdown, convert_md_to_pdf, read_file_content],
            checkpointer=await _create_checkpointer(),
            subagents=_build_subagents(),
            middleware=_build_middleware(),
        )
    return _main_agent


project_root_path = Path(__file__).parents[1].resolve()


@langfuse_observe(name="agent.run", as_type="span")
async def run_deep_agent(task_query, session_id):
    with start_span("agent.run", attrs={"session_id": session_id, "query_len": len(task_query)}):
        logger.info("开始执行 main_agent session_id=%s", session_id)

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
                from agent.intent.classifier import is_chitchat
                from agent.intent.llm_judge import classify_with_fallback

                if is_chitchat(task_query):
                    logger.info("L1 short-circuit: chitchat 直出")
                    monitor.report_task_result(task_query)
                    monitor._emit('intent', {"intent": "chitchat", "source": "l1_short_circuit"})
                    return

                intent_result = await classify_with_fallback(task_query)
                _cached_intent = intent_result["primary"]["intent"]
                monitor._emit('intent', {
                    "intent": intent_result["primary"]["intent"],
                    "confidence": intent_result["primary"]["confidence"],
                    "source": intent_result["source"],
                })

                if intent_result.get("need_clarify"):
                    clarify_msg = f"您是想查询{intent_result['candidates'][0]['intent']}还是{intent_result['candidates'][1]['intent']}相关的内容呢？请具体描述一下您的需求。"
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

        session_dir = project_root_path / "output" / f"session_{session_id}"
        session_dir.mkdir(parents=True, exist_ok=True)
        session_dir_str = str(session_dir).replace("\\", "/")
        relative_session_dir_str = str(session_dir.relative_to(project_root_path)).replace("\\", "/")

        updated_dir_path = project_root_path / "updated" / f"session_{session_id}"
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
        session_id_token = set_thread_context(session_id)
        monitor.report_session_dir(session_dir_str)

        config = {"configurable": {"thread_id": session_id}}

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

        main_agent = await get_main_agent()
        try:
            async for chunk in main_agent.astream(
                {"messages": [{"role": "user", "content": task_query + path_instruction}]},
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
                                _final_answer = last_msg.content
                                if os.getenv("GUARD_ENABLED", "false").lower() == "true":
                                    try:
                                        from gateway.output_guard import guard_output
                                        _og = guard_output(_final_answer)
                                        if not _og["safe"]:
                                            logger.warning("输出 guardrail 拦截: pii=%s", _og["pii_leaked"])
                                    except Exception:
                                        pass
                                monitor.report_task_result(last_msg.content)
        except Exception as e:
            logger.exception("main_agent 执行异常 session_id=%s", session_id)
            monitor.report_error(f"执行主智能发生异常信息：{str(e)}")
        finally:
            if _cache_hit is None and _final_answer and os.getenv("CACHE_ENABLED", "false").lower() == "true":
                try:
                    from agent.cache.semantic_cache import SemanticCache
                    await SemanticCache.set_async(
                        _cached_intent, task_query,
                        {"answer": _final_answer, "trace_id": session_id},
                    )
                except Exception:
                    pass
            reset_session_context(session_dir_token, session_id_token)
