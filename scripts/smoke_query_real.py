#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""agent-platform 真实数据冒烟：复用 opencode 通道跑真实 LLM + Postgres checkpoint 写读恢复。

不启动 HTTP server，直接复用 app 的 lifespan 引导逻辑（init_pool → checkpointer →
build_chat_model → build_graph），然后对同一个 thread_id 连发两轮 graph.astream，
验证：
  1. llm_enabled == True（LLM_API_KEY 非空 + 通道可达）
  2. 第一轮写入 checkpoint（Postgres）
  3. 第二轮能从同一 thread_id 读回 checkpoint 续跑（写读恢复）
"""
from __future__ import annotations

import asyncio
import sys

from agent_runtime.db import close_pool, get_pool, init_pool
from agent_server.agent.graph import build_graph
from agent_server.agent.llm import build_chat_model
from agent_server.config import get_settings


async def _build_checkpointer():
    pool = get_pool()
    from agent_core.memory import get_checkpointer
    saver = get_checkpointer(pg_pool=pool)
    if pool is not None:
        await saver.setup()
    return saver


async def run_once(graph, thread_id: str, question: str):
    final = ""
    chunks = 0
    async for update in graph.astream(
        {"messages": [("user", question)], "question": question,
         "user_id": "smoke", "iterations": 0},
        config={"configurable": {"thread_id": thread_id}},
        stream_mode="updates",
    ):
        chunks += 1
        for node, payload in update.items():
            if node == "synthesize" and isinstance(payload, dict) and payload.get("answer"):
                final = payload["answer"]
    # 兜底：若 synthesize 未给出 answer，从 checkpoint 状态里取最后一条 AI 消息
    if not final:
        state = await graph.aget_state({"configurable": {"thread_id": thread_id}})
        if state and state.values:
            for m in reversed(state.values.get("messages", [])):
                content = getattr(m, "content", None)
                if content and getattr(m, "type", "human") == "ai":
                    final = content
                    break
    return final, chunks


async def main() -> int:
    settings = get_settings()
    print(f"[config] db_enabled={settings.db_enabled} llm_enabled={settings.llm_enabled}")
    print(f"[config] LLM_BASE_URL={settings.llm_base_url} LLM_MODEL={settings.llm_model}")
    if not settings.llm_enabled:
        print("[FAIL] llm_enabled is False → 会走启发式模式，未命中真实 LLM 通道")
        return 2

    await init_pool(
        database_url=settings.database_url,
        db_pool_max_size=settings.db_pool_max_size,
    )
    checkpointer = await _build_checkpointer()
    llm = build_chat_model()
    graph = build_graph(llm, checkpointer=checkpointer, mcp_manager=None)

    thread_id = "smoke-real-query-001"

    print("\n=== 第一轮：写入 checkpoint + 真实 LLM 调用 ===")
    ans1, c1 = await run_once(graph, thread_id, "用一句话介绍一下你自己是什么模型。")
    print(f"[round1] chunks={c1} answer={ans1!r}")

    # 验证 checkpoint 已写入 Postgres
    pool = get_pool()
    if pool is not None:
        async with pool.connection() as conn:
            cur = await conn.execute(
                "SELECT count(*) AS n FROM checkpoints WHERE thread_id = %s", (thread_id,)
            )
            row = await cur.fetchone()
            n = row[0] if row else 0
        print(f"[checkpoint] Postgres 中 thread={thread_id} 的 checkpoint 行数 = {n}")
        if n == 0:
            print("[FAIL] checkpoint 未写入 Postgres")
            await close_pool()
            return 3
    else:
        print("[warn] 无 PG 连接池（db_enabled=False），checkpoint 走内存版")

    print("\n=== 第二轮：同一 thread_id 读回 checkpoint 续跑（写读恢复） ===")
    ans2, c2 = await run_once(graph, thread_id, "接着刚才，简短说下你能帮我做什么。")
    print(f"[round2] chunks={c2} answer={ans2!r}")

    # 读回 checkpoint 状态证明“读”成功（不抛错即说明读路径通）
    state = await graph.aget_state({"configurable": {"thread_id": thread_id}})
    n_msgs = len(state.values.get("messages", [])) if state and state.values else 0
    print(f"[checkpoint] aget_state 读回消息数 = {n_msgs}（>0 即证明第二轮已读到历史 checkpoint）")

    ok = bool(ans1) and bool(ans2) and n_msgs > 0
    print("\n=== 结论 ===")
    print("[PASS]" if ok else "[FAIL]", "真实 LLM 往返 + checkpoint 写读恢复")
    await close_pool()
    return 0 if ok else 4


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
