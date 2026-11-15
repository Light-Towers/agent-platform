"""roadmap #18 取证探针：只读控制台所消费的接口，逐帧记录真实读数。

本件**已随读数入库**（原写在 `.tmp-scratch/` 下，那边靠 `.gitignore` 的 `.*/` 不入库）。
⚠ “只读”指的是**被取证的那个控制台页面不得有写入口**（基线 6），不是本探针零副作用：
本探针会 `POST /query` ⇒ 真跑一次链路、消耗 token、向内存 checkpointer 写 checkpoint。
所以必须在**一次性本地实例**上跑（`DATABASE_URL=` 置空 ⇒ 内存态，命令见 readings.md §1 字段 ②），
不得拿它去跑现网。
"""
import asyncio

import httpx

BASE = "http://127.0.0.1:8123"


async def main() -> None:
    async with httpx.AsyncClient(timeout=90) as c:
        h = (await c.get(BASE + "/health")).json()
        print("== /health ==")
        for k in ("status", "version", "llm", "storage", "revert", "auth_enabled",
                  "identity_mode", "planner", "guard_enabled", "embedding_real",
                  "coordination", "admission"):
            print(f"  {k} = {h.get(k)}")

        print("\n== POST /query（SSE，逐帧原文） ==")
        async with c.stream(
            "POST", BASE + "/query",
            json={"query": "平台支持哪些能力？", "session_id": "console"},
        ) as r:
            print("  HTTP", r.status_code, "| content-type:", r.headers.get("content-type"))
            n = 0
            async for line in r.aiter_lines():
                s = line.strip()
                if not s:
                    continue
                n += 1
                print(f"  FRAME[{n}]: {s[:200]}")

        print("\n== GET /history ==")
        rr = await c.get(BASE + "/history", params={"session_id": "console", "limit": 5})
        print("  HTTP", rr.status_code, "|", rr.text[:220])

        print("\n== GET /console.html ==")
        rc = await c.get(BASE + "/console.html")
        print("  HTTP", rc.status_code, "| cache-control:", rc.headers.get("cache-control"),
              "| bytes:", len(rc.content))


asyncio.run(main())
