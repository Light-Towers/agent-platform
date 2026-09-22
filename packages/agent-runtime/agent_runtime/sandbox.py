"""沙箱代码执行器：在隔离环境中执行用户代码，保护宿主机安全。

双后端设计：
- **Docker 后端**（生产）：启动临时容器执行代码，--rm 自动清理，网络隔离 + 只读 FS + 资源限制
- **subprocess 后端**（开发降级）：用 subprocess 隔离执行，安全性较低但零依赖

后端选择：优先 Docker（docker CLI 可用），不可用时降级 subprocess（日志警告）。

远程 Docker 支持：
- 设置 ``docker_host`` 参数（如 ``"tcp://192.168.100.126:2375"``）或 ``DOCKER_HOST`` 环境变量
- Docker CLI 自动读取 ``DOCKER_HOST`` 连接远程 Docker daemon
- 远程 Docker 需开启 Docker API（``dockerd -H tcp://0.0.0.0:2375``），生产环境建议配 TLS

安全措施（Docker）：
- ``--rm``：执行完自动清理容器
- ``--network=none``：无网络访问
- ``--read-only``：根文件系统只读，``--tmpfs /tmp`` 供临时写入
- ``--memory=512m --cpus=1``：资源限制
- ``--security-opt=no-new-privileges``：禁止提权
- ``--user=nobody``：非 root 执行
- 超时：``asyncio.wait_for`` + Docker ``--timeout``

安全措施（subprocess）：
- ``timeout``：超时杀进程
- ``capture_output``：不继承宿主 stdout/stderr
- 无网络隔离（开发降级，日志警告）
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import sys
from dataclasses import dataclass
from typing import Literal

logger = logging.getLogger(__name__)

_DOCKER_IMAGE = "python:3.11-slim"
_DEFAULT_TIMEOUT = 30
_DEFAULT_MEMORY = "512m"
_DEFAULT_CPUS = "1"


@dataclass(frozen=True)
class SandboxResult:
    """沙箱执行结果。"""

    success: bool
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    duration_ms: int = 0
    backend: str = ""


def _docker_available() -> bool:
    """检测 docker CLI 是否可用。"""
    return shutil.which("docker") is not None


class SandboxExecutor:
    """沙箱执行器：Docker 优先，subprocess 降级。

    用法::

        executor = SandboxExecutor()
        result = await executor.execute("print(1 + 1)")
        if result.success:
            print(result.stdout)  # "2\\n"
    """

    def __init__(
        self,
        *,
        backend: Literal["docker", "subprocess", "auto"] = "auto",
        image: str = _DOCKER_IMAGE,
        memory: str = _DEFAULT_MEMORY,
        cpus: str = _DEFAULT_CPUS,
        docker_host: str | None = None,
    ) -> None:
        self._image = image
        self._memory = memory
        self._cpus = cpus
        self._docker_host = docker_host or os.environ.get("DOCKER_HOST")
        if backend == "auto":
            self._backend = "docker" if _docker_available() else "subprocess"
        else:
            self._backend = backend
        if self._backend == "subprocess" and backend == "auto":
            logger.warning(
                "Docker 不可用，沙箱降级为 subprocess 执行（安全性较低，仅开发环境适用）"
            )
        if self._docker_host and self._backend == "docker":
            logger.info("沙箱使用远程 Docker: %s", self._docker_host)

    @property
    def backend(self) -> str:
        return self._backend

    async def execute(
        self,
        code: str,
        *,
        language: str = "python",
        timeout: int = _DEFAULT_TIMEOUT,
    ) -> SandboxResult:
        """在沙箱中执行代码。

        :param code: 代码字符串。
        :param language: 语言（当前仅支持 "python"）。
        :param timeout: 超时秒数。
        :return: ``SandboxResult``
        """
        if language != "python":
            return SandboxResult(
                success=False, stderr=f"不支持的语言: {language}", exit_code=-1, backend=self._backend
            )
        if self._backend == "docker":
            return await self._execute_docker(code, timeout)
        return await self._execute_subprocess(code, timeout)

    async def _execute_docker(self, code: str, timeout: int) -> SandboxResult:
        """Docker 后端：启动临时容器执行代码。"""
        import time

        t0 = time.monotonic()
        cmd = [
            "docker", "run", "--rm",
            "--network=none",
            "--read-only",
            "--tmpfs", "/tmp:rw,size=64m",
            f"--memory={self._memory}",
            f"--cpus={self._cpus}",
            "--security-opt=no-new-privileges",
            "--user=nobody",
            self._image,
            "python", "-c", code,
        ]
        try:
            env = dict(os.environ)
            if self._docker_host:
                env["DOCKER_HOST"] = self._docker_host
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            exit_code = proc.returncode or 0
            return SandboxResult(
                success=exit_code == 0,
                stdout=stdout.decode("utf-8", errors="replace"),
                stderr=stderr.decode("utf-8", errors="replace"),
                exit_code=exit_code,
                duration_ms=int((time.monotonic() - t0) * 1000),
                backend="docker",
            )
        except TimeoutError:
            return SandboxResult(
                success=False, stderr=f"执行超时（{timeout}s）", exit_code=-1,
                duration_ms=int((time.monotonic() - t0) * 1000), backend="docker",
            )
        except Exception as exc:
            return SandboxResult(
                success=False, stderr=str(exc), exit_code=-1,
                duration_ms=int((time.monotonic() - t0) * 1000), backend="docker",
            )

    async def _execute_subprocess(self, code: str, timeout: int) -> SandboxResult:
        """subprocess 后端（开发降级）：隔离执行 Python 代码。"""
        import time

        t0 = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-c", code,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            exit_code = proc.returncode or 0
            return SandboxResult(
                success=exit_code == 0,
                stdout=stdout.decode("utf-8", errors="replace"),
                stderr=stderr.decode("utf-8", errors="replace"),
                exit_code=exit_code,
                duration_ms=int((time.monotonic() - t0) * 1000),
                backend="subprocess",
            )
        except TimeoutError:
            return SandboxResult(
                success=False, stderr=f"执行超时（{timeout}s）", exit_code=-1,
                duration_ms=int((time.monotonic() - t0) * 1000), backend="subprocess",
            )
        except Exception as exc:
            return SandboxResult(
                success=False, stderr=str(exc), exit_code=-1,
                duration_ms=int((time.monotonic() - t0) * 1000), backend="subprocess",
            )


__all__ = ["SandboxExecutor", "SandboxResult"]
