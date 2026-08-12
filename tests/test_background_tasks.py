"""验证后台任务持引用防 GC：派发后计入 pending，完成后自动移除。"""

import asyncio

from app.infra.cache import pending_background_tasks, spawn_background


async def test_spawned_task_is_tracked_until_done():
    started = pending_background_tasks()

    async def work():
        await asyncio.sleep(0.01)
        return 42

    task = spawn_background(work())
    assert pending_background_tasks() == started + 1

    result = await task
    await asyncio.sleep(0)  # 让 done 回调执行
    assert result == 42
    assert pending_background_tasks() == started
