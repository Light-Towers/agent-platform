import asyncio
import datetime
from collections.abc import Callable
from typing import Any

from fastapi import WebSocket

import utils._path_setup  # noqa: F401 — agent-core sys.path
from api.context import get_thread_context

try:
    from agent_core.logging import get_logger
    logger = get_logger(__name__)
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

try:
    import builtins
except ImportError:
    builtins = None


class ToolMonitor:
    """
    工具监控类，用于在工具执行过程中上报进度和状态。
    设计为单例模式，可在任何工具中直接导入使用。
    兼容 FastAPI WebSocket 和 脚本运行时的 stream_writer。
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.websocket_manager = None
            cls._instance._callbacks = {}
        return cls._instance

    def set_websocket_manager(self, manager):
        self.websocket_manager = manager

    def _emit(self, event_type: str, message: str, data: dict[str, Any] | None = None):
        payload = {
            "type": "monitor_event",
            "event": event_type,
            "message": message,
            "data": data or {},
            "timestamp": datetime.datetime.now().isoformat()
        }

        if self.websocket_manager:
            try:
                thread_id = get_thread_context()
                manager_loop = self.websocket_manager.loop

                if manager_loop:
                    if thread_id:
                        try:
                            current_loop = asyncio.get_running_loop()
                        except RuntimeError:
                            current_loop = None

                        if current_loop and current_loop == manager_loop:
                            current_loop.create_task(
                                self.websocket_manager.send_to_thread(payload, thread_id)
                            )
                        else:
                            asyncio.run_coroutine_threadsafe(
                                self.websocket_manager.send_to_thread(payload, thread_id),
                                manager_loop
                            )
            except Exception as e:
                logger.warning("WebSocket send failed: %s", e)

        if builtins and hasattr(builtins, 'runtime') and hasattr(builtins.runtime, 'stream_writer'):
            try:
                builtins.runtime.stream_writer(payload)
            except Exception:
                pass

        logger.debug("[Monitor:%s] %s", event_type, message)

        for cb in self._callbacks.get(event_type, []):
            try:
                cb(payload)
            except Exception:
                pass

    def report_tool(self, tool_name: str, args: dict[str, Any] = None):
        self._emit("tool_start", f"开始执行工具: {tool_name}", {"tool_name": tool_name, "args": args})

    def report_assistant(self, assistant_name: str, args: dict[str, Any] = None):
        self._emit("assistant_call", f"正在调用助手: {assistant_name}",
                   {"assistant_name": assistant_name, "args": args})

    def report_task_result(self, result: str):
        self._emit("task_result", "任务执行完成", {"result": result})

    def report_session_dir(self, path: str):
        self._emit("session_created", f"工作目录已创建: {path}", {"path": path})

    def report_error(self, message: str):
        logger.error("[Monitor:error] %s", message)
        self._emit("error", message)

    def on(self, event_type: str, callback: Callable):
        self._callbacks.setdefault(event_type, []).append(callback)

    def off(self, event_type: str, callback: Callable):
        if event_type in self._callbacks:
            try:
                self._callbacks[event_type].remove(callback)
            except ValueError:
                pass

    def report_tool_outcome(self, tool_name: str, outcome: str,
                            error_class: str = None, detail: str = ""):
        self._emit("tool_outcome", f"工具 {tool_name} 结果: {outcome}",
                   {"tool_name": tool_name, "outcome": outcome,
                    "error_class": error_class, "detail": detail})


monitor = ToolMonitor()


class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}
        self.loop = None

    def set_loop(self, loop):
        self.loop = loop
        monitor.set_websocket_manager(self)
        logger.info("ConnectionManager bound to loop: %s", id(self.loop))

    async def connect(self, websocket: WebSocket, thread_id: str):
        await websocket.accept()
        self.active_connections[thread_id] = websocket
        logger.info("Client connected: %s", thread_id)

    def disconnect(self, websocket: WebSocket, thread_id: str):
        if thread_id in self.active_connections:
            del self.active_connections[thread_id]
        logger.info("Client disconnected: %s", thread_id)

    async def send_personal_message(self, message: str, websocket: WebSocket):
        await websocket.send_text(message)

    async def send_to_thread(self, message: dict, thread_id: str):
        if thread_id in self.active_connections:
            websocket = self.active_connections[thread_id]
            await websocket.send_json(message)


manager = ConnectionManager()
