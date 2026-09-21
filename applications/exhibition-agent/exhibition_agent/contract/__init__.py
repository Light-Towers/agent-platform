"""contract/：跨项目接口契约 v1.2 的唯一定义处。

C1 ExecutionContext（platform → warehouse，保留）+ C2' 直接 REST（修订自 v1.1 统一信封）+ 错误码表。
本包是 exhibition-agent 对契约的唯一实现源，不依赖 shared-schemas（联邦契约是另一套口径）。

v1.2 变更：C2 从「统一信封 + skill invoke」改成「直接 REST」。
- envelope.py 移除 SkillRequest / SkillSuccessEnvelope / SkillErrorEnvelope（不再走信封）；
  保留 Readiness / DataClassification / EgressDecision / Source / Citation（平台侧自组装 SkillResult 用）。
- error_codes.py 保留 ErrorCode 枚举（trace.error_code / SkillResult.error_code / HTTP 映射用）。
- execution_context.py 不动（C1 保留）。

命名消歧：本包的 ``ExecutionContext`` 是 C1 跨项目契约上下文（user_id / tenant_id /
scopes / auth_source / request_id），与 ``agent_runtime.planner.protocol.ExecutionContext``
（运行时执行边界，含 metadata / record_usage / ContextVar 绑定）**语义不同**，
二者共存于 monorepo，import 时需按完整路径区分。
"""

from exhibition_agent.contract.envelope import (
    Citation,
    DataClassification,
    EgressDecision,
    Readiness,
    Source,
)
from exhibition_agent.contract.error_codes import (
    ERROR_CODE_HTTP_MAP,
    METRIC_PENDING_CODES,
    PENDING_ANSWER,
    PENDING_ANSWER_CODES,
    ErrorCode,
)
from exhibition_agent.contract.execution_context import (
    AuthSource,
    ExecutionContext,
    TenantType,
)

__all__ = [
    "ExecutionContext",
    "TenantType",
    "AuthSource",
    "Readiness",
    "DataClassification",
    "EgressDecision",
    "Source",
    "Citation",
    "ErrorCode",
    "ERROR_CODE_HTTP_MAP",
    "METRIC_PENDING_CODES",
    "PENDING_ANSWER_CODES",
    "PENDING_ANSWER",
]
