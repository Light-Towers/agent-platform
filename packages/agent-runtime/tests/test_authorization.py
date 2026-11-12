"""authorization 判据测试（1a；方案 plan-roles-kb-datasource-console §4/§6 + ADR-0015 §2.6）。

无网络/无 DB。五格各钉一条会被"顺手改回去"的取舍：

1. §4 矩阵**逐格**：9 个 feature × 3 角色的允许集与方案表一致（改表先改这里）；
2. 集合关系 admin ⊃ editor ⊃ viewer（增量表是它成立的实现面，反向漂移即红）；
3. 未知角色 / None → **空集 False**（fail-closed 不抛错；把未知码当 admin 即红）；
4. D9 兜底**可聚合计数**：unknown/None 每次自增，WARNING 按 (tenant,user) 首次去重
   （只评 WARNING 条数会让 R-1 触发条件永不可评——per-process 去重使条数封顶 1）；
5. ``resolve_features`` 单一入口（H6）：claims=None（P8 静态 API_KEY）与带 role 的
   claims 两条路径都从这一个函数出，兜底口径不第二份。
"""

from __future__ import annotations

import logging

import pytest

from agent_runtime import authorization as az
from agent_runtime.authorization import (
    FEATURES,
    ROLE_ADMIN,
    ROLE_EDITOR,
    ROLE_FEATURES,
    ROLE_VIEWER,
    ROLES,
    effective_role,
    features_for_role,
    has_feature,
    resolve_features,
    role_fallback_count,
)

# ---------------------------------------------------------------------------
# 格 1：§4 矩阵逐格（方案表是唯一事实源，本件是它的可执行形状）
# ---------------------------------------------------------------------------

_MATRIX = {
    # feature: (admin, editor, viewer) —— 与 §4 表逐行一致
    "chat.run": (True, True, True),
    "session.history": (True, True, True),
    "data.unmasked": (True, False, False),
    "sql.train": (True, False, False),
    "kb.upload": (True, True, False),
    "kb.publish": (True, False, False),
    "datasource.manage": (True, False, False),
    "execution.control": (True, False, False),
    "human_task.decide": (True, False, False),
}


@pytest.mark.parametrize("code,expected", sorted(_MATRIX.items()))
def test_matrix_matches_plan_table(code, expected):
    admin_ok = has_feature(ROLE_ADMIN, code)
    editor_ok = has_feature(ROLE_EDITOR, code)
    viewer_ok = has_feature(ROLE_VIEWER, code)
    assert (admin_ok, editor_ok, viewer_ok) == expected, (
        f"{code} 的矩阵格漂移：实际 (admin={admin_ok}, editor={editor_ok}, viewer={viewer_ok})，"
        f"方案 §4 要求 {expected}"
    )


def test_features_enum_is_exactly_nine():
    """10→9（kb.config 随模板砍除移出）：多一个无消费点的 feature 或少一个都算漂移。"""
    assert FEATURES == frozenset(_MATRIX), FEATURES ^ frozenset(_MATRIX)


def test_role_set_inclusion_admin_superset_editor_superset_viewer():
    """admin ⊃ editor ⊃ viewer：增量表结构漂移（如 viewer 拿到写面）即红。"""
    a, e, v = ROLE_FEATURES[ROLE_ADMIN], ROLE_FEATURES[ROLE_EDITOR], ROLE_FEATURES[ROLE_VIEWER]
    assert e < a and v < e
    # 且 viewer 恰是两个只读 feature，editor 只多 kb.upload（上传落 DRAFT）
    assert v == frozenset({"chat.run", "session.history"})
    assert e - v == frozenset({"kb.upload"})


def test_role_codes_are_closed_vocabulary():
    assert ROLES == (ROLE_ADMIN, ROLE_EDITOR, ROLE_VIEWER)
    assert set(ROLE_FEATURES) == set(ROLES), "ROLE_FEATURES 的键必须恰好是三角色（多写空集键即漂移）"


