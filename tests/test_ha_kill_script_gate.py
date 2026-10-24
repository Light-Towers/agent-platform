"""roadmap #16 门禁：强杀脚本缺 ``AGENT_PLATFORM_PG_URL`` 必须**拒跑**，不得静默连本机。

判据分三层，各防一种假绿：
- 子进程级（真实执行）：未注入变量 → 以配置缺失码退出，且输出无任何连接尝试痕迹。
- 纯函数级（反证）：注入即原样返回 → 证明上一条是「keyed 在该变量上」，不是脚本恒失败。
- 源码级（防绕过）：该变量的读取不得带默认值，且 ``init_pool`` 只接受注入值 → 防止日后
  把默认地址写回函数体内从而绕过前两条。

背景：脚本原先 ``os.environ.get("AGENT_PLATFORM_PG_URL", "postgresql://…@localhost:5433/…")``，
未注入时静默连开发机本机库，却照样打印「PASS」——取证结论对应的环境是不可知的。
"""

import ast
import os
import subprocess
import sys
from importlib import util
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _ROOT / "scripts" / "ha_real_kill_verify.py"
_ENV_VAR = "AGENT_PLATFORM_PG_URL"

# 「真的去连库」才会出现的痕迹；拒跑路径必须在连接之前就退出，故这些都应为 0 命中。
_CONNECT_ATTEMPT_TOKENS = (
    "psycopg",
    "init_pool",
    "Traceback",
    "Connection refused",
    "could not connect",
    "server closed the connection",
)


def _load_script_module():
    spec = util.spec_from_file_location("ha_real_kill_verify_under_test", _SCRIPT)
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_script_without_env() -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k not in {_ENV_VAR, "HA_MODE", "HA_EXEC_ID"}}
    return subprocess.run(
        [sys.executable, str(_SCRIPT)],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
        check=False,
    )


def test_script_refuses_when_pg_url_not_injected():
    """未注入变量 → 非零退出且点名缺哪个变量（判据：拒跑而非默连本机）。"""
    proc = _run_script_without_env()
    out = proc.stdout + proc.stderr

    assert proc.returncode != 0, f"脚本在未注入 {_ENV_VAR} 时竟跑起来了：{out}"
    assert _ENV_VAR in out, f"退出文案必须点名缺失的变量，否则运维无从修正：{out}"


def test_refusal_happens_before_any_connection_attempt():
    """拒跑必须早于连接：输出里不得有任何连接尝试痕迹。

    单看退出码不足以区分「拒跑」与「连了本机之后崩」，故按 token 反证。
    """
    proc = _run_script_without_env()
    out = proc.stdout + proc.stderr
    module = _load_script_module()

    assert proc.returncode == module.EXIT_CONFIG, (
        f"配置缺失须用独立退出码（与断言失败/超时区分），实际 {proc.returncode}：{out}"
    )
    hits = [token for token in _CONNECT_ATTEMPT_TOKENS if token.lower() in out.lower()]
    assert not hits, f"未注入变量时脚本出现了连接痕迹 {hits}：{out}"


def test_guard_is_keyed_on_env_var_not_always_failing(monkeypatch):
    """反证：注入了就原样返回——否则上面两条会因为「脚本恒失败」而空过。"""
    module = _load_script_module()
    sentinel = "postgresql://someone:somewhere@db.example:5432/agent_platform"
    monkeypatch.setenv(_ENV_VAR, sentinel)
    assert module._require_pg_url() == sentinel
    monkeypatch.setenv(_ENV_VAR, "   ")
    with pytest.raises(SystemExit) as blank:
        module._require_pg_url()
    assert blank.value.code == module.EXIT_CONFIG, "空白值同样按缺失处理（strip 后判空）"
    monkeypatch.delenv(_ENV_VAR, raising=False)
    with pytest.raises(SystemExit) as missing:
        module._require_pg_url()
    assert missing.value.code == module.EXIT_CONFIG


def _str_constants(tree: ast.AST) -> dict[str, str]:
    """模块级 ``NAME = "literal"`` 映射：脚本用常量别名引用环境变量名，需解析后再比对。"""
    out: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            if isinstance(node.value.value, str):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        out[target.id] = node.value.value
    return out


def test_pg_url_env_read_has_no_default_and_is_the_only_dsn_source():
    """源码级：该变量读取不得带**非空**默认值；init_pool 只接受注入值。

    空串默认值是允许的——它正是「缺失即拒跑」的写法（``.get(NAME, "")`` 后判空退出）；
    只有回落成真实地址才算违规。
    """
    src = ast.parse(_SCRIPT.read_text(encoding="utf-8-sig"))
    consts = _str_constants(src)
    offenders: list[str] = []
    unused_pool_args: list[str] = []
    seen_env_read = False

    for node in ast.walk(src):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_environ_get = isinstance(func, ast.Attribute) and func.attr in {"get", "getenv"}
        if is_environ_get and node.args and isinstance(node.args[0], (ast.Constant, ast.Name)):
            name = (
                node.args[0].value
                if isinstance(node.args[0], ast.Constant)
                else consts.get(node.args[0].id)
            )
            if name == _ENV_VAR:
                seen_env_read = True
                default = node.args[1] if len(node.args) > 1 else next(
                    (kw.value for kw in node.keywords if kw.arg == "default"), None
                )
                if default is not None and not (isinstance(default, ast.Constant) and not default.value):
                    offenders.append(f"{_SCRIPT.name}:{node.lineno} 给 {_ENV_VAR} 配了非空默认值")
        if isinstance(func, ast.Attribute) and func.attr == "init_pool":
            first = node.args[0] if node.args else None
            if not (isinstance(first, ast.Name) and first.id == "pg_url"):
                unused_pool_args.append(f"{_SCRIPT.name}:{node.lineno} init_pool 未使用注入的 pg_url")

    assert seen_env_read, f"脚本已不再读取 {_ENV_VAR}，本条门禁失去意义——请同步修订判据而不是删用例"
    assert not offenders, "禁止回落默认地址：\n" + "\n".join(offenders)
    assert not unused_pool_args, "连接点必须用注入值：\n" + "\n".join(unused_pool_args)


def test_pg_url_label_redacts_credentials():
    """取证日志只报库位置，DSN 里的凭证不得进 stdout。"""
    module = _load_script_module()
    label = module._pg_url_label("postgresql://agent:supersecret@db.internal:5433/agent_platform")
    assert "supersecret" not in label and "agent:" not in label
    assert label == "host=db.internal port=5433 db=agent_platform"
