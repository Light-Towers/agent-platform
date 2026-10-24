"""身份门卫装配点（roadmap 阶段 2 #11）：把「启动守卫 + 中间件 + 档位留痕」收敛成一次调用。

为什么需要这个模块：三件事的正确组合是易错点，散在各 app 里迟早漏一件——
漏守卫 = 生产多租户裸奔无人知（``require_identity_startup_guard`` 正是封这个的），
漏中间件 = 服务端断言根本不产生，漏留痕 = 事后无法核对当时生效的是哪一档。
**三层里本模块只是「单一实现」**，覆盖度另由 ``scripts/lint_architecture.py`` 的 P13 门禁判定
（AGENTS.md「架构决策原则」：单一实现 + 全局装配 + 强制门禁，缺一层即退化为约定）。

为什么不放进 ``agent_core.guardrails.app_factory.build_api_app``：工厂在 agent-core，
``IdentityMiddleware`` 在 agent-runtime，而依赖方向必须是
application → agent-runtime → agent-core（红线 1），core 不得反向 import runtime
⇒ 只能「共享实现 + 各服务装配点 + 存在性门禁」。这是本项与 #12 观测装配的形状差异，不是偷懒。

档位（沿用 ``IdentityMiddleware`` 现状，本模块不新增开关名）：
- **observe（默认）**：有合法凭据 ⇒ 断言进上下文；无凭据 ⇒ 交下游既有逻辑（provided>default），
  响应与状态码逐字不变 ⇒ 这是「先只观察不拦截」的落点。
- **enforce**：``TENANT_JWT_ENFORCE=true`` 时缺凭据 401。翻档是**运维动作**（置 env），
  不需要改代码，回退 = 撤 env。
"""

from __future__ import annotations

from typing import Any

from agent_core.logging import get_logger

from agent_runtime.identity import (
    env_bool,
    load_hmac_key,
    require_identity_startup_guard,
    verify_internal_header,
)
from agent_runtime.identity_middleware import IdentityMiddleware

logger = get_logger(__name__)

__all__ = ["ENFORCE_ENV", "FAILFAST_ENV", "HMAC_KEY_ENV", "INTERNAL_HEADER", "mount_identity_gate"]

# 灰度开关与凭据面的 env 名在此显式命名：留痕、门禁、测试都引用它，避免各服务猜名字。
ENFORCE_ENV = "TENANT_JWT_ENFORCE"
FAILFAST_ENV = "DEPLOY_ENFORCE_IDENTITY"
HMAC_KEY_ENV = "INTERNAL_HMAC_KEY_FILE"
INTERNAL_HEADER = "X-Internal-Tenant"


def verify_internal_header_if_configured(value: str) -> tuple[str, str | None] | None:
    """按请求判定：配了密钥才采信 ``X-Internal-Tenant``，未配则**忽略**该头。

    为什么不在装配时一次性决定：装配时点读到的 env 会固化整个进程生命周期，
    那样「运维补挂密钥文件」需要重启才生效。而 ``IdentityMiddleware`` 只在请求**真的带该头**
    时才调本函数，所以未配密钥的常规流量不产生任何额外 I/O。

    为什么「忽略」而不是「拒绝」：``verify_internal_header`` 在收到内部头但没配密钥时抛
    ``IdentityError``，中间件据此回 401。若照那个语义装配，「网关开始签发内部头」与
    「子服务尚未挂密钥」两件事的任何时间差都会把子服务打成全量 401——
    这是拿配置的缺位冒充攻击，属于可用性缺陷。忽略＝与接入前逐字一致。
    """
    if not load_hmac_key():
        logger.warning(
            "[identity] 收到 %s 但未配置 %s ⇒ 忽略该头（不采信也不拒绝）",
            INTERNAL_HEADER,
            HMAC_KEY_ENV,
        )
        return None
    return verify_internal_header(value)


def mount_identity_gate(app: Any, service_name: str) -> dict[str, Any]:
    """给服务挂上服务端身份门卫，返回本次生效的档位快照（供调用方与测试断言）。

    Args:
        app: FastAPI/Starlette 应用实例（须尚未 startup）。
        service_name: 留痕用的服务名，同时传给启动守卫做 fail-fast 定位。

    Returns:
        ``{"tier": "observe"|"enforce", "startup_mode": "jwt"|"single"|"insecure",
        "hmac_key_present_at_assembly": bool}``。调用方不需要据此分支；
        ``hmac_key_present_at_assembly`` 只是留痕快照，**采信与否按请求判定**（见
        :func:`verify_internal_header_if_configured`）。
    """
    startup_mode = require_identity_startup_guard(service_name)
    enforce = env_bool(ENFORCE_ENV, False)
    app.add_middleware(
        IdentityMiddleware,
        verify_header=verify_internal_header_if_configured,
    )
    logger.info(
        "[identity] %s 门卫已装配: 档=%s 启动模式=%s 内部签名头=按请求判定（配了 %s 才采信）"
        "（env: 档位=%s fail-fast=%s；装配时密钥=%s）",
        service_name,
        "enforce" if enforce else "observe",
        startup_mode,
        HMAC_KEY_ENV,
        ENFORCE_ENV,
        FAILFAST_ENV,
        "在位" if load_hmac_key() else "未在位",
    )
    return {
        "tier": "enforce" if enforce else "observe",
        "startup_mode": startup_mode,
        "hmac_key_present_at_assembly": bool(load_hmac_key()),
    }