# ---------------------------------------------------------------------------
# 格 3：1c 统一兜底口径 —— 原语仍 fail-closed，判定入口收敛到 viewer + D9 计数
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_role", [None, "", "root", "superadmin", "ADMIN"])
def test_unknown_role_converges_to_viewer_with_d9_count(bad_role, monkeypatch):
    """未知码 → viewer 能力集（不是空集），且每次兜底都计入 D9 可聚合计数。

    ``features_for_role`` 作为原语仍返回空集（不猜）；**判定入口** ``has_feature``
    经 ``effective_role`` 收敛，避免「子服务直调拿空集又不计数」的第二套口径。
    """
    _reset_counters(monkeypatch)
    assert features_for_role(bad_role) == frozenset()
    assert has_feature(bad_role, "chat.run") is True       # viewer 放行读面
    assert has_feature(bad_role, "data.unmasked") is False  # 写面仍拒绝
    assert az.role_fallback_count() == 2


def test_unknown_role_not_treated_as_admin():
    assert has_feature("root", "data.unmasked") is False


# ---------------------------------------------------------------------------
# 格 4：D9 兜底可见性（计数 + WARNING 去重）
# ---------------------------------------------------------------------------


def _reset_counters(monkeypatch):
    """隔离本件外的计数状态（模块级全局；测试互不传染）。"""
    monkeypatch.setattr(az, "_fallback_count", 0)
    monkeypatch.setattr(az, "_fallback_warned", set())


def test_effective_role_passes_valid_codes_through():
    for role in ROLES:
        assert effective_role(role) == role


def test_effective_role_falls_back_to_viewer_and_counts(monkeypatch):
    _reset_counters(monkeypatch)
    before = role_fallback_count()
    assert effective_role(None, tenant="t1", user="u1") == ROLE_VIEWER
    assert effective_role("ghost", tenant="t2", user="u2") == ROLE_VIEWER
    assert role_fallback_count() == before + 2, "unknown/None 每次都计数（可聚合计数是 R-1 的评据）"


def test_fallback_warning_dedupes_per_tenant_user(monkeypatch, caplog):
    _reset_counters(monkeypatch)
    with caplog.at_level(logging.WARNING, logger="agent_runtime.authorization"):
        for _ in range(3):  # 同一 (tenant,user) 反复兜底
            effective_role(None, tenant="dup", user="dupu")
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1, "WARNING 按 (tenant,user) 首次去重；3 次兜底只首条入日志"
    assert "dup" in warnings[0].getMessage()
    # 但计数不受去重影响（格 4 的另一半）
    assert role_fallback_count() == 3


def test_fallback_warning_distinguishes_new_pairs(monkeypatch, caplog):
    _reset_counters(monkeypatch)
    with caplog.at_level(logging.WARNING, logger="agent_runtime.authorization"):
        effective_role(None, tenant="a", user="x")
        effective_role(None, tenant="a", user="y")  # 同 tenant 不同 user ⇒ 新键
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 2


# ---------------------------------------------------------------------------
# 格 5：resolve_features 单一入口（H6）
# ---------------------------------------------------------------------------


class _Claims:
    """最小 TokenClaims 形状（鸭子类型；resolve_features 只读三个属性）。"""

    def __init__(self, role, tenant="t9", user="u9"):
        self.role = role
        self.tenant_id = tenant
        self.user_id = user


def test_resolve_features_none_claims_is_viewer_set(monkeypatch):
    """P8：静态 API_KEY 无 claims → viewer 兜底（与 D9 同一条规则，H6 一处兼现）。"""
    _reset_counters(monkeypatch)
    feats = resolve_features(None)
    assert feats == ROLE_FEATURES[ROLE_VIEWER]
    assert role_fallback_count() == 1, "兜底走同一计数通道（两路不各写一份）"


def test_resolve_features_with_role_claims(monkeypatch):
    _reset_counters(monkeypatch)
    assert resolve_features(_Claims(ROLE_ADMIN)) == ROLE_FEATURES[ROLE_ADMIN]
    assert resolve_features(_Claims(ROLE_VIEWER)) == ROLE_FEATURES[ROLE_VIEWER]
    assert role_fallback_count() == 0, "合法 claims 不触发兜底计数"


def test_resolve_features_unknown_role_code_falls_back(monkeypatch):
    _reset_counters(monkeypatch)
    assert resolve_features(_Claims("ghost", tenant="tk", user="uk")) == ROLE_FEATURES[ROLE_VIEWER]
    assert role_fallback_count() == 1
