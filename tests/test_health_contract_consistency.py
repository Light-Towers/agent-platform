"""跨服务 `/health` 形状一致性（roadmap 阶段1 #7 判据「跨服务一致性测试…不破坏下游」）。

为什么钉形状而不是统一形状：本仓当前有**三套**健康检查约定（逐个实读核实）——

| 约定 | 服务 | 说明 |
|---|---|---|
| `HealthResponse`（`status` ∈ `healthy/degraded/unhealthy`） | agent_server · nl2sql-service | 共享契约，`shared_schemas.health` |
| `{"status": "ok"}` | exhibition-agent · kefu-service（另 opencode gateway） | 字面值**不在** `HealthStatus` 枚举内 |
| `{"ok": true}` | knowledge-service（`/health/live` `/health/ready`） | 布尔键，形状不同；`ready` 在依赖不可用时返回 **503**，是 k8s 就绪探针契约 |

统一这三套会改**线上响应值**与**探针语义**（下游含 `deploy/k8s/scripts/verify.sh`、
`portforward.sh`、k8s liveness/readiness），属契约变更 ⇒ 按红线另出方案并先做消费方审计
（审计结论见 `docs/plans/plan-unfinished-completion-schedule-2026-10-16.md` §6）。

本文件因此只做两件**不破坏下游**的事：
① 钉住「已入共享契约的服务不许退回裸 dict」；② 钉住「不许冒出第四套约定」——
新服务必须归入已知两套之一，否则本测试红。这是漂移的现实成因：
`docs/architecture/agent-harness-capability-map.md` §4.4 记录过 README 把 agent_server 的
`status` 写成 `ok`（实测枚举是 `healthy`）——就是被这种不统一喂出来的文档错判。

判据取源码而非启动服务：本测试在根 session 跑，起 6 个 app 需要 PG/LLM/Milvus，
会把「格式一致性」测成「环境可用性」测试（后者已按守卫模式归到各自 session）。
"""

from __future__ import annotations

import ast
import re

import pytest
from shared_schemas.health import HealthResponse, HealthStatus

REPO = __import__("pathlib").Path(__file__).resolve().parents[1]

# 用响应模型 = 共享 HealthResponse 的服务（其健康面文件）
CONFORMING: dict[str, str] = {
    "agent_server": "applications/agent_server/api/health_router.py",
    "nl2sql-service": "applications/nl2sql-service/nl2sql_service/api/server.py",
}

# 仍用遗留裸 dict 约定的服务 → 其当前字面值
LEGACY: dict[str, tuple[str, str]] = {
    "exhibition-agent": ("applications/exhibition-agent/exhibition_agent/server.py", '"status": "ok"'),
    "kefu-service": ("applications/kefu-service/kefu_agent/__main__.py", '"status": "ok"'),
    "knowledge-service": ("applications/knowledge-service/knowledge_service/api", '"ok": True'),
}


def _read(rel: str) -> str:
    p = REPO / rel
    if p.is_dir():
        return "\n".join(f.read_text(encoding="utf-8-sig") for f in sorted(p.rglob("*.py")))
    return p.read_text(encoding="utf-8-sig")


def test_health_status_enum_is_the_shared_three_state():
    """共享枚举必须保持三态；加/减值都会改变下游解析，需另行决策。"""
    assert {s.value for s in HealthStatus} == {"healthy", "degraded", "unhealthy"}


def test_health_response_required_shape():
    """共享契约的必填字段 = status + version（下游按这两个键做判活）。"""
    required = {n for n, f in HealthResponse.model_fields.items() if f.is_required()}
    assert required == {"status", "version"}
    # 其余为「可选贡献位」：零破坏设计（默认 False/None），旧调用方不受影响
    assert HealthResponse.model_fields["otel_status"].default is None
    assert HealthResponse.model_fields["coordination"].default is False


