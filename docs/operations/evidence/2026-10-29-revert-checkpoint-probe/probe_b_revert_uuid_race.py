"""探针 B：revert 写入的 uuid4 行，有多少比例能成为「最新态」？

事实基线（源码，非推测）：
- `langgraph/checkpoint/memory/__init__.py` InMemorySaver.get_tuple 无 id 分支：
  `checkpoint_id = max(checkpoints.keys())` ⇒ 「最新」= checkpoint_id **字典序最大**。
- `agent_runtime/revert.py:77` 新行 id = `str(uuid.uuid4())`（随机），
  而 LangGraph 自身产出的 id 是时序 UUIDv6（如 `1f1d35ce-…`，version=6）。
- `applications/agent_federation/agent/checkpoint_cleaner.py:36` 注释：
  「checkpoint_id 为 uuid.hex，字典序即写入序，sort(-1) 取最新」⇒ 同一假设。

写法纪律：全程只调产品函数（append_thread / RevertHandler.revert），
不手写 aput（本会话先前的一个手写 aput 探针因把全部 channel_versions 当 new_versions
传入而覆盖了共享 blob，读数作废，未入库；revert.py 自己传 new_versions={} 是正确的）。
"""

import asyncio
import uuid

from agent_core.memory import get_checkpointer
from agent_runtime.revert import RevertHandler
from agent_server.memory import thread_persist


async def latest(cp, tid):
    tpl = await cp.aget_tuple({"configurable": {"thread_id": tid, "checkpoint_ns": ""}})
    return tpl.checkpoint["id"]


async def reverted_rows(cp, tid):
    """alist 里 metadata 带 reverted_from 的行 = revert 写的新行。"""
    out = []
    async for tpl in cp.alist({"configurable": {"thread_id": tid, "checkpoint_ns": ""}}):
        if (tpl.metadata or {}).get("reverted_from"):
            out.append(tpl.checkpoint["id"])
    return out


async def one_trial(idx: int):
    """一轮：主路径写一次 → revert 回该 checkpoint → 看新行是否成为最新。"""
    cp = get_checkpointer()
    tid = f"probe3-{idx}"
    await thread_persist.append_thread(cp, tid, "Q", "A")
    target = await latest(cp, tid)
    res = await RevertHandler(cp).revert(operator="probe3", session_id=tid, checkpoint_id=target)
    rows = await reverted_rows(cp, tid)
    new_id = rows[0] if rows else None
    got = await latest(cp, tid)
    return {
        "target_ver": uuid.UUID(target).version,
        "new_ver": uuid.UUID(new_id).version if new_id else None,
        "success": res.success,
        "became_latest": got == new_id,
        "target_id_prefix": target[:4],
        "new_id_prefix": (new_id or "")[:4],
    }


async def main():
    n = 60
    trials = [await one_trial(i) for i in range(n)]

    wins = sum(1 for t in trials if t["became_latest"])
    oks = sum(1 for t in trials if t["success"])
    vers_t = {t["target_ver"] for t in trials}
    vers_n = {t["new_ver"] for t in trials}

    print(f"样本 n={n}")
    print(f"revert 返回 success=True 的条数 = {oks}")
    print(f"其中「新行成为最新态」= {wins}/{n} = {wins / n:.1%}")
    print(f"★ 静默失效（success=True 但读侧没换）= {oks - wins} 条 = {(oks - wins) / n:.1%}")
    print(f"目标 checkpoint 的 uuid version 集合 = {vers_t}（时序）")
    print(f"revert 新行 uuid version 集合 = {vers_n}（随机）")
    print("\n前 8 轮样例（target_id 前缀 vs new_id 前缀，字典序大者胜）：")
    for i, t in enumerate(trials[:8]):
        print(
            f"  {i}: {t['target_id_prefix']} vs {t['new_id_prefix']} → "
            f"became_latest={t['became_latest']}"
        )

    print("\n== 附：同一 thread 连续两轮 revert 后，读侧看到的是哪一条 ==")
    cp = get_checkpointer()
    tid = "probe3-chain"
    await thread_persist.append_thread(cp, tid, "Q1", "A1")
    first = await latest(cp, tid)
    # 主路径每线程只有一条 checkpoint（探针 A 已证），所以 revert 行就是该线程的第二条
    await RevertHandler(cp).revert(operator="probe3", session_id=tid, checkpoint_id=first)
    rows = await reverted_rows(cp, tid)
    print(f"  thread 内 revert 行数 = {len(rows)}，checkpoint 总数按 alist = "
          f"{len([1 async for _ in cp.alist({'configurable': {'thread_id': tid, 'checkpoint_ns': ''}})])}")
    print(f"  当前读侧最新 = {await latest(cp, tid)}；目标 = {first}；revert 行 = {rows}")


if __name__ == "__main__":
    asyncio.run(main())
