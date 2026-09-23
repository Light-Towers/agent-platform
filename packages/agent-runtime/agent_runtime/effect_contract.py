"""Effect Contract（V3-2）：副作用的**语义契约**——平台据此知道 effect 应如何 delivery/retry/recover。

与 SideEffectStore 的区别（v3-roadmap-breakdown.md §5）：
- ``SideEffectStore`` 记录「这个 effect 已执行」（事实/证据）；
- ``EffectContract`` 声明「这个 effect 应该如何交付、能否安全重试、如何恢复」（语义/契约）。

平台**不承诺** effectively-once：``IdempotencyStore`` 只能证明「平台知道某 effect_key 已确认」，
**不能凭空知道第三方到底有没有成功执行**。``EffectivelyOnce`` 是「在特定 idempotency / receipt
条件下实现的业务语义」，不是 Runtime 的绝对保证。

失败决策（``decide_failure_action``）把「异常分类」与「副作用语义」两个信号合并：
```
Tool failed
   │
   ▼
Failure Classification (agent_core.resilience.classify_exception)
   │
   ▼
Effect Contract（本模块）
   │
   ├── RETRY_SAFE          safe retry
   ├── QUERY_BEFORE_RETRY  query status first
   ├── NO_RETRY            don't retry
   └── ABORT               fatal，终止执行
```
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from agent_core.resilience import ErrorClass


class DeliverySemantics(str, Enum):
    """交付语义（严谨三分）。"""

    AT_MOST_ONCE = "at-most-once"
    AT_LEAST_ONCE = "at-least-once"
    EFFECTIVELY_ONCE = "effectively-once"


class IdempotencyStrategy(str, Enum):
    """幂等策略：如何让重复调用收敛到一次业务效果。"""

    NONE = "none"  # 无幂等保证——重复调用会产生重复副作用
    BUSINESS_KEY = "business-key"  # 业务键幂等（如 order_id，由外部系统识别）
    PLATFORM_KEY = "platform-key"  # 平台幂等键（execution_id:step_id:effect_type）


class ReceiptStrategy(str, Enum):
    """回执策略：如何证明 effect 已在外部系统落地。"""

    NONE = "none"  # 无回执——恢复时无法判定外部状态
    EXTERNAL_ID = "external-id"  # 外部系统返回 id（如 job_id / order_id），可据此 query
    PLATFORM_MARKER = "platform-marker"  # 仅平台侧 marker（SideEffectStore 记录）


class RetryPolicy(str, Enum):
    """重试策略：失败后能否直接重试。"""

    SAFE = "safe"  # 直接重试安全（幂等 / 只读）
    UNSAFE = "unsafe"  # 直接重试不安全（非幂等写），不应重试
    QUERY_FIRST = "query-first"  # 先查询外部状态确认，再决定是否重试


class FailureRecovery(str, Enum):
    """失败恢复策略：重试耗尽 / 不可重试时的兜底动作。"""

    RETRY_SAFE = "retry-safe"  # 安全重试（配合 RetryPolicy.SAFE）
    QUERY_BEFORE_RETRY = "query-before-retry"  # 先 query 外部状态
    NO_RETRY = "no-retry"  # 不重试，直接降级/失败
    MANUAL = "manual"  # 需人工介入（如非幂等写且无回执）


class FailureAction(str, Enum):
    """失败后动作（决策输出）：供 Scheduler / 执行图消费。"""

    RETRY_SAFE = "retry-safe"  # 直接重试
    QUERY_BEFORE_RETRY = "query-before-retry"  # 先查询外部状态再重试
    NO_RETRY = "no-retry"  # 不重试，按可恢复降级继续
    ABORT = "abort"  # 终止整次执行（FATAL）


@dataclass(frozen=True)
class EffectContract:
    """副作用的语义契约（6 字段）。

    示例（``create_order``）：
    ```
    EffectContract(
        effect_key="order_id",
        delivery_semantics=DeliverySemantics.EFFECTIVELY_ONCE,
        idempotency_strategy=IdempotencyStrategy.BUSINESS_KEY,
        receipt_strategy=ReceiptStrategy.EXTERNAL_ID,
        retry_policy=RetryPolicy.SAFE,
        failure_recovery=FailureRecovery.RETRY_SAFE,
    )
    ```
    """

    effect_key: str
    delivery_semantics: DeliverySemantics = DeliverySemantics.AT_MOST_ONCE
    idempotency_strategy: IdempotencyStrategy = IdempotencyStrategy.NONE
    receipt_strategy: ReceiptStrategy = ReceiptStrategy.NONE
    retry_policy: RetryPolicy = RetryPolicy.UNSAFE
    failure_recovery: FailureRecovery = FailureRecovery.NO_RETRY

    def to_dict(self) -> dict[str, str]:
        """序列化（供持久化 / 审计）。"""
        return {
            "effect_key": self.effect_key,
            "delivery_semantics": self.delivery_semantics.value,
            "idempotency_strategy": self.idempotency_strategy.value,
            "receipt_strategy": self.receipt_strategy.value,
            "retry_policy": self.retry_policy.value,
            "failure_recovery": self.failure_recovery.value,
        }

    @classmethod
    def read_only(cls, effect_key: str = "read") -> "EffectContract":
        """只读能力预设：无副作用，重试安全。"""
        return cls(
            effect_key=effect_key,
            delivery_semantics=DeliverySemantics.AT_MOST_ONCE,
            idempotency_strategy=IdempotencyStrategy.NONE,
            receipt_strategy=ReceiptStrategy.NONE,
            retry_policy=RetryPolicy.SAFE,
            failure_recovery=FailureRecovery.RETRY_SAFE,
        )

    @classmethod
    def idempotent_write(cls, effect_key: str) -> "EffectContract":
        """幂等写预设：业务键幂等，重试安全（at-least-once + business-key）。"""
        return cls(
            effect_key=effect_key,
            delivery_semantics=DeliverySemantics.AT_LEAST_ONCE,
            idempotency_strategy=IdempotencyStrategy.BUSINESS_KEY,
            receipt_strategy=ReceiptStrategy.NONE,
            retry_policy=RetryPolicy.SAFE,
            failure_recovery=FailureRecovery.RETRY_SAFE,
        )

    @classmethod
    def non_idempotent_write(cls, effect_key: str) -> "EffectContract":
        """非幂等写预设：重复调用会产生重复副作用，不应重试，需人工介入。"""
        return cls(
            effect_key=effect_key,
            delivery_semantics=DeliverySemantics.AT_MOST_ONCE,
            idempotency_strategy=IdempotencyStrategy.NONE,
            receipt_strategy=ReceiptStrategy.NONE,
            retry_policy=RetryPolicy.UNSAFE,
            failure_recovery=FailureRecovery.MANUAL,
        )

    @classmethod
    def async_task(cls, effect_key: str) -> "EffectContract":
        """异步任务预设：外部返回 id，失败时先 query 状态再决定（effectively-once 语义）。"""
        return cls(
            effect_key=effect_key,
            delivery_semantics=DeliverySemantics.EFFECTIVELY_ONCE,
            idempotency_strategy=IdempotencyStrategy.BUSINESS_KEY,
            receipt_strategy=ReceiptStrategy.EXTERNAL_ID,
            retry_policy=RetryPolicy.QUERY_FIRST,
            failure_recovery=FailureRecovery.QUERY_BEFORE_RETRY,
        )


def decide_failure_action(
    contract: "EffectContract | None",
    error_class: ErrorClass,
) -> FailureAction:
    """据 EffectContract + 异常分类决定失败后动作。

    - FATAL 异常 → ``ABORT``（无论 contract 如何，致命错误终止执行）；
    - RECOVERABLE 异常 → ``NO_RETRY``（降级继续，不重试）；
    - RETRYABLE 异常：按 contract.retry_policy 决策；
      ``contract`` 为 None（Skill 未声明）时保持 v2 语义（按异常分类可重试 → ``RETRY_SAFE``）。
    """
    if error_class is ErrorClass.FATAL:
        return FailureAction.ABORT
    if error_class is ErrorClass.RECOVERABLE:
        return FailureAction.NO_RETRY
    # ErrorClass.RETRYABLE
    if contract is None:
        return FailureAction.RETRY_SAFE
    if contract.retry_policy is RetryPolicy.UNSAFE:
        return FailureAction.NO_RETRY
    if contract.retry_policy is RetryPolicy.QUERY_FIRST:
        return FailureAction.QUERY_BEFORE_RETRY
    return FailureAction.RETRY_SAFE


__all__ = [
    "DeliverySemantics",
    "IdempotencyStrategy",
    "ReceiptStrategy",
    "RetryPolicy",
    "FailureRecovery",
    "FailureAction",
    "EffectContract",
    "decide_failure_action",
]