@pytest.mark.parametrize("service", sorted(CONFORMING))
def test_conforming_services_stay_on_shared_health_response(service):
    """已入共享契约的服务不得退回裸 dict（退回即下游解析分叉，红线级）。"""
    src = _read(CONFORMING[service])
    assert "HealthResponse" in src, f"{service} 的 /health 不再声明共享 HealthResponse"


@pytest.mark.parametrize("service", sorted(LEGACY))
def test_legacy_services_are_actually_legacy_and_still_respondable(service):
    """遗留约定逐项核实：登记失实（其实已迁移）也要报红，否则台账本身会腐坏。

    同时钉住遗留字面值仍在——本测试不假装它们是错的，只让「不一致」显式可见。
    """
    rel, literal = LEGACY[service]
    src = _read(rel)
    has_health_route = re.search(r'(/health|health_router|def health)', src) is not None
    assert has_health_route, f"{service} 找不到 /health 面，登记路径已漂移"
    assert literal in src, (
        f"{service} 不再返回 {literal} —— 可能已迁到共享契约；"
        f"请把它从 LEGACY 挪进 CONFORMING 并重跑下游消费方审计"
    )


def _health_route_status_literals(src: str) -> set[str]:
    """只取 **/health 路由函数自身**返回的 `"status": "<字面值>"`。

    按整文件扫会假阳性：`agent_federation/api/server.py` 的上传响应有
    `{"status":"uploaded"}`、`warehouse_mock.py` 的场景数据有 `{"status":"scheduled"}`，
    它们只是与 /health 同处一个文件，与健康约定无关。
    """
    out: set[str] = set()
    # 上游 `_read()` 用 utf-8-sig：读到 BOM 时不把 U+FEFF 留给 ast.parse（`utf-8` 会），
    # 否则本测试会以"环境噪声"失败而不是以判据失败。全仓 `.py` 的 BOM 已于 2026-10-16 清零，
    # 保留这个读取约定是防再混入，不是迁就现状。
    tree = ast.parse(src, filename="<health>")
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        is_health = any(
            isinstance(d, ast.Call)
            and d.args
            and isinstance(d.args[0], ast.Constant)
            and isinstance(d.args[0].value, str)
            and d.args[0].value.startswith("/health")
            for d in node.decorator_list
        )
        if not is_health:
            continue
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Dict):
                continue
            for k, v in zip(sub.keys, sub.values, strict=False):
                if (
                    isinstance(k, ast.Constant)
                    and k.value == "status"
                    and isinstance(v, ast.Constant)
                    and isinstance(v.value, str)
                ):
                    out.add(v.value)
    return out


def test_no_fourth_health_convention_appears():
    """平台级：不得出现第 4 套 `status` 字面值。

    已知三套 = 枚举 healthy/degraded/unhealthy、`"ok"`、布尔 `"ok"` 键。
    任何新的 `{"status": "<别的东西>"}` 都会让聚合看板/告警按未知值处理。
    """
    known = {"healthy", "degraded", "unhealthy", "ok", "alive", "ready"}
    offenders: dict[str, set[str]] = {}
    scanned = 0
    for py in sorted((REPO / "applications").rglob("*.py")):
        if "tests" in py.parts or ".venv" in py.parts:
            continue
        src = py.read_text(encoding="utf-8-sig")
        literals = _health_route_status_literals(src)
        if not literals and "/health" not in src:
            continue
        scanned += bool(literals)
        unknown = literals - known
        if unknown:
            offenders[py.relative_to(REPO).as_posix()] = unknown
    # 自检：本测试依赖能扫到遗留字面值。扫到 0 个说明提取逻辑失效，
    # 那会让「禁第 4 套」变成永绿装饰 ⇒ 必须报错而不是静默通过。
    assert scanned >= 2, f"只从 /health 路由取到 {scanned} 个 status 字面值，提取逻辑可能已失效"
    assert not offenders, f"出现未知 /health status 字面值（第 4 套约定）：{offenders}"
