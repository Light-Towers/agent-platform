"""探针 A：Planner 主路径到底会不会累积 checkpoint（即：有没有「历史点」可回退）？

只读性质：不启服务、不写库，只在内存 checkpointer 上跑真实产品代码
`thread_persist.append_thread` + `agent_runtime.revert`，读数用于定方案。
"""

import asyncio
import uuid

from agent_core.memory import get_checkpointer
from agent_runtime.revert import RevertHandler
from agent_server.memory import thread_persist


async def list_cps(cp, thread_id):
    """走 LangGraph 稳定接口 alist（三种 saver 都实现）。"""
    cfg = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    out = []
    async for tpl in cp.alist(cfg):
        ck = tpl.checkpoint
        msgs = ck.get("channel_values", {}).get("messages", []) or []
        out.append((ck["id"], len(msgs)))
    return out


async def main():
    cp = get_checkpointer()
    print(f"checkpointer class = {type(cp).__name__}")

    tid = "probe-planner-path"
    print("\n== 1) Planner 主路径：连续两轮 append_thread（产品代码原样调用）==")
    await thread_persist.append_thread(cp, tid, "Q1 第一轮提问", "A1 第一轮回答")
    r1 = await list_cps(cp, tid)
    print(f"  第 1 轮后 alist = {r1}")

    await thread_persist.append_thread(cp, tid, "Q2 第二轮提问", "A2 第二轮回答")
    r2 = await list_cps(cp, tid)
    print(f"  第 2 轮后 alist = {r2}")
    print(f"  checkpoint 条数 1 轮={len(r1)} → 2 轮={len(r2)}")
    print(f"  id 是否相同 = {r1 and r2 and r1[0][0] == r2[0][0]}")

    latest = await cp.aget_tuple({"configurable": {"thread_id": tid, "checkpoint_ns": ""}})
    msgs = latest.checkpoint.get("channel_values", {}).get("messages", []) or []
    print(f"  最新 checkpoint 内 messages 条数 = {len(msgs)}（两轮都还在 ⇒ /history 正常）")

    print("\n== 2) 该线程有几个可回退点（= alist 条数） ==")
    print(f"  可回退点 = {len(r2)} 个，且它是「当前最新态」⇒ 回退目标只能是它自己")

    print("\n== 3) 对它执行 revert，看是否产生新 checkpoint ==")
    handler = RevertHandler(cp)
    res = await handler.revert(operator="probe", session_id=tid, checkpoint_id=r2[0][0])
    print(f"  revert success={res.success} error={res.error!r} new_cp={res.checkpoint_id!r}")
    r3 = await list_cps(cp, tid)
    print(f"  revert 后 alist = {r3}")
    print(f"  条数变化 {len(r2)} → {len(r3)}")

    print("\n== 4) 对照：写入时换新 id（revert.py 的做法）会不会累积成新行 ==")
    tid2 = "probe-newid"
    await thread_persist.append_thread(cp, tid2, "Q1", "A1")
    base = await cp.aget_tuple({"configurable": {"thread_id": tid2, "checkpoint_ns": ""}})

    ck = dict(base.checkpoint)
    ck["id"] = str(uuid.uuid4())
    md = dict(base.metadata or {})
    md.setdefault("checkpoint_ns", "")
    await cp.aput(
        {"configurable": {"thread_id": tid2, "checkpoint_ns": ""}},
        ck,
        md,
        dict(ck.get("channel_versions", {})),
    )
    r4 = await list_cps(cp, tid2)
    print(f"  换 id 后 alist = {[(i, n) for i, n in r4]} ⇒ 条数 {len(r4)}")


if __name__ == "__main__":
    asyncio.run(main())
