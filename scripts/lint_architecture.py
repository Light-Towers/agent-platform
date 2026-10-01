#!/usr/bin/env python3
"""架构约束 lint：检测违反模块边界的调用模式。

P4-2：收紧 registry.execute 直接可见性。
架构契约：Skill → Skill 组合唯一合法路径是 runtime.delegate()，
禁止在 skills/ 和 planner/ 外部直接调 registry.execute()。

白名单（宿主代码，有意保留）：
- planner/protocol.py（delegate 实现内部）
- agent_server/agent/graph.py（_invoke 回退，向后兼容）
- skills/registry.py（SkillRegistry 自身）
- tests/ / eval/（测试与评测）

P6：禁止在 kernel 外对密钥类标识手写裸哈希（DUP-1 横向重复门禁，见下文）；
    并封锁【刻意保留的弱派生】``legacy_thread_id`` 的调用面（仅迁移脚本可用）。
P7：禁止在 kernel 外手写路径 containment / api 层绕过 ``guardrails.fs``（A 类横切收敛）。
P8：禁止在对外响应体（HTTP JSON / SSE 帧）回显异常消息或堆栈（C 类横切收敛）。
P9：禁止在 app 层裸调 ``monitor.report_tool*``（散点埋点，v3 合流并入）。
P10：禁止 ``from tools.*`` 直引 ``@tool`` 绕过 ``tool_registry.get_tool()``（v3 合流并入）。
P11：禁止无顶层 ``permissions:`` 块的 GitHub Actions workflow（GITHUB_TOKEN 未限权，
     对应 CodeQL ``actions/missing-workflow-permissions``，见 B7d 方案 §7）。
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 模式：匹配 registry.execute( 和 get_registry().execute(
_PATTERN = re.compile(r"(?:get_registry\(\)|registry)\.execute\s*\(")

# 白名单：允许直接调用 registry.execute 的文件（相对路径前缀匹配）
_WHITELIST = (
    "packages/agent-runtime/agent_runtime/planner/protocol.py",
    "packages/agent-runtime/agent_runtime/skills/registry.py",
    "applications/agent_server/agent/graph.py",
    "tests/",
    "eval/",
    "scripts/lint_architecture.py",
    # 各包自身测试
    "packages/agent-core/tests/",
    "packages/agent-runtime/tests/",
    "applications/agent_federation/tests/",
    "applications/agent_server/tests/",
    "applications/kefu-service/tests/",
    "applications/exhibition-agent/tests/",
    "applications/knowledge-service/tests/",
    "applications/nl2sql-service/tests/",
)


def check() -> list[str]:
    violations: list[str] = []
    for py_file in ROOT.rglob("*.py"):
        rel = py_file.relative_to(ROOT).as_posix()
        # 跳过 .venv / __pycache__ / .ruff_cache / IDE 临时文件
        if any(p in rel for p in (".venv", "__pycache__", ".ruff_cache", ".egg-info",
                                   ".codeartsdoer", ".codebuddy")):
            continue
        if any(rel.startswith(w) or rel == w for w in _WHITELIST):
            continue
        try:
            for lineno, line in enumerate(py_file.read_text(encoding="utf-8").splitlines(), 1):
                if _PATTERN.search(line):
                    violations.append(f"{rel}:{lineno}: {line.strip()}")
        except Exception:
            pass
    return violations


# ---------------------------------------------------------------------------
# P2 架构不变量：生产 FastAPI app 必须经 agent_core 统一工厂 ``build_api_app``
# 创建，由构造保证注册统一 500 脱敏 handler（仅扫 applications/**）。
# 见 docs/plans/plan-p2-unified-exception-handlers-2026-09-24.md §3.2/§3.3。
# 白名单：knowledge-service main.py（已有自实现 handler，D-3 本轮不迁移）、
# exhibition mock_server（dev fixture、非网关服务）；各 tests/ 已跳。
# ---------------------------------------------------------------------------
_FASTAPI_PATTERN = re.compile(r"\bFastAPI\s*\(")
_FASTAPI_WHITELIST = (
    "applications/knowledge-service/knowledge_service/main.py",
    "applications/exhibition-agent/exhibition_agent/mock_server/warehouse_mock.py",
)


def check_fastapi_apps() -> list[str]:
    violations: list[str] = []
    for py_file in ROOT.rglob("*.py"):
        rel = py_file.relative_to(ROOT).as_posix()
        if not rel.startswith("applications/"):
            continue
        if any(p in rel for p in (".venv", "__pycache__", ".ruff_cache", ".egg-info",
                                   ".codeartsdoer", ".codebuddy")):
            continue
        if "/tests/" in rel:
            continue
        if any(rel == w or rel.startswith(w) for w in _FASTAPI_WHITELIST):
            continue
        try:
            for lineno, line in enumerate(py_file.read_text(encoding="utf-8").splitlines(), 1):
                if _FASTAPI_PATTERN.search(line):
                    violations.append(f"{rel}:{lineno}: {line.strip()}")
        except Exception:
            pass
    return violations


# ---------------------------------------------------------------------------
# P5 架构不变量：workspace 成员间顶层包名不得重复。
# 背景：uv/hatchling editable 安装以朴素 .pth 把成员源码根整体加入 sys.path，
# 源码根下任何含 __init__.py 的子目录都会成为可全局 import 的顶层包；
# 跨成员重名时解析结果取决于 .pth 顺序（隐式遮蔽，曾导致 ks 单测 collection 失败）。
# 历史冲突 eval（agent_federation vs knowledge-service）已于 2026-09-25 消歧义，
# 见 docs/plans/plan-workspace-toplevel-eval-disambiguation-2026-09-25.md。
# 规则：若成员源码根本身是包（含 __init__.py）则只暴露包名；否则暴露其下
# 含 __init__.py 且名为合法标识符的直接子目录（与 .pth 真实暴露机制同源）。
# ---------------------------------------------------------------------------
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _exposed_toplevel_names(source_root: Path) -> set[str]:
    """返回某 sys.path 暴露根下的顶层 regular package 名集合。"""
    if (source_root / "__init__.py").exists():
        # 源码根自身就是包：作为整体被暴露，其子目录已在包命名空间内，不占顶层
        return {source_root.name} if _IDENT_RE.match(source_root.name) else set()
    exposed: set[str] = set()
    for child in source_root.iterdir():
        if (
            child.is_dir()
            and not child.name.startswith((".", "_"))
            and _IDENT_RE.match(child.name)
            and (child / "__init__.py").exists()
        ):
            exposed.add(child.name)
    return exposed


def check_toplevel_package_clashes() -> list[str]:
    """跨 workspace 成员检测顶层包名重复；返回违规描述列表（空=通过）。"""
    with (ROOT / "pyproject.toml").open("rb") as f:
        data = tomllib.load(f)

    # 暴露根 = 各 workspace 成员目录 + 根包 wheel packages 的父目录（如 applications/）
    source_roots: list[Path] = [
        ROOT / m for m in data.get("tool", {}).get("uv", {}).get("workspace", {}).get("members", [])
    ]
    for pkg in data.get("tool", {}).get("hatch", {}).get("build", {}).get("targets", {}).get("wheel", {}).get("packages", []):
        pkg_dir = ROOT / pkg
        if pkg_dir.exists():
            source_roots.append(pkg_dir.parent)

    owners: dict[str, list[Path]] = {}
    seen_roots: set[Path] = set()
    for root in source_roots:
        if not root.is_dir() or root in seen_roots:
            continue
        seen_roots.add(root)
        for name in _exposed_toplevel_names(root):
            owners.setdefault(name, []).append(root)

    violations: list[str] = []
    for name, roots in sorted(owners.items()):
        uniq = sorted({r.relative_to(ROOT).as_posix() for r in roots})
        if len(uniq) > 1:
            violations.append(f"顶层包名 '{name}' 被多个成员同时暴露: {uniq}")
    return violations


# ---------------------------------------------------------------------------
# P6 架构不变量（DUP-1 横向重复门禁）：密钥 → 稳定指纹 只能由 kernel 单一实现
# ``agent_core.guardrails.auth.fingerprint`` 产出。背景：CodeQL
# ``py/weak-sensitive-data-hashing`` 的 5 条告警是同一操作被抄 4 遍且截断语义
# 分裂（全量 vs ``[:12]`` 48bit、均无服务端 pepper）——前 3 条 lint 均为「禁止危险调
# 用点」型检测，对「同类横切逻辑多实现」这一维度全空白，故新增本不变量防复发。
# 规则：同一行出现弱哈希调用 + 密钥语义标识即失败。
#   · ``hmac.new(secret, msg, hashlib.sha256)`` 不命中（hashlib 无紧跟 ``(``），
#     因 HMAC 才是本门禁鼓励的写法；
#   · 非敏感分桶（如 ``gateway/gray.py`` 的 ``md5(user_id)``）不含密钥语义名，
#     天然不在拦截面内（无需为其开白名单）。
# 白名单：kernel 单一实现所在文件（含迁移用的 legacy 派生助手）。
# ---------------------------------------------------------------------------
_WEAK_HASH_CALL = re.compile(r"hashlib\.(?:md5|sha1|sha224|sha256|sha384|sha512)\s*\(")
_SECRET_IDENT = re.compile(r"api_?key|apikey|secret|passwo?rd|access_key|private_key", re.IGNORECASE)
_BARE_SECRET_HASH_WHITELIST = (
    "packages/agent-core/agent_core/guardrails/auth.py",
)


def _is_bare_secret_hash_line(stripped: str) -> bool:
    """单行判定（抽出以便反例单测）：弱哈希调用 + 密钥语义标识同行共现。

    纯注释行不判（文档/说明常引用反例写法）。
    """
    if stripped.startswith("#"):
        return False
    return bool(_WEAK_HASH_CALL.search(stripped) and _SECRET_IDENT.search(stripped))


def check_bare_secret_hashing() -> list[str]:
    """扫全仓：白名单外禁对 api_key/secret 类变量裸用 hashlib（DUP-1）。"""
    violations: list[str] = []
    for py_file in ROOT.rglob("*.py"):
        rel = py_file.relative_to(ROOT).as_posix()
        if any(p in rel for p in (".venv", "__pycache__", ".ruff_cache", ".egg-info",
                                   ".codeartsdoer", ".codebuddy", "courses/")):
            continue
        if "/tests/" in rel or rel.startswith("tests/"):
            continue
        if any(rel == w or rel.startswith(w) for w in _BARE_SECRET_HASH_WHITELIST):
            continue
        try:
            for lineno, line in enumerate(py_file.read_text(encoding="utf-8").splitlines(), 1):
                stripped = line.strip()
                if _is_bare_secret_hash_line(stripped):
                    violations.append(f"{rel}:{lineno}: {stripped}")
        except Exception:
            pass
    return violations


# ---------------------------------------------------------------------------
# P6-2：【刻意保留的弱派生】``legacy_thread_id`` 调用面封闭。
# 背景：该函数必须复算升级前的 ``user-{sha256(api_key)[:12]}``（48bit 截断），否则
# 历史会话目录 / checkpointer ``thread_id`` 无法找回。Batch 2 当时只靠 docstring
# 「业务代码调用即违反 DUP-1」的**约定**约束，而 kernel 在 P6 白名单内， lint 拦不住
# 新增调用点——PR 重扫时 CodeQL 果然又把这条当新告警报了出来（约定会腐，故升级为门禁）。
# 规则：除 kernel 定义处与迁移脚本外，出现 ``legacy_thread_id(`` 调用即失败。
# ---------------------------------------------------------------------------
_LEGACY_ID_CALL = re.compile(r"\blegacy_thread_id\s*\(")
_LEGACY_ID_ALLOWED = (
    "packages/agent-core/agent_core/guardrails/auth.py",  # 定义 + __all__
    "scripts/migrate_thread_identity.py",  # 唯一合法消费者（一次性迁移）
)


def _is_legacy_id_call_line(stripped: str) -> bool:
    """单行判定（抽出以便反例单测）：弱派生名后紧跟左括号（调用或定义形式）。

    本文刻意不写出完整的字面匹配形式，否则本文件会命中自己的规则（与
    ``_WEAK_HASH_CALL`` 的写法同理）。
    """
    if stripped.startswith("#"):
        return False
    return bool(_LEGACY_ID_CALL.search(stripped))


def check_legacy_identity_calls() -> list[str]:
    """扫全仓：白名单外禁调用 ``legacy_thread_id``（弱派生不得进入业务链路）。"""
    violations: list[str] = []
    for py_file in ROOT.rglob("*.py"):
        rel = py_file.relative_to(ROOT).as_posix()
        if _skipped_rel(rel):
            continue
        if rel in _LEGACY_ID_ALLOWED:
            continue
        try:
            for lineno, line in enumerate(py_file.read_text(encoding="utf-8").splitlines(), 1):
                stripped = line.strip()
                if _is_legacy_id_call_line(stripped):
                    violations.append(f"{rel}:{lineno}: {stripped}")
        except Exception:
            pass
    return violations


# ---------------------------------------------------------------------------
# P7 架构不变量（「用户可控路径」横切关注点单一实现门禁，CodeQL py/path-injection 根因）：
# containment 与文件名净化只能由 kernel ``agent_core.guardrails.fs`` 提供。
# 背景：``agent_federation/api/server.py`` 4 个文件端点各自手写
# ``resolve()`` + ``is_relative_to()``（防护有效但语义不一致，且散在私有写法难以被
# CodeQL / 人工 review 认定为统一 sanitizer）。与 P6 同构：前 3 条不变量均为
# 「禁止危险调用点」型，本不变量守的是「同一横切逻辑不得第二次实现」这一维度。
# 两条子检查：
#   P7-1 白名单外禁手写 ``.is_relative_to(``（路径包含判定只允许 kernel 一处）；
#   P7-2 api 层（``applications/**`` 下路径含 ``/api/`` 的模块）出现文件 I/O 出口
#        （``FileResponse(`` / ``.rglob(`` / ``.glob(``）时，该文件必须调用
#        ``safe_join`` / ``resolve_within``，否则视为新增端点绕过护栏。
# 白名单：kernel 单一实现文件；P7-2 另含「路径来自模块常量、无请求输入」的静态页面站点。
# ---------------------------------------------------------------------------
_MANUAL_CONTAINMENT = re.compile(r"\.is_relative_to\s*\(")
_FS_CONTAINMENT_WHITELIST = (
    "packages/agent-core/agent_core/guardrails/fs.py",
)

_API_IO_MARKER = re.compile(r"\bFileResponse\s*\(|\.rglob\s*\(|\.glob\s*\(")
_FS_HELPER_USE = re.compile(r"\bsafe_join\s*\(|\bresolve_within\s*\(")
_FS_IO_WHITELIST = (
    # 静态资源页：路径来自 PROJECT_ROOT / 模块常量拼接，不接受请求输入
    "applications/knowledge-service/knowledge_service/api/import_router.py",
    "applications/knowledge-service/knowledge_service/api/query_router.py",
)


def _skipped_rel(rel: str) -> bool:
    """扫描排除面：依赖/缓存/IDE 产物/课件示例/测试代码（与 P6 保持一致）。"""
    if any(p in rel for p in (".venv", "__pycache__", ".ruff_cache", ".egg-info",
                              ".codeartsdoer", ".codebuddy", "courses/")):
        return True
    return "/tests/" in rel or rel.startswith("tests/")


def _is_manual_containment_line(stripped: str) -> bool:
    """单行判定（抽出以便反例单测）：手写 ``is_relative_to`` containment。

    纯注释行不判（文档/方案常引用旧写法）。
    """
    if stripped.startswith("#"):
        return False
    return bool(_MANUAL_CONTAINMENT.search(stripped))


def _api_io_violation(text: str) -> str | None:
    """文件粒度判定（抽出以便单测）：有文件 I/O 出口但未调 kernel 护栏→返回首个违规行。"""
    if not _API_IO_MARKER.search(text) or _FS_HELPER_USE.search(text):
        return None
    for lineno, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if _API_IO_MARKER.search(stripped):
            return f"{lineno}: {stripped}（无 safe_join/resolve_within 调用）"
    return None


def check_manual_path_containment() -> list[str]:
    """扫全仓：白名单外禁手写 ``is_relative_to`` 做路径 containment（P7-1）。"""
    violations: list[str] = []
    for py_file in ROOT.rglob("*.py"):
        rel = py_file.relative_to(ROOT).as_posix()
        if _skipped_rel(rel):
            continue
        if any(rel == w or rel.startswith(w) for w in _FS_CONTAINMENT_WHITELIST):
            continue
        try:
            for lineno, line in enumerate(py_file.read_text(encoding="utf-8").splitlines(), 1):
                stripped = line.strip()
                if _is_manual_containment_line(stripped):
                    violations.append(f"{rel}:{lineno}: {stripped}")
        except Exception:
            pass
    return violations


def check_api_layer_path_io() -> list[str]:
    """扫 api 层：有文件 I/O 出口但未过 kernel ``guardrails.fs`` 护栏的文件（P7-2，按文件粒度）。"""
    violations: list[str] = []
    for py_file in ROOT.rglob("*.py"):
        rel = py_file.relative_to(ROOT).as_posix()
        if not rel.startswith("applications/") or "/api/" not in f"/{rel}":
            continue
        if _skipped_rel(rel):
            continue
        if any(rel == w or rel.startswith(w) for w in _FS_IO_WHITELIST):
            continue
        try:
            text = py_file.read_text(encoding="utf-8")
        except Exception:
            continue
        hit = _api_io_violation(text)
        if hit:
            violations.append(f"{rel}:{hit}")
    return violations


# ---------------------------------------------------------------------------
# P8 架构不变量（「内部异常详情」横切关注点，CodeQL py/stack-trace-exposure 根因）：
# 对外响应体（HTTP JSON / SSE 帧）不得回显异常消息或堆栈。
# 背景：``install_error_handlers`` 只能兜住「未捕获异常 → 500 信封」，对已经自行
# ``except`` 并 ``return JSONResponse`` / 推 SSE 帧的站点无能为力（流已开、状态码已发），
# 这类站点历史上的 ``str(e)`` / ``f"...{e}"`` 会把内部路径 / 上游响应体 / SQL 片段
# 送到客户端。脱敏边界点唯一：kernel ``agent_core.guardrails.errors``
# （未捕获异常走 ``install_error_handlers``，自行 catch 的出口走 ``mask_exception_for_client``）。
# 作用域：``applications/**`` 下含 HTTP/SSE 出口标记的模块（与 P7-2 同构的文件粒度前置）。
# 放行（不进判定面）：
#   1. 注释行（文档/方案常引用旧写法）；
#   2. 服务端日志行（``logger.*``——异常全貌的合规去向）；
#   3. 仅异常类名 ``type(x).__name__``（不含消息，不属堆栈回显）；
#   4. 4xx 客户端错误回显（D-2=A：不动各 app 现有 4xx ``{detail}`` 信封，
#      输入校验失败详情面向调用方自身输入）。
# ---------------------------------------------------------------------------
_HTTP_EXIT_MARKER = re.compile(
    r"@app\.|@router\.|add_api_route|JSONResponse\(|HTTPException\(|StreamingResponse\("
    r"|TextResponse\(|FileResponse\(|push_to_session\(|sse_pack\(|\b_sse\("
)
_EXC_MSG_CALL = re.compile(r"\bstr\(\s*(?:e|exc|err|error|exception)\b", re.IGNORECASE)
_EXC_F_INTERP = re.compile(r"\{\s*(?:e|exc|err|error|exception)\s*(?::[^{}]*)?\}")
_F_PREFIX = re.compile(r"\bf['\"]")
_TB_CALL = re.compile(r"\btraceback\.|format_exc\s*\(")
_CLASS_NAME_TOKEN = re.compile(r"type\(\s*[A-Za-z_]\w*\s*\)\.__name__")
_LOGGER_LINE = re.compile(r"\b(?:logger|log)\w*\.\w+\(")
_STATUS_4XX = re.compile(r"status_code\s*=\s*4\d\d")
# 白名单：故意置空——本不变量不允许静默例外，任何新增必须先在方案文档里说理。
_EXC_ECHO_WHITELIST: tuple[str, ...] = ()


def _is_http_exit_module(text: str) -> bool:
    """文件粒度前置：是否 HTTP/SSE 出口模块（含路由装饰器或响应/帧构造）。"""
    return bool(_HTTP_EXIT_MARKER.search(text))


def _is_exception_echo_line(stripped: str) -> bool:
    """单行判定（抽出以便反例单测）：对外出口回显异常消息 / 堆栈。

    先把仅类名写法 ``type(x).__name__`` 从行内剔除，剩下的才是消息级插值；
    否则 ``f"{type(e).__name__}: {e}"`` 这种「含消息」的行会被误放行。
    """
    if stripped.startswith("#"):
        return False
    if _STATUS_4XX.search(stripped):
        return False
    if _LOGGER_LINE.search(stripped):
        return False
    line = _CLASS_NAME_TOKEN.sub("__cls__", stripped)
    if _TB_CALL.search(line):
        return True
    has_interp = bool(_EXC_MSG_CALL.search(line)) or (
        bool(_EXC_F_INTERP.search(line)) and bool(_F_PREFIX.search(line))
    )
    return has_interp


def check_exception_echo_in_api_responses() -> list[str]:
    """扫 applications/** 的 HTTP/SSE 出口模块：禁回显异常消息/堆栈（P8）。"""
    violations: list[str] = []
    for py_file in ROOT.rglob("*.py"):
        rel = py_file.relative_to(ROOT).as_posix()
        if not rel.startswith("applications/"):
            continue
        if _skipped_rel(rel):
            continue
        if any(rel == w or rel.startswith(w) for w in _EXC_ECHO_WHITELIST):
            continue
        try:
            text = py_file.read_text(encoding="utf-8")
        except Exception:
            continue
        if not _is_http_exit_module(text):
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if _is_exception_echo_line(stripped):
                violations.append(f"{rel}:{lineno}: {stripped}")
    return violations


# ---------------------------------------------------------------------------
# P9 架构不变量（v3 合流并入，原「批 3」门禁）：tool 事件上报唯一出口 = agent_core.observability.observe_tool。
# applications/** 生产代码禁止裸调 monitor.report_tool / monitor.report_tool_outcome
# （散点埋点反模式，见 docs/plans/plan-tool-instrumentation-choke-point-2026-09-25.md
# §5 批 3）；outcome 语义经 ToolResult 返回承载（v3.1 定板）。
# 作用域仅 applications/**：kernel（agent_core/observability）为合法实现位；
# tests/ 由作用域排除；evaluation 订阅走 monitor.on 非本模式，天然不命中。
# ---------------------------------------------------------------------------
# 负向前瞻 (?<![\w.])：排除 foo_monitor / self._monitor 等误命中（仍精准匹配裸 monitor）
_TOOL_MONITOR_PATTERN = re.compile(r"(?<![\w.])monitor\.report_tool(?:_outcome)?\s*\(")
_TOOL_MONITOR_WHITELIST: tuple[str, ...] = ()


def check_tool_monitor_scatter() -> list[str]:
    """app 层禁止裸调 monitor.report_tool*（散点埋点）；返回违规描述列表。"""
    violations: list[str] = []
    for py_file in ROOT.rglob("*.py"):
        rel = py_file.relative_to(ROOT).as_posix()
        if not rel.startswith("applications/"):
            continue
        if any(p in rel for p in (".venv", "__pycache__", ".ruff_cache", ".egg-info",
                                   ".codeartsdoer", ".codebuddy")):
            continue
        if "/tests/" in rel:
            continue
        if any(rel == w or rel.startswith(w) for w in _TOOL_MONITOR_WHITELIST):
            continue
        try:
            for lineno, line in enumerate(py_file.read_text(encoding="utf-8").splitlines(), 1):
                if _TOOL_MONITOR_PATTERN.search(line):
                    violations.append(f"{rel}:{lineno}: {line.strip()}")
        except Exception:
            pass
    return violations


# ---------------------------------------------------------------------------
# P10 架构不变量（v3 合流并入，原「C1 防回归」）：禁用 from tools.* 直引 @tool 对象
# 绕过 tool_registry.get_tool()（一旦绕过就丢掉 tool 级观测）。
# ---------------------------------------------------------------------------
_TOOL_REGISTRY_PATH = ROOT / "applications" / "agent_federation" / "agent" / "tool_registry.py"
_DIRECT_IMPORT_PATTERN = re.compile(r"^\s*from\s+tools\.[\w.]*\s+import\s+(.+)$")


def _load_registry_tool_names() -> set[str]:
    """从 TOOL_REGISTRY 解析已注册 @tool 属性名（module:attr 的 attr 即工具名）。"""
    try:
        text = _TOOL_REGISTRY_PATH.read_text(encoding="utf-8")
    except OSError:
        return set()
    names: set[str] = set()
    for m in re.finditer(r'"([\w]+)"\s*:\s*"tools\.[\w]+:([\w]+)"', text):
        names.add(m.group(2))
    return names


def check_tool_direct_import() -> list[str]:
    """禁止经 ``from tools.* import <@tool>`` 直引绕过 tool_registry.get_tool()（C1 根因防回归）。

    批 2 已将六条挂载路径统一经 get_tool() 取用（含 subagent 直引、bridge 直引），
    本检查封死「未来新增工具时直接 import @tool 对象跳过观测包装」的回归面。
    合法例外：tool_registry.py 自身（用字符串延迟定位）、tests/、普通函数
    （如 check_knowledge_health 非 @tool，不在 TOOL_REGISTRY 故不命中）。
    """
    tool_names = _load_registry_tool_names()
    if not tool_names:
        return []
    violations: list[str] = []
    for py_file in ROOT.rglob("*.py"):
        rel = py_file.relative_to(ROOT).as_posix()
        if not rel.startswith("applications/"):
            continue
        if any(p in rel for p in (".venv", "__pycache__", ".ruff_cache", ".egg-info",
                                   ".codeartsdoer", ".codebuddy")):
            continue
        if "/tests/" in rel:
            continue
        if rel == "applications/agent_federation/agent/tool_registry.py":
            continue
        try:
            for lineno, line in enumerate(py_file.read_text(encoding="utf-8").splitlines(), 1):
                m = _DIRECT_IMPORT_PATTERN.match(line)
                if not m:
                    continue
                for part in m.group(1).split(","):
                    sym = part.strip().split(" as ")[0].strip()
                    if sym in tool_names:
                        violations.append(
                            f"{rel}:{lineno}: 直引 @tool '{sym}' 绕过 get_tool()"
                            f"（应经 tool_registry.get_tool 取用，否则缺失 tool 级事件）"
                        )
        except Exception:
            pass
    return violations


# ---------------------------------------------------------------------------
# P11 架构不变量：GitHub Actions workflow 必须显式声明顶层 GITHUB_TOKEN 权限。
# 根因（CodeQL actions/missing-workflow-permissions）：未声明 permissions 的 job
# 会回落到组织/仓库级默认（常为读写），任何被引入的第三方 action 都能拿写权限。
# 判据只认顶层块：顶层声明由构造保证覆盖该 workflow 的全部 job，而 job 级声明
# 易漏且不可核（确需某 job 提升权限时在 job 级单独声明，顶层块仍不得省略）。
# 作用域仅仓库根 .github/workflows/：GitHub 只解析该目录，applications/** 下的
# 同名目录不会被 Actions 运行时加载，列入只会误伤占位文件。
# ---------------------------------------------------------------------------
_WORKFLOW_DIR_REL = ".github/workflows"


def _workflow_permission_violation(text: str) -> str | None:
    """单个 workflow 文本的权限判定：违规返回原因，合规返回 ``None``。"""
    lines = text.splitlines()
    idx = None
    for i, line in enumerate(lines):
        if line.startswith("permissions:"):
            idx = i
            break
    if idx is None:
        return "缺顶层 permissions: 块（GITHUB_TOKEN 权限未限制）"
    value = lines[idx].split(":", 1)[1].strip()
    if value == "write-all":
        return "顶层 permissions 取值为 write-all（等于放开全部作用域）"
    if value in ("", "{}", "null", "~"):
        # 块式声明：必须至少有一个缩进的子作用域
        for nxt in lines[idx + 1:]:
            if not nxt.strip() or nxt.strip().startswith("#"):
                continue
            if nxt[:1] in (" ", "\t"):
                return None
            break
        return "顶层 permissions: 为空块（未声明任何作用域）"
    return None


def check_workflow_permissions() -> list[str]:
    """根 workflow 必须带顶层 permissions 块；返回违规描述列表。"""
    workflow_dir = ROOT / _WORKFLOW_DIR_REL
    if not workflow_dir.is_dir():
        # fail-closed：目录被搬走也不能静默放行，否则本门禁退化为约定
        return [f"{_WORKFLOW_DIR_REL}/ 不存在（workflow 目录被移动？请同步修正本门禁作用域）"]
    violations: list[str] = []
    for wf in sorted(workflow_dir.glob("*.yml")) + sorted(workflow_dir.glob("*.yaml")):
        rel = wf.relative_to(ROOT).as_posix()
        try:
            text = wf.read_text(encoding="utf-8")
        except OSError as exc:  # 读不到就是违规，不等于通过
            violations.append(f"{rel}: 无法读取（{exc}）")
            continue
        reason = _workflow_permission_violation(text)
        if reason:
            violations.append(f"{rel}: {reason}")
    return violations


def main() -> int:
    rc = 0
    v1 = check()
    if v1:
        print("P4-2 架构约束违反：registry.execute() 仅允许经 delegate() 调用")
        print("白名单文件外的直接调用：")
        for v in v1:
            print(f"  {v}")
        rc = 1
    else:
        print("P4-2 架构约束通过：无白名单外 registry.execute() 调用")

    v2 = check_fastapi_apps()
    if v2:
        print("P2 架构约束违反：生产 FastAPI app 必须经 agent_core build_api_app 创建（裸 FastAPI( 不允许）")
        print("白名单外的裸构造：")
        for v in v2:
            print(f"  {v}")
        rc = 1
    else:
        print("P2 架构约束通过：无白名单外裸 FastAPI() 构造")
    v3 = check_toplevel_package_clashes()
    if v3:
        print("P5 架构约束违反：workspace 成员间顶层包名重复（editable .pth 全暴露，解析取决于安装顺序）")
        print("修复：重命名其中一方或将工具目录收进各自命名空间包（见 plan-workspace-toplevel-eval-disambiguation）：")
        for v in v3:
            print(f"  {v}")
        rc = 1
    else:
        print("P5 架构约束通过：无跨成员顶层包名冲突")
    v4 = check_bare_secret_hashing() + check_legacy_identity_calls()
    if v4:
        print("P6 架构约束违反：密钥→指纹 必须走 kernel 单一实现 agent_core.guardrails.auth.fingerprint（DUP-1），")
        print("   且刻意保留的弱派生 legacy_thread_id 只允许迁移脚本调用（业务链路禁用）")
        print("白名单外对 api_key/secret 裸用 hashlib，或白名单外调用 legacy_thread_id 的站点：")
        for v in v4:
            print(f"  {v}")
        rc = 1
    else:
        print("P6 架构约束通过：无白名单外裸 hashlib 作用于密钥类标识，且 legacy_thread_id 调用面未外溢")
    v5 = check_manual_path_containment() + check_api_layer_path_io()
    if v5:
        print("P7 架构约束违反：路径 containment / 文件名净化 必须走 kernel 单一实现 agent_core.guardrails.fs（A 类 py/path-injection 根因）")
        print("白名单外手写 is_relative_to，或 api 层文件 I/O 未过 safe_join/resolve_within 护栏的站点：")
        for v in v5:
            print(f"  {v}")
        rc = 1
    else:
        print("P7 架构约束通过：无白名单外手写路径 containment，api 层文件 I/O 均经 kernel guardrails.fs")
    v6 = check_exception_echo_in_api_responses()
    if v6:
        print("P8 架构约束违反：对外响应体（HTTP JSON / SSE 帧）不得回显异常消息或堆栈（C 类 py/stack-trace-exposure 根因）")
        print("自行 catch 的出口请取 kernel 脱敏边界点：未捕获异常走 install_error_handlers，其余走 mask_exception_for_client（异常全貌只入服务端日志）：")
        for v in v6:
            print(f"  {v}")
        rc = 1
    else:
        print("P8 架构约束通过：HTTP/SSE 出口无异常消息/堆栈回显")
    v7 = check_tool_monitor_scatter()
    if v7:
        print("P9 架构约束违反：app 层禁止裸调 monitor.report_tool*（散点埋点）")
        print("修复：工具经 tool_registry.get_tool() 取用，outcome 语义经 ToolResult 返回承载：")
        for v in v7:
            print(f"  {v}")
        rc = 1
    else:
        print("P9 架构约束通过：无白名单外散点 tool 埋点")
    v8 = check_tool_direct_import()
    if v8:
        print("P10 架构约束违反：经 from tools.* import <@tool> 直引绕过 get_tool()（观测断点）")
        print("修复：统一经 tool_registry.get_tool() 取用：")
        for v in v8:
            print(f"  {v}")
        rc = 1
    else:
        print("P10 架构约束通过：无 @tool 直引旁路")
    v9 = check_workflow_permissions()
    if v9:
        print("P11 架构约束违反：workflow 必须显式声明顶层 permissions（GITHUB_TOKEN 最小权限）")
        print("修复：在 jobs: 之前加顶层块，只开该 workflow 实际需要的最小作用域（常规为 contents: read）：")
        for v in v9:
            print(f"  {v}")
        rc = 1
    else:
        print("P11 架构约束通过：所有根 workflow 均声明了顶层 permissions")
    return rc


if __name__ == "__main__":
    sys.exit(main())
