"""DUP-1 收敛的治理测试：P6 lint 门禁 + 会话身份迁移。

两部分对应 Batch 2 的「第③层强制门禁」与「派生算法变更的兼容路径」：
- ``scripts/lint_architecture.py`` P6：白名单外禁对 api_key/secret 裸用 hashlib；
  P6-2：【刻意保留的弱派生】``legacy_thread_id`` 调用面封闭（仅迁移脚本可用）；
- ``scripts/migrate_thread_identity.py``：legacy ``user-{sha256[:12]}`` → 新 ``user-{HMAC[:32]}`` 映射。

脚本非包内模块，按文件路径加载（与 pytest ``--import-mode=importlib`` 一致的做法）。
"""

import importlib.util
from pathlib import Path

import pytest
from agent_core.guardrails.auth import derive_thread_id, legacy_thread_id

_ROOT = Path(__file__).resolve().parents[2]


def _load_script(module_name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(module_name, _ROOT / relative_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


lint = _load_script("lint_architecture", "scripts/lint_architecture.py")
migrate = _load_script("migrate_thread_identity", "scripts/migrate_thread_identity.py")


# ---------------------------------------------------------------------------
# P6 门禁：单行判定 + 全仓零违规
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        'digest = hashlib.sha256((api_key or "").encode()).hexdigest()[:12]',
        'h = hashlib.md5(secret.encode("utf-8")).hexdigest()',
        "return hashlib.sha256(self.password.encode()).hexdigest()",
        'key = hashlib.sha256(access_key.encode()).hexdigest()',
    ],
)
def test_p6_flags_bare_hash_on_secret(line):
    assert lint._is_bare_secret_hash_line(line) is True


@pytest.mark.parametrize(
    "line",
    [
        # 正确写法：HMAC（hashlib 作为摘要构造器传入，无紧跟 `(`）
        'sig = hmac.new(secret.encode("utf-8"), payload.encode(), hashlib.sha256).digest()',
        # 非敏感标识：灰度分桶 / 查询串 / 内容指纹
        'hash_val = int(hashlib.md5(user_id.encode("utf-8")).hexdigest(), 16) % 100',
        'query_hash = hashlib.sha256(body.query.encode("utf-8")).hexdigest()[:16]',
        # 注释行放行（文档常引用反例）
        '# 历史实现：hashlib.sha256(api_key)[:12] 已废弃',
    ],
)
def test_p6_allows_legitimate_lines(line):
    assert lint._is_bare_secret_hash_line(line) is False


def test_p6_current_tree_has_zero_violations():
    """四处散点（kernel auth / llm registry / 两个 app 的 resolve_thread_id）必须已收敛。"""
    assert lint.check_bare_secret_hashing() == []


def test_p6_scan_flags_non_whitelisted_and_spares_kernel_whitelist(tmp_path, monkeypatch):
    """端到端扫描面（往 临时根 埋探针）：非白名单文件被报，kernel 单一实现文件不报。"""
    bad = tmp_path / "applications" / "agent_server" / "probe.py"
    bad.parent.mkdir(parents=True)
    bad.write_text(
        'import hashlib\n\n\ndef f(api_key):\n    return hashlib.sha256(api_key.encode()).hexdigest()\n',
        encoding="utf-8",
    )
    whitelisted = tmp_path / "packages" / "agent-core" / "agent_core" / "guardrails" / "auth.py"
    whitelisted.parent.mkdir(parents=True)
    whitelisted.write_text(
        'import hashlib\n\n\ndef legacy_thread_id(api_key):\n'
        '    return hashlib.sha256(api_key.encode()).hexdigest()[:12]\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(lint, "ROOT", tmp_path)

    violations = lint.check_bare_secret_hashing()
    assert len(violations) == 1
    assert "probe.py" in violations[0]


# ---------------------------------------------------------------------------
# P6-2 门禁：弱派生助手的调用面封闭（CodeQL PR 重扫把 :99 当新告警报出后补的硬拦截）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        "thread = legacy_thread_id(api_key)",
        "    return legacy_thread_id(provided)",
        "pairs = [legacy_thread_id(k) for k in keys]",
    ],
)
def test_p6_2_flags_legacy_id_call(line):
    assert lint._is_legacy_id_call_line(line) is True


@pytest.mark.parametrize(
    "line",
    [
        # 合规写法：走新派生
        "thread = derive_thread_id(api_key)",
        # 名字后非左括号（引用而非调用）
        "handlers = [legacy_thread_id]",
        # 注释行放行
        "# 旧实现 legacy_thread_id(x) 已禁止业务调用",
    ],
)
def test_p6_2_allows_legitimate_lines(line):
    assert lint._is_legacy_id_call_line(line) is False


def test_p6_2_current_tree_has_zero_violations():
    """当前树内该弱派生只出现在 kernel 定义处与迁移脚本（_LEGACY_ID_ALLOWED）。"""
    assert lint.check_legacy_identity_calls() == []


