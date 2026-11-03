"""取证探针 B：错误通道 + revert 真实分支读数（给 web/ PR-3 定夺用）。

本件**已随读数入库**（原写在 `.tmp-scratch/` 下，那边靠 `.gitignore` 的 `.*/` 不入库）。
副作用与探针 A 同源且必须同环境跑（一次性本地实例，`DATABASE_URL=` 置空）：
- 第 1 项 `POST /query` ⇒ **真跑一次链路**（消耗 token、写内存 checkpoint）；
- 第 2 项 `POST /session/revert` 喂**不存在的** uuid ⇒ 取的是失败分支读数（实测
  `404 CHECKPOINT_NOT_FOUND`，故不改状态），但它仍是**写形接口**，不得拿真实 id 去现网跑；
- 第 3/4 项是 422 形状读数（参数不合法，请求未进入业务层）。
"""
import asyncio

import httpx

BASE = "http://127.0.0.1:8123"


async def main() -> None:
    async with httpx.AsyncClient(timeout=90) as c:
        print("== 1) 走 rag 特征的问题：看是否出流内 error 帧 ==")
        async with c.stream(
            "POST", BASE + "/query",
            json={"query": "检索知识库里关于故障转移的文档并给出依据", "session_id": "console"},
        ) as r:
            print("  HTTP", r.status_code)
            async for line in r.aiter_lines():
                s = line.strip()
                if s:
                    print(f"  FRAME: {s[:210]}")

        print("\n== 2) /session/revert 带不存在的 checkpoint_id（只读取证不做交互，纯拿分支读数） ==")
        rr = await c.post(
            BASE + "/session/revert",
            json={"session_id": "console", "checkpoint_id": "00000000-0000-0000-0000-000000000000"},
        )
        print("  HTTP", rr.status_code, "|", rr.text[:240])

        print("\n== 3) /history 空 session_id（422 形状） ==")
        r3 = await c.get(BASE + "/history", params={"session_id": ""})
        print("  HTTP", r3.status_code, "|", r3.text[:180])

        print("\n== 4) 不存在的检查点之外：/session/revert 缺字段（422 形状） ==")
        r4 = await c.post(BASE + "/session/revert", json={"session_id": "console"})
        print("  HTTP", r4.status_code, "|", r4.text[:180])


asyncio.run(main())
