# -*- coding: utf-8 -*-
"""
app/lm/_logging.py —— app.lm 内共享日志对象（M8）。

优先使用项目标准 loguru（app.core.logger）；当 loguru 未安装（裸 venv / 最小化部署，
例如仅跑 api 模式单测）时回退到标准库 logging，保证 api 模式路径可导入、可运行。
仅在真实环境缺失 loguru 时启用回退，真实环境行为与项目标准完全一致。
"""

try:
    from app.core.logger import logger
except ImportError:  # pragma: no cover - 仅裸 venv（无 loguru）场景触发
    import logging

    class _LoguruCompatLogger:
        """loguru 缺失时的兼容壳：success 映射到 info，其余透传标准库日志。"""

        def __init__(self, name):
            self._logger = logging.getLogger(name)

        def debug(self, message, *args, **kwargs):
            self._logger.debug(message, *args)

        def info(self, message, *args, **kwargs):
            self._logger.info(message, *args)

        def success(self, message, *args, **kwargs):
            self._logger.info(message, *args)

        def warning(self, message, *args, **kwargs):
            self._logger.warning(message, *args)

        def error(self, message, *args, **kwargs):
            self._logger.error(message, *args)

        def exception(self, message, *args, **kwargs):
            self._logger.exception(message, *args)

    logger = _LoguruCompatLogger(__name__)
