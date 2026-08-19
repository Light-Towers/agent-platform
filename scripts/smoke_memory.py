"""TB-7 等价冒烟：在无 Docker 环境下验证 app 内存模式 lifespan 预热 + 图构建。

等价于 `make compose-smoke` 中 agent-platform 服务启动并完成 lifespan 的关键路径，
但不需要 pgvector / Docker。仅验证「app 自身能完成导入 + 图构建 + 健康检查」，
不覆盖 pg 连接（那部分由 compose 真端到端覆盖）。

用法：
    uv run python scripts/smoke_memory.py

注意：内存模式要求 DATABASE_URL 完全未设置（非空字符串会被当作启用 pg）。
本脚本会在启动前主动清除该环境变量以强制内存模式。
"""
import asyncio
import os
import traceback

# 彻底清除 DATABASE_URL，确保进入内存模式（db_enabled=False）
for k in list(os.environ):
    if k.upper() == "DATABASE_URL":
        os.environ.pop(k, None)

import agent_server.main as m


async def main() -> int:
    settings = m.get_settings()
    if settings.db_enabled:
        print("SKIP: DATABASE_URL 已设置，请改用 `make compose-smoke` 做 pg 端到端冒烟")
        return 2
    try:
        async with m.app.router.lifespan_context(m.app):
            graph = getattr(m.app.state, "graph", None)
            checkpointer = getattr(m.app.state, "checkpointer", None)
            print("LIFESPAN_OK")
            print("db_enabled=", settings.db_enabled)
            print("graph built=", graph is not None)
            print("checkpoint type=", type(checkpointer).__name__)
            return 0 if (graph is not None and checkpointer is not None) else 1
    except Exception:  # noqa: BLE001
        print("LIFESPAN_FAILED")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
