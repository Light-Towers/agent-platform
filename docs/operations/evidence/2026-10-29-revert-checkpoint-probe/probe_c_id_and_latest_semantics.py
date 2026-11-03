"""探针 C：checkpoint id 的生成器 + 三方 saver 的「最新」判定表达式（定修复形状）。

要回答四件事：
1. LangGraph 自己用什么生成 checkpoint id，连调 N 次是否**严格**字典序单调；
2. 候选 id 生成器（uuid4 现写法 / uuid6 推荐 / uuid_utils.uuid7）与
   **产品主路径实际写出的那个 id** 的字典序关系 —— 决定谁能在读侧胜出；
3. InMemorySaver / AsyncPostgresSaver / MongoCheckpointer 三处「取最新」的表达式；
4. PG 表里 checkpoint_id 的列类型（决定是字典序还是数值序）。

只读性质：不启服务、不写外部库（第 2 项用 InMemorySaver）。
"""

import asyncio
import inspect
import re
import uuid

import langgraph.checkpoint.base as cb
from agent_core.memory import get_checkpointer
from agent_server.memory import thread_persist
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.base.id import uuid6
from uuid_utils import uuid7  # langgraph 的传递依赖，本机可用（仅用于证伪，方案不新增它）

N = 1000


async def product_latest_id() -> str:
    """产品主路径（thread_persist.append_thread）实际写出的 checkpoint id。"""
    cp = get_checkpointer()
    tid = "probe-c-vs-product"
    await thread_persist.append_thread(cp, tid, "Q", "A")
    latest = await cp.aget_tuple({"configurable": {"thread_id": tid, "checkpoint_ns": ""}})
    return latest.checkpoint["id"]


def main():
    print("== 1) LangGraph 自己的 id 生成器 ==")
    src = inspect.getsource(cb)
    for line in src.splitlines():
        s = line.strip()
        if "uuid6" in s and (s.startswith(("import", "from")) or "id=" in s):
            print("   ", s[:150])

    c1, c2 = empty_checkpoint(), empty_checkpoint()
    print(f"   empty_checkpoint id1 = {c1['id']} (v{uuid.UUID(c1['id']).version})")
    print(f"   empty_checkpoint id2 = {c2['id']} (v{uuid.UUID(c2['id']).version})")
    print(f"   连续两次调用字典序递增 = {c2['id'] > c1['id']}")

    # 推荐修法靠的正是"连调单调"这条，两次不够 ⇒ 连取 N 个验严格单调
    seq = [str(uuid6()) for _ in range(N)]
    print(f"   连调 uuid6() N={N}（不带 clock_seq）：")
    print(f"     严格递增（逐个 > 前一个）= {all(b > a for a, b in zip(seq, seq[1:]))}")
    print(f"     去重后个数 = {len(set(seq))} / {N}")
    print(f"     首 = {seq[0]}  尾 = {seq[-1]}")

    print("\n== 2) 候选 id vs 产品主路径写出的 id（谁能在读侧胜出） ==")
    product_id = asyncio.run(product_latest_id())
    print(f"   产品 id = {product_id} (v{uuid.UUID(product_id).version})")
    for label, cand in (
        ("uuid4（revert.py 现写法）", str(uuid.uuid4())),
        ("uuid6（推荐修法）", str(uuid6())),
        ("uuid_utils.uuid7（直觉上的可排序 id）", str(uuid7())),
    ):
        print(f"   {label} = {cand}")
        print(f"     ⇒ 是否 > 产品 id = {cand > product_id}")

    print("\n== 3) InMemorySaver 的「最新」判定 ==")
    from langgraph.checkpoint.memory import InMemorySaver

    for line in inspect.getsource(InMemorySaver.get_tuple).splitlines():
        if "max(" in line:
            print("   [memory/__init__.py]", line.strip()[:150])

    print("\n== 4) AsyncPostgresSaver 的「最新」判定与列类型 ==")
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    pgsrc = inspect.getsource(inspect.getmodule(AsyncPostgresSaver))
    for line in pgsrc.splitlines():
        if "ORDER BY checkpoint_id" in line:
            print("   [aio.py]", line.strip()[:170])

    basesrc = inspect.getsource(
        __import__("langgraph.checkpoint.postgres.base", fromlist=["*"])
    )
    for m in re.finditer(r"checkpoint_id\s+\w+", basesrc):
        print("   [base.py 列定义]", " ".join(m.group(0).split()))
        break

    print("\n== 5) MongoCheckpointer（本仓自研）的排序 ==")
    mongo_src = inspect.getsource(
        __import__("agent_core.memory.mongo_checkpointer", fromlist=["MongoCheckpointer"])
    )
    for line in mongo_src.splitlines():
        if 'sort("checkpoint_id"' in line:
            print("   [mongo_checkpointer.py]", line.strip()[:150])

    print("\n== 6) 本仓清理器对同一假设的显式表述 ==")
    cleaner = open(
        "applications/agent_federation/agent/checkpoint_cleaner.py", encoding="utf-8"
    ).read()
    for line in cleaner.splitlines():
        if "字典序即写入序" in line or "ORDER BY checkpoint_id DESC" in line:
            print("   [checkpoint_cleaner.py]", line.strip()[:150])


if __name__ == "__main__":
    main()