def test_p6_2_scan_flags_business_call_and_spares_allowed_sites(tmp_path, monkeypatch):
    """端到端扫描面：业务侧新增调用点被报；kernel 定义处与迁移脚本不报。"""
    bad = tmp_path / "applications" / "agent_server" / "probe.py"
    bad.parent.mkdir(parents=True)
    bad.write_text(
        "from agent_core.guardrails.auth import legacy_thread_id\n\n\n"
        "def f(api_key):\n    return legacy_thread_id(api_key)\n",
        encoding="utf-8",
    )
    allowed_script = tmp_path / "scripts" / "migrate_thread_identity.py"
    allowed_script.parent.mkdir(parents=True)
    allowed_script.write_text(
        "def pair(api_key):\n    return legacy_thread_id(api_key)\n", encoding="utf-8"
    )
    kernel = tmp_path / "packages" / "agent-core" / "agent_core" / "guardrails" / "auth.py"
    kernel.parent.mkdir(parents=True)
    kernel.write_text(
        "def legacy_thread_id(api_key):\n    return api_key\n", encoding="utf-8"
    )
    monkeypatch.setattr(lint, "ROOT", tmp_path)

    violations = lint.check_legacy_identity_calls()
    assert len(violations) == 1
    assert "probe.py" in violations[0]


# ---------------------------------------------------------------------------
# 迁移：legacy → new 映射可计算 + 目录改名
# ---------------------------------------------------------------------------


def test_thread_id_pair_matches_kernel_helpers():
    legacy, new = migrate.thread_id_pair("sk-abc")
    assert legacy == legacy_thread_id("sk-abc")
    assert new == derive_thread_id("sk-abc")
    assert legacy != new


def test_session_dir_name_matches_federation_upload_layout():
    # federation /api/upload：target_dir = updated_dir / f"session_{safe_thread_id}"
    assert migrate.session_dir_name("user-deadbeef") == "session_user-deadbeef"


def test_plan_session_renames_maps_legacy_to_new(tmp_path):
    legacy, new = migrate.thread_id_pair("sk-abc")
    src = tmp_path / migrate.session_dir_name(legacy)
    src.mkdir()
    (src / "a.txt").write_text("x", encoding="utf-8")

    pairs, skipped = migrate.plan_session_renames(tmp_path, legacy, new)
    assert skipped == []
    assert pairs == [(src, tmp_path / migrate.session_dir_name(new))]


def test_plan_session_renames_noop_when_legacy_absent(tmp_path):
    legacy, new = migrate.thread_id_pair("sk-abc")
    (tmp_path / migrate.session_dir_name(new)).mkdir()  # 已是新格式
    pairs, skipped = migrate.plan_session_renames(tmp_path, legacy, new)
    assert pairs == [] and skipped == []


def test_plan_session_renames_refuses_to_overwrite(tmp_path):
    """碰撞不覆盖：目标已存在时列为 skipped，交人工核实（防静默丢历史）。"""
    legacy, new = migrate.thread_id_pair("sk-abc")
    (tmp_path / migrate.session_dir_name(legacy)).mkdir()
    (tmp_path / migrate.session_dir_name(new)).mkdir()

    pairs, skipped = migrate.plan_session_renames(tmp_path, legacy, new)
    assert pairs == []
    assert len(skipped) == 1


def test_apply_session_renames_moves_content(tmp_path):
    legacy, new = migrate.thread_id_pair("sk-abc")
    src = tmp_path / migrate.session_dir_name(legacy)
    src.mkdir()
    (src / "a.txt").write_text("payload", encoding="utf-8")
    dst = tmp_path / migrate.session_dir_name(new)

    pairs, _ = migrate.plan_session_renames(tmp_path, legacy, new)
    assert migrate.apply_session_renames(pairs) == 1
    assert not src.exists()
    assert (dst / "a.txt").read_text(encoding="utf-8") == "payload"


def test_main_dry_run_does_not_rename(tmp_path, capsys):
    legacy, new = migrate.thread_id_pair("sk-abc")
    src = tmp_path / migrate.session_dir_name(legacy)
    src.mkdir()

    rc = migrate.main(["--api-key", "sk-abc", "--sessions-dir", str(tmp_path)])
    assert rc == 0
    assert src.exists()  # 未加 --apply 不得动盘
    out = capsys.readouterr().out
    assert legacy in out and new in out and "dry-run" in out


def test_main_apply_renames(tmp_path):
    legacy, new = migrate.thread_id_pair("sk-abc")
    src = tmp_path / migrate.session_dir_name(legacy)
    src.mkdir()

    rc = migrate.main(["--api-key", "sk-abc", "--sessions-dir", str(tmp_path), "--apply"])
    assert rc == 0
    assert not src.exists()
    assert (tmp_path / migrate.session_dir_name(new)).is_dir()


def test_main_requires_api_key(monkeypatch, capsys):
    monkeypatch.delenv("API_KEY", raising=False)
    assert migrate.main([]) == 2
    assert "API_KEY" in capsys.readouterr().err


def test_checkpoint_sql_covers_all_thread_keyed_tables():
    legacy, new = migrate.thread_id_pair("sk-abc")
    stmts = migrate.build_checkpoint_sql(legacy, new)
    joined = "\n".join(stmts)
    for table in ("checkpoints", "checkpoint_writes", "checkpoint_blobs"):
        assert f"UPDATE {table}" in joined
    # 只出语句、以绑定变量占位，不把未实跑验证的写操作固化进脚本
    assert "%s" in joined and legacy not in stmts[0].split("--")[0]
