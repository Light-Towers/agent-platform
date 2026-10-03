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

P6：禁止对密钥类标识手写裸哈希（DUP-1 横向重复门禁，见下文）。B7b-5 反转后无白名单：
    kernel 的「凭据→摘要」单一实现已删，四个已退役入口名也不得再现（P6-3）。
P7：禁止在 kernel 外手写路径 containment / api 层绕过 ``guardrails.fs``（A 类横切收敛）。
P8：禁止在对外响应体（HTTP JSON / SSE 帧）回显异常消息或堆栈（C 类横切收敛）。
P9：禁止在 app 层裸调 ``monitor.report_tool*``（散点埋点，v3 合流并入）。
P10：禁止 ``from tools.*`` 直引 ``@tool`` 绕过 ``tool_registry.get_tool()``（v3 合流并入）。
P11：禁止无顶层 ``permissions:`` 块的 GitHub Actions workflow（GITHUB_TOKEN 未限权，
     对应 CodeQL ``actions/missing-workflow-permissions``，见 B7d 方案 §7）。
L-1：禁止手动 .__enter__()/.__exit__()；L-2：禁止经 app.state 散点取用 tracer；
L-3：观测 init 仅限装配点（三条见 plan-observability-global-remediation-2026-09-29.md §3.3）。
L-4：OTel/langfuse 可选依赖多处声明下界必须归一（同方案，防组合解析回溯）。
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
# 白名单：exhibition mock_server（dev fixture、非网关服务）；各 tests/ 已跳。
# knowledge-service main.py 已迁 build_api_app（观测方案 S2 尾项，2026-09-30），
# 其自有 M5 错误信封经 install_handlers=False 保留，不再占白名单。
# ---------------------------------------------------------------------------
_FASTAPI_PATTERN = re.compile(r"\bFastAPI\s*\(")
_FASTAPI_WHITELIST = (
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
# P6 架构不变量（DUP-1 横向重复门禁，**B7b-5 已反转**）：全仓不得再有「凭据 → 稳定
# 指纹」实现。背景：CodeQL ``py/weak-sensitive-data-hashing`` 的 5 条告警是同一操作被抄
# 4 遍且截断语义分裂（全量 vs ``[:12]`` 48bit、均无服务端 pepper）；当时新增本不变量，
# 以 kernel ``guardrails.auth`` 为唯一白名单实现。B7b 拆完三条链（会话身份 / 限流桶 /
# LLM 缓存键）后该实现已作为死代码删除 ⇒ **白名单置空**（继续留着就是留着缺口）。
# 两条子检查：
#   P6-1 同一行出现弱哈希调用 + 密钥语义标识即失败（无白名单）；
#   P6-3 「凭据→摘要」入口名（已退役的四个函数）以调用/定义形式出现即失败。
# 为何需要 P6-3：P6-1 的正则只抓 ``hashlib.<algo>(`` 同行共现，抓不到「调 kernel 函数
# 但被摘要的仍是凭据」这类写法，也抓不到改名绕过。改名消警是纯 gaming，而「把旧函数
# 名加回来」必须让 CI 失败而不是靠 review 自觉。判定抽成单行函数以便反例单测
# （沿用 ``_is_bare_secret_hash_line`` 的做法）。
# ---------------------------------------------------------------------------
_WEAK_HASH_CALL = re.compile(r"hashlib\.(?:md5|sha1|sha224|sha256|sha384|sha512)\s*\(")
_SECRET_IDENT = re.compile(r"api_?key|apikey|secret|passwo?rd|access_key|private_key", re.IGNORECASE)
# B7b-5：kernel 单一实现已删除 ⇒ 无白名单。置空而非删变量：保留名字供既有用例引用，
# 并让「未来有人想加回白名单」在 diff 里一眼可见。
_BARE_SECRET_HASH_WHITELIST: tuple[str, ...] = ()

# 本文刻意不写出「名字 + 左括号」的完整字面形式（改用 ``\s*`` 隔开），否则本文件会
# 命中自己的规则（与 ``_WEAK_HASH_CALL`` 的写法同理）。
_RETIRED_IDENTITY_HELPERS = re.compile(
    r"\b(?:fingerprint|derive_thread_id|legacy_thread_id|_hash_api_key)\s*\("
)


def _is_bare_secret_hash_line(stripped: str) -> bool:
    """单行判定（抽出以便反例单测）：弱哈希调用 + 密钥语义标识同行共现。

    纯注释行不判（文档/说明常引用反例写法）。
    """
    if stripped.startswith("#"):
        return False
    return bool(_WEAK_HASH_CALL.search(stripped) and _SECRET_IDENT.search(stripped))


def _is_retired_identity_helper_line(stripped: str) -> bool:
    """单行判定（抽出以便反例单测）：已退役的「凭据→摘要」入口名以调用/定义形式出现。

    纯注释行不判（文档/方案常引用旧写法）；名字后非左括号（如纯文本提及）也不判，
    守的是「真的又有人写/调它」而不是「文档里提到它」。
    """
    if stripped.startswith("#"):
        return False
    return bool(_RETIRED_IDENTITY_HELPERS.search(stripped))


def _iter_scanned_py_files():
    """逐仓 ``*.py`` 产出 ``(rel, path)``，跳过依赖/缓存/课件/测试面（见 ``_skipped_rel``）。"""
    for py_file in ROOT.rglob("*.py"):
        rel = py_file.relative_to(ROOT).as_posix()
        if _skipped_rel(rel):
            continue
        yield rel, py_file


def check_bare_secret_hashing() -> list[str]:
    """扫全仓：禁对 api_key/secret 类变量裸用 hashlib（DUP-1，B7b-5 后无白名单）。"""
    violations: list[str] = []
    for rel, py_file in _iter_scanned_py_files():
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


def check_retired_identity_helpers() -> list[str]:
    """扫全仓：已退役的「凭据→摘要」入口名不得再现（被治理对象已消失 ⇒ 无白名单）。

    P6-2 的继任者：旧规则守的是「弱派生只允许迁移脚本调用」，而枚举式迁移不再从密钥
    复算 ⇒ 函数本体已删，守的是「不得再加回来」。
    """
    violations: list[str] = []
    for rel, py_file in _iter_scanned_py_files():
        try:
            for lineno, line in enumerate(py_file.read_text(encoding="utf-8").splitlines(), 1):
                stripped = line.strip()
                if _is_retired_identity_helper_line(stripped):
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
# S1/S3 观测架构不变量（plan-observability-global-remediation-2026-09-29.md）：
# L-3：观测 init（init_tracing/init_otel）只允许出现在应用装配点（main/server）
#      与过渡门面，业务模块禁止私起——防止再长出第二个状态机（R6 根因）。
# L-1：禁止对上下文管理器手动 .__enter__()/.__exit__()——真 OTel（api≥1.27）
#      的 CM 生命周期与 SSE/后台任务跨 asyncio 任务边界不安全（R4/R8 根因，
#      NoOp 替身 __getattr__ 兜底使其在关闭态隐形）。
# ---------------------------------------------------------------------------
_INIT_PATTERN = re.compile(r"(?<!def )\b(?:init_tracing)\s*\(")
_INIT_WHITELIST = (
    "applications/agent_server/main.py",
    "applications/knowledge-service/knowledge_service/main.py",
    "applications/agent_federation/api/server.py",
    "applications/knowledge-service/eval/",  # 评测入口脚本（非服务进程，装配点等价）
    # 门面 otel.py 已退役（观测方案 §12，2026-09-30）：kernel 直调后 init_tracing 仅剩装配点。
    # exhibition 装配薄封装：无本地状态、委托 kernel，由其 server.py:59 装配点调用。
    "applications/exhibition-agent/exhibition_agent/observability/otel.py",
)

_MANUAL_CM_PATTERN = re.compile(r"\.__(?:enter|exit)__\s*\(")
_MANUAL_CM_WHITELIST: tuple[str, ...] = ()

# L-2（S2/S3）：禁止经 app.state 散点取用 tracer（R8/R12 土壤）——请求级 span 由
# TracingMiddleware 创建，业务层经 agent_core.tracing.current_span/record_request_attributes
# 取用；S2 迁移完成后白名单清零，新代码走散点即 CI 红。
_TRACER_STATE_PATTERN = re.compile(
    r"getattr\([^,)]*app\.state\s*,\s*[\"'](?:otel_)?tracer[\"']|app\.state\.(?:otel_)?tracer\b"
)
_TRACER_STATE_WHITELIST: tuple[str, ...] = ()


def _iter_prod_py():
    """遍历生产 py 文件（复用 _skipped_rel，与 P6/P7 同一套排除面）。"""
    for py_file in ROOT.rglob("*.py"):
        rel = py_file.relative_to(ROOT).as_posix()
        if _skipped_rel(rel):
            continue
        yield rel, py_file


def _is_code_line(line: str) -> bool:
    """过滤注释行与 rst 内联代码（``docstring 提及不算调用）。"""
    s = line.strip()
    return not (s.startswith("#") or "``" in s)


def check_init_scatter() -> list[str]:
    """L-3：观测 init 只允许在装配点/过渡门面出现（业务模块私起 init 即违规）。"""
    violations: list[str] = []
    for rel, py_file in _iter_prod_py():
        if not rel.startswith(("applications/", "packages/")):
            continue
        if any(rel == w or rel.startswith(w) for w in _INIT_WHITELIST):
            continue
        try:
            for lineno, line in enumerate(py_file.read_text(encoding="utf-8").splitlines(), 1):
                if _INIT_PATTERN.search(line) and _is_code_line(line):
                    violations.append(
                        f"{rel}:{lineno}: {line.strip()}"
                        f"（观测 init 仅限装配点 main/server 与过渡门面，禁止业务模块私起第二状态机）"
                    )
        except Exception:
            pass
    return violations


def check_manual_cm_lifecycle() -> list[str]:
    """L-1：禁止手动 .__enter__()/.__exit__()（CM 生命周期必须 with 配对，跨任务手动拆分配方=500）。"""
    violations: list[str] = []
    for rel, py_file in _iter_prod_py():
        if not rel.startswith(("applications/", "packages/")):
            continue
        if any(rel == w or rel.startswith(w) for w in _MANUAL_CM_WHITELIST):
            continue
        try:
            for lineno, line in enumerate(py_file.read_text(encoding="utf-8").splitlines(), 1):
                if _MANUAL_CM_PATTERN.search(line) and _is_code_line(line):
                    violations.append(
                        f"{rel}:{lineno}: {line.strip()}"
                        f"（span/attach 上下文管理器必须 with 配对；手动 enter/exit 跨异步任务边界不安全）"
                    )
        except Exception:
            pass
    return violations


def check_tracer_state_scatter() -> list[str]:
    """L-2：禁止 app.state 取用 tracer 散点（应走中间件请求 span + current_span）。"""
    violations: list[str] = []
    for rel, py_file in _iter_prod_py():
        if not rel.startswith("applications/"):
            continue
        if any(rel == w or rel.startswith(w) for w in _TRACER_STATE_WHITELIST):
            continue
        try:
            for lineno, line in enumerate(py_file.read_text(encoding="utf-8").splitlines(), 1):
                if _TRACER_STATE_PATTERN.search(line) and _is_code_line(line):
                    violations.append(
                        f"{rel}:{lineno}: {line.strip()}"
                        f"（tracer 不得经 app.state 散点取用；请求级 span 由 TracingMiddleware 创建，"
                        f"业务属性经 agent_core.tracing.record_request_attributes 写入）"
                    )
        except Exception:
            pass
    return violations


# ---------------------------------------------------------------------------
# L-4（S3，依赖契约）：OTel/langfuse 可选依赖版本区间三处归一（R1/R2 防回归）。
# 背景：根 [otel]、agent-core [tracing] 两处 extras 与
# federation [observability] 的 langfuse 各自声明下界曾漂移（sdk>=1.20 vs >=1.24），
# 叠加 langfuse v2/v3 代际冲突导致 pip 必回溯。规则：
#   1) OTel 软导入面均在声明位有 extras（门面退役后 agent-runtime 无 otel 直导入，
#      声明位已摘；kernel 在 agent-core [tracing]，装配方在根 [otel]）；
#   2) 同一包在多处声明时下界版本必须一致；
#   3) agent-runtime 必须为 langfuse 软导入（tracing.py）声明 extras，且下界与
#      federation [observability] 一致（import 路径 v2→v3 迁移属 S4，见方案 §3.4）。
# ---------------------------------------------------------------------------
_OTEL_EXTRAS_SITES = (
    ("pyproject.toml", "otel"),
    ("packages/agent-core/pyproject.toml", "tracing"),
    ("packages/agent-runtime/pyproject.toml", "langfuse"),
    ("applications/agent_federation/pyproject.toml", "observability"),
    # exhibition 观测后端软依赖（llm_obs 懒导入）；S4 迁入，同受 langfuse 下界归一约束。
    ("applications/exhibition-agent/pyproject.toml", "langfuse"),
)
_OTEL_TRACKED_PKGS = ("opentelemetry-api", "opentelemetry-sdk", "opentelemetry-exporter-otlp", "langfuse")


def _normalize_dep_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def check_otel_extras_alignment() -> list[str]:
    """L-4：校验 OTel/langfuse extras 声明存在且多处下界一致。"""
    violations: list[str] = []
    declared: dict[str, list[tuple[str, str]]] = {}  # pkg -> [(site, lower)]
    for rel, extra in _OTEL_EXTRAS_SITES:
        path = ROOT / rel
        try:
            with path.open("rb") as f:
                data = tomllib.load(f)
        except (OSError, tomllib.TOMLDecodeError) as e:
            violations.append(f"{rel}: 无法解析（{e}）")
            continue
        deps = data.get("project", {}).get("optional-dependencies", {}).get(extra)
        site = f"{rel}[{extra}]"
        if deps is None:
            violations.append(f"{site}: extras 缺失（观测软依赖必须显式声明，见方案 §3.3 L-4）")
            continue
        for req in deps:
            name = _normalize_dep_name(re.split(r"[<>=!~;\[ ]", req, 1)[0])
            if name not in _OTEL_TRACKED_PKGS:
                continue
            m = re.search(r">=\s*([0-9][0-9a-zA-Z.]*)", req)
            lower = m.group(1) if m else "(无下界)"
            declared.setdefault(name, []).append((site, lower))

    for pkg, sites in sorted(declared.items()):
        lowers = {lower for _site, lower in sites}
        if len(lowers) > 1:
            detail = " vs ".join(f"{site}: >={lower}" for site, lower in sites)
            violations.append(f"'{pkg}' 下界不一致（{detail}）——归一到方案敲定版本，防组合解析回溯")
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
    v4 = check_bare_secret_hashing() + check_retired_identity_helpers()
    if v4:
        print("P6 架构约束违反：全仓不得再有「凭据 → 摘要」实现（DUP-1 / CodeQL py/weak-sensitive-data-hashing），")
        print("   B7b 已拆完三条链并删除 kernel 单一实现 ⇒ 白名单为空，旧入口名也不得加回来")
        print("对 api_key/secret 裸用 hashlib，或再现已退役身份派生入口名的站点：")
        for v in v4:
            print(f"  {v}")
        rc = 1
    else:
        print("P6 架构约束通过：无裸 hashlib 作用于密钥类标识，且已退役的「凭据→摘要」入口名零再现")
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
    v10 = check_init_scatter()
    if v10:
        print("L-3 观测架构约束违反：init_tracing/init_otel 仅限装配点（main/server/过渡门面/eval 入口）调用")
        print("修复：接线收敛到应用启动装配点，业务模块经 get_tracer()/请求上下文取用（见 plan-observability-global-remediation）：")
        for v in v10:
            print(f"  {v}")
        rc = 1
    else:
        print("L-3 观测架构约束通过：观测 init 无业务模块私起")

    v11 = check_manual_cm_lifecycle()
    if v11:
        print("L-1 观测架构约束违反：禁止手动 .__enter__()/.__exit__()（真 OTel 下 CM 跨任务拆分配方=500）")
        print("修复：with start_span(...)/with use_context(...) 标准形配对，或 start_span(context=)+finally end()：")
        for v in v11:
            print(f"  {v}")
        rc = 1
    else:
        print("L-1 观测架构约束通过：无手动 CM 生命周期拆分配对")

    v12 = check_tracer_state_scatter()
    if v12:
        print("L-2 观测架构约束违反：禁止经 app.state 散点取用 tracer（应走 TracingMiddleware 请求 span）")
        print("修复：业务属性经 agent_core.tracing.record_request_attributes / current_span 写入：")
        for v in v12:
            print(f"  {v}")
        rc = 1
    else:
        print("L-2 观测架构约束通过：无 app.state tracer 散点取用")

    v13 = check_otel_extras_alignment()
    if v13:
        print("L-4 依赖契约违反：OTel/langfuse extras 必须声明且多处下界一致（R1/R2 防回归）")
        print("修复：归一到方案敲定下界（见 plan-observability §3.3 L-4）：")
        for v in v13:
            print(f"  {v}")
        rc = 1
    else:
        print("L-4 依赖契约通过：OTel/langfuse extras 声明齐备且下界一致")
    return rc


if __name__ == "__main__":
    sys.exit(main())
