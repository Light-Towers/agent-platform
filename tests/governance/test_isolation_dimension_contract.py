"""隔离维度契约测试（ADR-0006 §7 / plan T12，W5）。

固化「tenant 为边界 / workspace 为归属」的架构不变量，让隔离维度约定由
**门禁强制**而非靠自觉（AGENTS.md 全局优先原则第 3 层）。两个维度：

1. **建表契约**：扫描 ``agent_runtime`` migrations 全部 ``CREATE TABLE``，断言每张
   业务表含 ``tenant_id`` 列；平台级/系统/待判定表走显式白名单并登记理由。
   人为新增一张无 ``tenant_id`` 的业务表 → 本用例必红（plan §4 T12 验收）。

2. **谓词配对契约**：AST 提取 corpus / memory 模块的 SQL 字符串常量（Python 会
   把相邻字面量合并为单一 Constant），断言凡含 ``workspace_id =`` 归属谓词的查询
   必在同一 SQL 内含 ``tenant_id`` 边界谓词（ADR-0006 D1/D2：归属维不可单独隔离）。

不连真实 PG，纯静态，可 CI。已知误报源见各用例注释。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

# ---------------------------------------------------------------------------
# migrations 目录（经 importable 包定位，平台无关）
# ---------------------------------------------------------------------------
import agent_runtime.migrations as _migrations_pkg

MIGRATIONS_DIR = Path(_migrations_pkg.__file__).parent

# 白名单：不含 tenant_id 但经论证合法的表 → 必须显式登记理由（缺理由即视为违规）。
# 与 ADR-0006 §2.1 / §D3 数据分类对齐。
SYSTEM_TABLE_WHITELIST: dict[str, str] = {
    # —— 执行/持久化基础设施：按 execution_id / key 定位，非多租户业务数据 ——
    "execution_checkpoints": "durability 执行态，按 execution_id 定位（非业务数据）",
    "idempotency_keys": "幂等键表，按 key 定位（运行时基础设施）",
    "execution_leases": "执行租约，按 execution_id 定位（HA 协调）",
    "admission_slots": "准入槽位，按 execution_id 定位（HA 协调）",
    "side_effects": "副作用记录，按 execution_id 定位（HA effectively-once）",
    "execution_events": "执行事件流，按 execution_id 定位（可观测）",
    "trajectories": "轨迹快照，按 execution_id 定位（可观测/回放）",
    "execution_status": "执行状态，按 execution_id 定位（调度）",
    "awaitable_tasks": "可等待任务，按 execution_id 定位（外部回调）",
    "revert_audit": "会话回退审计，按 operator/session 定位（治理审计）",
    "mcp_call_audit": "MCP 调用审计，按 caller/server 定位（治理审计）",
    # —— 待判定 / 归属其他计划（登记为已知技术债，非本计划处置）——
    "admission_queue": "准入队列，仅 user_id；租户维度 ADR §4 W 表登记待另行判定",
    "episodic_memories": "执行记忆，隔离列由 plan-memory-hardening T1 处置（本计划不重复）",
    "procedural_memories": "技能记忆，租户内共享由 plan-memory-hardening T1 处置（本计划不重复）",
}

_CREATE_TABLE_RE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*\(",
    re.IGNORECASE,
)
_ALTER_ADD_TENANT_RE = re.compile(
    r"ALTER\s+TABLE\s+([A-Za-z_][A-Za-z0-9_]*)\s+ADD\s+COLUMN[^;]*\btenant_id\b",
    re.IGNORECASE,
)


def _extract_create_tables(sql: str) -> list[tuple[str, str]]:
    """从 SQL 文本提取 (表名, 建表体) —— 括号平衡截取列定义块。"""
    out: list[tuple[str, str]] = []
    for m in _CREATE_TABLE_RE.finditer(sql):
        name = m.group(1)
        i = m.end() - 1  # 指向 '('
        depth = 0
        start = i
        while i < len(sql):
            ch = sql[i]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        out.append((name, sql[start:i + 1]))
    return out


def _migration_sql() -> list[tuple[Path, str]]:
    return [
        (p, p.read_text(encoding="utf-8"))
        for p in sorted(MIGRATIONS_DIR.glob("*.up.sql"))
    ]


def _final_schema_state() -> tuple[dict[str, bool], dict[str, str], set[str]]:
    """按版本顺序回放迁移，得到每张表的最终状态。

    返回 (table -> has_tenant, table -> 首次创建文件, 全部 CREATE 表名集合)。
    CREATE 含 tenant_id 或后续 ALTER ADD COLUMN tenant_id 均计为“有租户边界”——
    隔离契约关注**最终 schema**，而非单文件快照（chunks/memories/sql_* 的 tenant_id
    由 004/006 增量补齐即属此形态）。
    """
    has_tenant: dict[str, bool] = {}
    origin: dict[str, str] = {}
    for path, sql in _migration_sql():
        for name, body in _extract_create_tables(sql):
            has_tenant.setdefault(name, re.search(r"\btenant_id\b", body) is not None)
            origin.setdefault(name, path.name)
        for m in _ALTER_ADD_TENANT_RE.finditer(sql):
            has_tenant[m.group(1)] = True
    return has_tenant, origin, set(has_tenant)


def test_every_business_table_declares_tenant_id():
    """不变量：迁移回放后的最终 schema，每张业务表必须含 tenant_id 列（否则须进白名单并登记理由）。"""
    has_tenant, origin, _ = _final_schema_state()
    offenders = [
        f"{origin[t]}:{t} 最终缺 tenant_id 列"
        for t, ok in has_tenant.items()
        if not ok and t not in SYSTEM_TABLE_WHITELIST
    ]
    assert not offenders, (
        "发现无 tenant_id 的业务表（ADR-0006 D1：tenant 为唯一安全边界）。"
        "若确为平台级/系统表，请在 SYSTEM_TABLE_WHITELIST 登记理由：\n"
        + "\n".join(sorted(offenders))
    )


def test_whitelist_entries_reference_existing_tables():
    """白名单条目必须仍存在于 migrations（防白名单漂移：表被删/改名则清理）。"""
    _, _, seen = _final_schema_state()
    stale = [t for t in SYSTEM_TABLE_WHITELIST if t not in seen]
    assert not stale, (
        "SYSTEM_TABLE_WHITELIST 含 migrations 中已不存在的表，请清理漂移条目：\n"
        + "\n".join(stale)
    )


def test_detector_flags_synthetic_tenantless_business_table():
    """验收（plan §4 T12）：人为建一张无 tenant_id 的业务表 → 检测器必须拦下。

    不往真实 migrations 注脏数据，而是直接验证检测器对合成 SQL 的判定，
    证明上述不变量断言确实能捕获回归（而非恒真）。
    """
    synthetic = (
        "CREATE TABLE IF NOT EXISTS widgets (\n"
        "    id BIGSERIAL PRIMARY KEY,\n"
        "    workspace_id TEXT NOT NULL DEFAULT 'default'\n"
        ");\n"
    )
    tables = _extract_create_tables(synthetic)
    assert tables and tables[0][0] == "widgets"
    body = tables[0][1]
    assert re.search(r"\btenant_id\b", body) is None, "widgets 无 tenant_id，应被判为违规"
    assert "widgets" not in SYSTEM_TABLE_WHITELIST, "未登记白名单 → 契约测试会因此表而红"
    # 反证：若补上 tenant_id 列（或后续 ALTER），则合规。
    with_tenant = "CREATE TABLE gadgets (id INT, tenant_id TEXT NOT NULL);"
    _gname, gbody = _extract_create_tables(with_tenant)[0]
    assert re.search(r"\btenant_id\b", gbody) is not None


def test_whitelisted_system_tables_have_reason():
    """白名单每条必须有非空理由（防止用空注释绕过契约）。"""
    bad = [t for t, why in SYSTEM_TABLE_WHITELIST.items() if not why.strip()]
    assert not bad, f"以下白名单条目缺少隔离理由：{bad}"


# ---------------------------------------------------------------------------
# 谓词配对契约（workspace_id 归属维不得脱离 tenant_id 边界单独出现）
# ---------------------------------------------------------------------------

# 扫描范围：真正对 corpus / memories 发 SQL 的模块。
SQL_SOURCE_SCAN = [
    "applications/agent_server/rag/store.py",
    "applications/agent_server/sql/schema_store.py",
    "packages/agent-core/agent_core/memory/typed.py",
    "packages/agent-runtime/agent_runtime/workspace_registry.py",
]

# 含归属/边界谓词特征的实际 SQL 关键字（排除文档/日志字符串误报）。
_TABLE_TOKENS = ("chunks", "sql_ddl", "sql_docs", "sql_examples", "memories", "workspaces")
_HAS_WS_PRED = re.compile(r"workspace_id\s*=")


def _string_constants(tree: ast.AST) -> list[str]:
    return [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def test_workspace_predicate_is_always_paired_with_tenant():
    """含 workspace_id = 谓词的 SQL 常量必须同时含 tenant_id 边界谓词。

    已知误报源：docstring/日志可能提及 workspace_id 但非 SQL —— 通过要求同串含
    表名 token + SQL 动词（SELECT/INSERT/UPDATE/DELETE/WHERE）过滤；仅对真正的
    查询语句施加配对约束。
    """
    root = Path(__file__).resolve().parents[2]
    violations: list[str] = []
    for rel in SQL_SOURCE_SCAN:
        src = (root / rel).read_text(encoding="utf-8")
        tree = ast.parse(src)
        for const in _string_constants(tree):
            if not _HAS_WS_PRED.search(const):
                continue
            is_sql = any(tok in const for tok in _TABLE_TOKENS) and re.search(
                r"\b(SELECT|INSERT|UPDATE|DELETE|WHERE)\b", const
            )
            if not is_sql:
                continue
            if not re.search(r"\btenant_id\b", const):
                violations.append(f"{rel}: SQL 含 workspace_id 谓词但缺 tenant_id：{const[:80]!r}")
    assert not violations, (
        "workspace 归属谓词脱离 tenant 边界单独出现（ADR-0006 D2）：\n"
        + "\n".join(violations)
    )
