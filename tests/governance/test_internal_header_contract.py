"""跨服务单一实现守卫（ADR-0007 决策 1=A3）：内部头签名原语只 agent-core 一份。

- 行为：agent_runtime.identity 的 sign/verify 与 agent-core 原语**互相可验**（薄封装，非重复实现）；
- 反漂移：`agent_runtime/identity.py` 不得再自行 `hmac.new(...sha256...)` 实现签名（应下沉 agent-core）。
  防"每处各自实现"导致签名格式漂移（横切关注点单一实现原则）。
"""

from __future__ import annotations

from pathlib import Path

from agent_core.internal_header import sign_internal_header as core_sign
from agent_core.internal_header import verify_internal_header as core_verify
from agent_runtime.identity import sign_internal_header as rt_sign
from agent_runtime.identity import verify_internal_header as rt_verify

REPO = Path(__file__).resolve().parents[2]
_KEY = b"shared-hmac-key"


def test_runtime_and_core_signatures_interchangeable():
    # runtime 签 → core 验
    assert core_verify(rt_sign("tenantA", "u1", key=_KEY), key=_KEY) == ("tenantA", "u1")
    # core 签 → runtime 验
    assert rt_verify(core_sign("tenantB", "u2", key=_KEY), key=_KEY) == ("tenantB", "u2")


def test_identity_does_not_reimplement_hmac_primitive():
    """签名原语唯一在 agent-core；identity 只委托，不再自带 hmac.new/sha256 实现。"""
    src = (REPO / "packages/agent-runtime/agent_runtime/identity.py").read_text(encoding="utf-8")
    assert "hmac.new" not in src, "内部头签名应复用 agent_core.internal_header，勿在 runtime 重复实现"
    assert "from agent_core.internal_header import" in src, "identity 必须委托 agent-core 原语"
