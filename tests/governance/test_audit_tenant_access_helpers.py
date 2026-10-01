"""A1 审计脚本纯函数测试（无 DB 依赖，CI 可达）。

覆盖租户分布打标记的启发式逻辑与占位租户名正则——脚本主体需真实库，此处只验证判定
函数正确（避免误把真实租户名标成占位、或漏标孤立小租户）。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _load_script():
    path = REPO / "scripts" / "audit_tenant_access.py"
    spec = importlib.util.spec_from_file_location("audit_tenant_access", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_default_tenant_not_flagged_as_orphan():
    m = _load_script()
    # 默认租户即便行数小也不标孤立（它是兜底桶）
    assert m._tag_tenant("default", 3, "default", 5) == []


def test_orphan_small_tenant_flagged():
    m = _load_script()
    tags = m._tag_tenant("tenantA", 2, "default", 5)
    assert any("孤立小租户" in t for t in tags)


def test_large_non_default_not_orphan():
    m = _load_script()
    assert m._tag_tenant("tenantA", 1000, "default", 5) == []


def test_placeholder_name_flagged_but_real_tenant_not():
    m = _load_script()
    # 测试/占位名命中
    assert any("测试/占位" in t for t in m._tag_tenant("test_1", 100, "default", 5))
    assert any("测试/占位" in t for t in m._tag_tenant("demo", 999, "default", 5))
    # 真实租户名（如 tenantA / payments）不应被误标为占位
    assert not m._PLACEHOLDER_RE.match("tenantA")
    assert not m._PLACEHOLDER_RE.match("payments")
    assert not m._PLACEHOLDER_RE.match("acme-corp")


def test_placeholder_and_orphan_both_applied():
    m = _load_script()
    tags = m._tag_tenant("sample_x", 1, "default", 5)
    assert any("测试/占位" in t for t in tags)
    assert any("孤立小租户" in t for t in tags)


def test_checks_list_shape():
    m = _load_script()
    # 业务表清单含隔离加固落地的 7 张表
    assert set(m.BUSINESS_TABLES) == {
        "memories", "chunks", "sql_ddl", "sql_docs", "sql_examples",
        "episodic_memories", "procedural_memories",
    }
