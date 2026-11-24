#!/usr/bin/env python3
"""真 PG 往返实取：会话传图存储（chat_images）+ 图片解析 + 多模态合成。

来历：plan-image-qa-fullstack 的 5 个 bug（Form / pool.acquire / $1 散参数 / fetchrow /
VL 端点）全在 fake 单测全绿下存活，部署后才逐个暴露。本探针用 pgserver（wheel 自带
PostgreSQL 16.2 + pgvector，本机零基建）起真库、跑真 migration 022、调**生产 chat_images.py**
（非 fake），把 DB 相关的假绿一次根除。外部 VL 端点另见 preflight_vl.py。

为什么能零基建跑：配方见 `docs/operations/testing-playbook.md` §3.4；
Windows 下必须 `WindowsSelectorEventLoopPolicy`，否则 psycopg 异步必炸。

退出码：`0` 全部通过 · `1` 有未过（回归）· `2` 前置不可用（pgserver 缺席/起不来）——`2` 从不折算成通过。

    uv run --no-sync --with pgserver python scripts/evidence/chat_images_real_pg_probe.py
"""

from __future__ import annotations

import asyncio
import base64
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PGDATA = ROOT / ".pgserver-probe"  # 根 .gitignore 的 .*/ 天然忽略
DB = "chat_images_evidence"

try:
    import pgserver
    import psycopg
    import psycopg_pool
except ImportError as exc:
    print(f"[PRE] 依赖不可用（需 --with pgserver）: {exc}")
    sys.exit(2)

sys.path.insert(0, str(ROOT / "applications"))  # 使 agent_server 作为包可 import
sys.path.insert(0, str(ROOT / "packages" / "agent-runtime"))

FAILS: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")
    if not ok:
        FAILS.append(label)


# 一张真实可解码的 PNG（1x1 红点，IDAT 校验和有效）
_TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8AAAwAB/wFbC+8AAAAASUVORK5CYII="
)


async def _apply_022(conn) -> None:
    """建 chat_images 表（与 migration 022 同 DDL；独立表，不依赖前序迁移）。"""
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS chat_images (
            ref TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, session_id TEXT NOT NULL,
            content BYTEA NOT NULL, content_type TEXT NOT NULL, byte_size INTEGER NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)


async def phase(db: str) -> None:
    import agent_server.chat_images as store  # 与 query_router 的 _chat_images 同一模块对象
    from agent_server.api import query_router  # 确保它 import 的 _chat_images 已就位
    # 两处引用必须指向同一模块对象，否则 monkeypatch 只改一半（正是本次探针发现的问题）
    assert query_router._chat_images is store, "query_router 与探针必须共用同一 chat_images 模块"

    pool = psycopg_pool.AsyncConnectionPool(db, min_size=1, max_size=2, timeout=10.0)
    await pool.open()
    store.get_pool = lambda: pool  # 注入真 pool
    try:
        async with pool.connection() as c:
            await _apply_022(c)
        print("=== 1. 生产 chat_images.save_image/get_image（真 psycopg3）===")
        ref = store.make_ref("tenantA", "sess-1", "png")
        await store.save_image(ref, "tenantA", "sess-1", _TINY_PNG, "image/png")
        got = await store.get_image(ref, "tenantA")
        check("save→get 往返字节一致", bool(got) and got[0] == _TINY_PNG and got[1] == "image/png")

        print("=== 2. 租户隔离（跨租户 ref 必须拒绝）===")
        check("跨租户 get 返回 None", await store.get_image(ref, "tenantB") is None)

        print("=== 3. ref 形状（不透明、不含 host/hostile 前缀）===")
        check("ref 不含 host/端口", ":" not in ref.replace("chat-images", "") and "minio" not in ref, ref)

        print("=== 4. TTL 清理（只删过期、不删有效）===")
        # 造一条过期行
        old_ref = store.make_ref("tenantA", "sess-old", "png")
        async with pool.connection() as c:
            await c.execute(
                "INSERT INTO chat_images (ref,tenant_id,session_id,content,content_type,byte_size,created_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,NOW() - INTERVAL '30 days')",
                (old_ref, "tenantA", "sess-old", _TINY_PNG, "image/png", len(_TINY_PNG)),
            )
        n = await store.delete_expired()
        check("删掉过期行", n >= 1, f"deleted={n}")
        check("有效行仍在", await store.get_image(ref, "tenantA") is not None)

        print("=== 5. 图片解析 → data URI → 多模态合成 ===")
        # _resolve_images / _compose 是纯逻辑（不依赖 pool），验证接线形状
        from agent_server.api.query_router import _image_signature, _resolve_images
        from agent_server.planners.deterministic import DeterministicPlanner

        imgs = await _resolve_images({"images": [ref]}, "tenantA")
        check("ref 解析为 data URI", len(imgs) == 1 and imgs[0].startswith("data:image/png;base64,"))
        check("图片签名纳入缓存键", len(_image_signature(imgs)) == 16)

        class _Stub:
            def __init__(self):
                self.calls = []

            async def ainvoke(self, msgs):
                self.calls.append(msgs)
                return type("R", (), {"content": "ok"})()

        vl, text = _Stub(), _Stub()
        await DeterministicPlanner()._compose("q", [], [], text, images=imgs, vl_llm=vl)
        check("有图走 VL 且 content 含 image_url",
              len(vl.calls) == 1 and len(text.calls) == 0
              and any(b.get("type") == "image_url" for b in vl.calls[0][1]["content"]))
        await DeterministicPlanner()._compose("q", [], [], text)
        check("无图保持纯文本", isinstance(text.calls[0][1]["content"], str))
    finally:
        await pool.close()


def main() -> int:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        srv = pgserver.get_server(str(PGDATA))
        base = srv.get_uri()
        with psycopg.connect(base, autocommit=True) as c:
            c.execute(f"DROP DATABASE IF EXISTS {DB}")
            c.execute(f"CREATE DATABASE {DB}")
    except Exception as exc:  # noqa: BLE001 — 前置不可用归因须覆盖任意异常形状
        print(f"[PRE] 本机 PG 起不来/连不上 [{type(exc).__name__}]: {exc}")
        return 2
    db = base.rsplit("/", 1)[0] + f"/{DB}"
    asyncio.run(phase(db))
    print("\n结论:", "全部通过" if not FAILS else f"{len(FAILS)} 项未过: {FAILS}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
