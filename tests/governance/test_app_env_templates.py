# -*- coding: utf-8 -*-
"""非 pydantic-settings 应用的「代码读到的 env 键 ⊆ 模板已提及」门禁（roadmap #21 / P2-5）。

覆盖 `agent_federation` 与 `knowledge-service` 两家：它们的配置面是 `os.getenv` / `os.environ` 直读，
**没有模型可枚举字段**，所以不能套 `tests/governance/test_agent_server_env_template.py` 那套
（那份按 `Settings.model_fields` 比对）。本用例改用 AST 抽字面量键名。

**口径必须写成注释态也算数**（这是本批实测出来的关键一条）：
两家模板把可选开关一律写成 `# KEY=default` 的**注释态**（federation 文件里还自述"默认值取自代码中
os.getenv 第二参数"），那是刻意范式 —— 开关被部署时不该带着值生效。
所以判据是「**是否被提及**（active 或注释态）」，不是「是否 active」。
按 active 口径实取会得出 federation 52 / KS 11 的**假缺口**；按提及口径真缺是 7 / 10（已由 2026-10-16 补录）。

不覆盖的部分（登记，不当已完成）：
- **动态键名**（`os.getenv(f"...")` / 变量名）扫不出来：实取 federation 3 处、KS 2 处 ⇒ 本门禁只保证字面量键。
- `kefu-service` 实取 0 个字面量读取点（它经 `.env` + 配置文件装配），无可比对对象 ⇒ 不入本表，
  硬凑一条"0 缺"的用例等于空转。
- 全仓反向门禁（"模板里每个键都必须有读取方"）仍属待拍板：它要先覆盖所有 `os.getenv` 形态与各家前缀折算，
  见 `docs/plans/plan-unfinished-completion-schedule-2026-10-16.md` §3 第 12 项。
"""

from __future__ import annotations

import ast
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]

APPS: dict[str, tuple[str, str]] = {
    "agent_federation": ("applications/agent_federation", "applications/agent_federation/.env.example"),
    "knowledge-service": ("applications/knowledge-service", "applications/knowledge-service/.env.example"),
}

# 密钥类键名：模板里只允许留空或占位符写法，不得出现可直接使用的值
_SECRET = re.compile(r"(API_KEY|SECRET|PASSWORD|TOKEN|DSN|ACCESS_KEY)$")


def _reads(root: str) -> tuple[set[str], int]:
    """AST 抽本应用（排除 tests/）里字面量形态的 os.getenv / os.environ.get / os.environ[...] 键名。"""
    names: set[str] = set()
    dynamic = 0
    for py in sorted((ROOT / root).rglob("*.py")):
        rp = py.as_posix()
        if "/tests/" in f"/{rp}/" or py.name.startswith("test_") or ".venv" in rp:
            continue
        try:
            tree = ast.parse(py.read_text(encoding="utf-8-sig"))
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                parts: list[str] = []
                cur = node.func
                while isinstance(cur, ast.Attribute):
                    parts.append(cur.attr)
                    cur = cur.value
                if not (isinstance(cur, ast.Name) and cur.id == "os"):
                    continue
                if not (parts[-1] == "getenv" or (len(parts) >= 2 and parts[-1] == "get" and parts[-2] == "environ")):
                    continue
                if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    names.add(node.args[0].value)
                else:
                    dynamic += 1
            elif isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Load):
                cur = node.value
                if isinstance(cur, ast.Attribute) and isinstance(cur.value, ast.Name) and cur.value.id == "os" and cur.attr == "environ":
                    if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
                        names.add(node.slice.value)
                    else:
                        dynamic += 1
    return names, dynamic


def _mentioned(tmpl: str) -> tuple[set[str], dict[str, str]]:
    """返回（被提及的键集合，active 键→值）。注释态 `# KEY=value` 只计入"提及"。"""
    mentioned: set[str] = set()
    active: dict[str, str] = {}
    for line in (ROOT / tmpl).read_text(encoding="utf-8-sig").splitlines():
        s = line.strip()
        if "=" not in s:
            continue
        key = s.lstrip("#").split("=", 1)[0].strip()
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            continue
        mentioned.add(key)
        if not s.startswith("#"):
            active[key] = s.split("=", 1)[1].split("#", 1)[0].strip()
    return mentioned, active


def test_every_read_env_key_is_mentioned_in_that_apps_template():
    for app, (root, tmpl) in APPS.items():
        names, dynamic = _reads(root)
        assert names, f"{app}: AST 抽到 0 个键 ⇒ 本用例对该应用空转，需先修扫描"
        mentioned, _ = _mentioned(tmpl)
        missing = sorted(names - mentioned)
        assert not missing, (
            f"{app}: 代码读取而 .env.example 从未提及（active 与注释态都无）的键 {len(missing)} 个：{missing}。"
            f" 另有 {dynamic} 处动态键名不在本判据覆盖范围。"
        )


def test_secret_keys_are_never_shipped_with_a_live_value():
    """模板里密钥类键只能留空或写成**占位符** —— 防"把可直接使用的凭据提交进 .env.example"。

    判据取"是不是占位符"而不是"是否为空"：本仓既有范式有两种占位写法
    （`<YOUR_TAVILY_KEY>` 与 `your-key-here`），把它们判成违规会让门禁一跑就红、进而被绕过；
    真正要拦的是**形如可用凭据的值**。
    两次返工的经过：初版按"必须留空或含 <>"跑，KS 的 `OPENAI_API_KEY=your-key-here` 被误判；
    改成"含占位词即放行"的**子串**匹配后，反证用 `sk-proj-…xxxx3333` 塞进去照样绿灯 ——
    子串匹配会被真实凭据里恰好出现的 `xxxx` 蒙过。**现版改为整值精确匹配占位符白名单 + 含 `<` 即算占位**，
    并保留"留空通过"。反证见台账 §24（长随机串必须报红）。
    """
    exact_placeholders = {"your-key-here", "changeme", "replace-me", "replace_me", "placeholder", "xxx", "xxxx"}
    for app, (_root, tmpl) in APPS.items():
        _, active = _mentioned(tmpl)
        offenders = {}
        for key, value in active.items():
            if not _SECRET.search(key) or not value:
                continue
            if "<" in value or value.strip().lower() in exact_placeholders:
                continue
            offenders[key] = value
        assert not offenders, f"{app}: 模板里这些密钥键带着可直接使用的值：{sorted(offenders)}"
