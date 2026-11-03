"""探针 D：存量的 uuid4 回退行，会不会永久遮蔽后续按 uuid6 写入的新行？

问题由来：若按「每轮写新 id（uuid6）」修缺口 A，那么历史上已经写入的
`revert.py` uuid4 行（首 4 位十六进制均匀分布，绝大多数概率 > 当前 v6 前缀 `1f1d`）
在字典序上**恒大于**今后任何 v6 id ⇒ 读侧 `max()` 永远返回那条旧回退行，
线程**冻结在回退点**。若成立，则"修 A"必须同时处置存量行，否则是回归。

姿势纪律（本会话已两次因违反它作废读数）：
- 回退行**由产品函数 `RevertHandler.revert` 造**，不手写；
- 「未来的每轮写入」产品代码还不存在，只能手写 aput ⇒ 必须带**双自检**：
  ① 按指定 id 精确读回该行，内容末条 == 本轮 marker（证明这行真的落下去了）；
  ② 读侧最新 id 与写入 id 分开报（不拿"最新"当"我写的那行"）。
  第一版探针 D 漏了 `ck["id"] = ck_id`，写成原地覆写，靠"回退行 id == 目标 id"
  这个刺眼读数暴露——所以这里把两条自检都写成断言级外显，而不是只打印。
"""

import asyncio
import uuid

from agent_core.memory import get_checkpointer
from agent_runtime.revert import RevertHandler
from agent_server.memory import thread_persist
from langchain_core.messages import AIMessage
from langgraph.checkpoint.base.id import uuid6


def _cfg(tid, ck_id=None):
    c = {"thread_id": tid, "checkpoint_ns": ""}
    if ck_id:
        c["checkpoint_id"] = ck_id
    return {"configurable": c}


def msgs_of(tpl):
    return (tpl.checkpoint.get("channel_values") or {}).get("messages", []) or []


async def latest(cp, tid):
    return await cp.aget_tuple(_cfg(tid))


async def write_row_checked(cp, tid, ck_id, marker):
    """按 append_thread 的姿势写一条**换新 id** 的行，并做双自检。

    返回 (row_landed, latest_id, latest_is_new_row)。
    row_landed = 按 ck_id 精确读回，且末条内容 == marker（行确实落下去、内容对）。
    """
    base = await latest(cp, tid)
    base_id = base.checkpoint["id"]
    ck = dict(base.checkpoint)
    ck["id"] = ck_id  # ← 第一版漏了这一行，导致原地覆写
    cv = dict(ck.get("channel_values", {}))
    msgs = list(cv.get("messages", []))
    msgs.append(AIMessage(content=marker, id=str(uuid.uuid4())))
    cv["messages"] = msgs
    versions = dict(ck.get("channel_versions", {}))
    versions["messages"] = versions.get("messages", 0) + 1
    ck["channel_values"] = cv
    ck["channel_versions"] = versions
    md = dict(base.metadata or {})
    md.setdefault("checkpoint_ns", "")
    await cp.aput(_cfg(tid, ck_id), ck, md, {"messages": versions["messages"]})

    at_id = await cp.aget_tuple(_cfg(tid, ck_id))
    row_landed = at_id is not None and at_id.checkpoint["id"] == ck_id and (
        getattr(msgs_of(at_id)[-1], "content", None) if msgs_of(at_id) else None
    ) == marker
    got = await latest(cp, tid)
    return row_landed, got.checkpoint["id"], (got.checkpoint["id"] == ck_id), base_id


async def make_poisoned_thread(cp, idx, max_tries=200):
    """用产品函数造一个「回退行在字典序上赢了」的线程（现写法多数情况一次成功）。"""
    for k in range(max_tries):
        tid = f"probeD-poison-{idx}-{k}"
        await thread_persist.append_thread(cp, tid, "Q1", "A1-原始")
        target = (await latest(cp, tid)).checkpoint["id"]
        await RevertHandler(cp).revert(operator="probeD", session_id=tid, checkpoint_id=target)
        now = (await latest(cp, tid)).checkpoint["id"]
        if now != target and uuid.UUID(now).version == 4:
            return tid, target, now
    raise AssertionError("200 次都没造出「回退行胜出」的线程，样本异常")


async def main():
    cp = get_checkpointer()
    print(f"checkpointer class = {type(cp).__name__}")

    tid, target, poison = await make_poisoned_thread(cp, 0)
    print(f"\n== 1) 产品路径造出的「已回退」线程 {tid} ==")
    print(f"   目标(v6)        = {target}")
    print(f"   revert 新行(v4) = {poison}  ⇒ 读侧最新 = {poison}（回退行已遮蔽目标）")

    print("\n== 2) 此后按「每轮写新 uuid6」连写 3 轮（模拟修好 A 之后的形态） ==")
    for i in range(1, 4):
        new_id = str(uuid6())
        landed, got, is_new, _base = await write_row_checked(cp, tid, new_id, f"第 {i} 轮新回答")
        assert landed, f"自检失败：按 {new_id} 读不回本轮内容，读数作废"
        print(f"   写 {new_id} (v{uuid.UUID(new_id).version})")
        print(f"     行已落地（精确读回内容对）= {landed}")
        print(f"     读侧最新 = {got}  ⇒ 新行成为最新 = {is_new}；仍停在 uuid4 回退行 = {got == poison}")

    rows = [t.checkpoint["id"] async for t in cp.alist(_cfg(tid))]
    print(f"\n== 3) 该线程 alist 共 {len(rows)} 行，字典序首位 = {rows[0]}")
    print(f"   结论：uuid4 回退行永久遮蔽后续 v6 写入 = {rows[0] == poison}")
    print(f"   行数 1 → {len(rows)}（回退 1 行 + 本轮 3 行 + 原目标 1 行 = 5）")

    print("\n== 4) 对照：回退行若用 uuid6（推荐修法），同样连写会不会被遮蔽 ==")
    tid2 = "probeD-uuid6-revert"
    await thread_persist.append_thread(cp, tid2, "Q1", "A1-原始")
    t2 = (await latest(cp, tid2)).checkpoint["id"]
    rev6 = str(uuid6())
    landed_a, got_a, is_new_a, _ = await write_row_checked(cp, tid2, rev6, "A1-回退后(uuid6)")
    assert landed_a, "自检失败：uuid6 回退行没落地"
    print(f"   目标 = {t2}")
    print(f"   回退行 = {rev6}  ⇒ 读侧最新 = {got_a}  ⇒ 回退行成为最新 = {is_new_a}")
    nxt = str(uuid6())
    landed_b, got_b, is_new_b, _ = await write_row_checked(cp, tid2, nxt, "之后一轮")
    assert landed_b, "自检失败：后续行没落地"
    print(f"   之后写 {nxt} ⇒ 读侧最新 = {got_b}  ⇒ 新行胜出 = {is_new_b}")
    print("   ⇒ 同族 id（v6 vs v6）时按写入序单调，无遮蔽")


if __name__ == "__main__":
    asyncio.run(main())
