"""DUP-1 收敛的治理测试：P6 lint 门禁 + 会话身份迁移。

两部分对应 Batch 2 的「第③层强制门禁」与「派生算法变更的兼容路径」：
- ``scripts/lint_architecture.py`` P6-1：全仓禁对 api_key/secret 裸用 hashlib（**B7b-5 已
  反转**：kernel 单一实现删除 ⇒ 白名单置空，连 kernel 路径也不得再现）；
  P6-3：已退役的四个「凭据→摘要」入口名（含 ``legacy_thread_id``）以调用/定义形式再现
  即失败 —— P6-2（「弱派生只允许迁移脚本调用」）随被治理对象消失而作废，**同等语义由
  P6-3 承接**（门禁换代，非删用例凑绿）；
- ``scripts/migrate_thread_identity.py``：**枚举式**迁移（旧凭据摘要 id → ``tenant-<主体>``），
  不再从密钥复算 ⇒ 脚本内不得出现 hashlib/hmac（下方 AST 用例锁死）。

脚本非包内模块，按文件路径加载（与 pytest ``--import-mode=importlib`` 一致的做法）。
"""

import ast
import importlib.util
from pathlib import Path

import pytest
from agent_core.guardrails.auth import resolve_thread_identity

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
    """散点必须已收敛：两个 app 的会话身份不再对凭据摘要（B7b-4 后连 ``derive_thread_id`` 已删）。"""
    assert lint.check_bare_secret_hashing() == []


def test_p6_scan_no_longer_spares_kernel_file(tmp_path, monkeypatch):
    """端到端扫描面（往临时根埋探针）：**白名单已空** ⇒ kernel 路径探针同样被报。

    取代原「非白名单被报 / kernel 单一实现豁免」用例：豁免对象（kernel 指纹实现）
    已作为死代码删除，若还有人往 kernel 里加回裸哈希，本用例必须红。
    """
    app_probe = tmp_path / "applications" / "agent_server" / "probe.py"
    app_probe.parent.mkdir(parents=True)
    kernel_probe = tmp_path / "packages" / "agent-core" / "agent_core" / "guardrails" / "auth.py"
    kernel_probe.parent.mkdir(parents=True)
    offending = (
        'import hashlib\n\n\ndef f(api_key):\n'
        '    return hashlib.sha256(api_key.encode()).hexdigest()\n'
    )
    app_probe.write_text(offending, encoding="utf-8")
    kernel_probe.write_text(offending, encoding="utf-8")
    monkeypatch.setattr(lint, "ROOT", tmp_path)

    violations = lint.check_bare_secret_hashing()
    assert len(violations) == 2, violations
    assert any("applications/agent_server/probe.py" in v for v in violations)
    assert any("guardrails/auth.py" in v for v in violations)


def test_p6_whitelist_is_empty_by_design():
    """契约锁：白名单必须为空（有人想「留个例外」就得先改这条断言，diff 里一眼可见）。"""
    assert lint._BARE_SECRET_HASH_WHITELIST == ()


# ---------------------------------------------------------------------------
# P6-3 门禁：已退役「凭据→摘要」入口名不得再现（P6-2 的继任者）
# P6-2 守的是「弱派生只允许迁移脚本调用」；枚举式迁移不再从密钥复算 ⇒ 函数本体已删，
# 被治理对象消失 ⇒ 门禁换代为「不得再加回来」（含改名绕过的四个已知入口名）。
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        "thread = legacy_thread_id(api_key)",
        "    return derive_thread_id(provided)",
        "pairs = [fingerprint(k) for k in keys]",
        "digest = _hash_api_key(secret)",
        # 定义形态同样被拦（把旧函数整个加回来）
        "def fingerprint(secret, pepper):",
    ],
)
def test_p6_3_flags_retired_identity_helper(line):
    assert lint._is_retired_identity_helper_line(line) is True


@pytest.mark.parametrize(
    "line",
    [
        # 合规写法：主体化派生，不涉凭据
        "thread = resolve_thread_identity(principal)",
        # 名字后非左括号（引用而非调用）
        "handlers = [legacy_thread_id]",
        # 注释行放行（文档常引用反例）
        "# 旧实现 legacy_thread_id(x) 已禁止业务调用",
        # 同行无旧入口名
        "return hashlib.sha256(query.encode()).hexdigest()",
    ],
)
def test_p6_3_allows_legitimate_lines(line):
    assert lint._is_retired_identity_helper_line(line) is False


def test_p6_3_current_tree_has_zero_violations():
    """当前树内四个入口名已彻底消失（kernel 定义、转发导出、迁移脚本引用全部删除）。"""
    assert lint.check_retired_identity_helpers() == []


def test_p6_3_scan_flags_every_site_no_allowed_exception(tmp_path, monkeypatch):
    """端到端扫描面：业务侧、kernel 定义处、迁移脚本三处探针**全部**被报（无豁免位）。"""
    app_probe = tmp_path / "applications" / "agent_server" / "probe.py"
    app_probe.parent.mkdir(parents=True)
    app_probe.write_text(
        "from agent_core.guardrails.auth import legacy_thread_id\n\n\n"
        "def f(api_key):\n    return legacy_thread_id(api_key)\n",
        encoding="utf-8",
    )
    script_probe = tmp_path / "scripts" / "migrate_thread_identity.py"
    script_probe.parent.mkdir(parents=True)
    script_probe.write_text(
        "def pair(api_key):\n    return legacy_thread_id(api_key)\n", encoding="utf-8"
    )
    kernel_probe = tmp_path / "packages" / "agent-core" / "agent_core" / "guardrails" / "auth.py"
    kernel_probe.parent.mkdir(parents=True)
    kernel_probe.write_text(
        "def legacy_thread_id(api_key):\n    return api_key\n", encoding="utf-8"
    )
    monkeypatch.setattr(lint, "ROOT", tmp_path)

    violations = lint.check_retired_identity_helpers()
    assert len(violations) == 3, violations
    hit = "\n".join(violations)
    for site in ("applications/agent_server/probe.py", "scripts/migrate_thread_identity.py", "guardrails/auth.py"):
        assert site in hit, site


# ---------------------------------------------------------------------------
# 迁移：枚举式（旧 id 从数据里枚举，不从密钥复算）+ 目录改名
# ---------------------------------------------------------------------------

_LEGACY_12 = "user-0123456789ab"  # 48bit 截断形态
_LEGACY_32 = "user-" + "0123456789abcdef" * 2  # 128bit 摘要形态


def test_migrate_script_has_no_crypto_references():
    """AST 门禁：枚举式脚本里不得出现 hashlib/hmac，也不得引用任何「凭据→摘要」入口。

    锁的是 B7b-5 的前提：一旦有人想「加回 --api-key 直接算」，本用例会红。
    """
    tree = ast.parse((_ROOT / "scripts" / "migrate_thread_identity.py").read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert "hashlib" not in imported
    assert "hmac" not in imported
    called = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
    for retired in ("legacy_thread_id", "derive_thread_id", "fingerprint", "_hash_api_key"):
        assert retired not in called, f"脚本重新引用了已退役的凭据派生入口：{retired}"


@pytest.mark.parametrize("thread_id", [_LEGACY_12, _LEGACY_32])
def test_is_credential_digest_accepts_both_generations(thread_id):
    assert migrate.is_credential_digest(thread_id) is True
    assert migrate.needs_manual_review(thread_id) is False


@pytest.mark.parametrize(
    "thread_id",
    [
        "user-alice-session-1",  # monitor.build_thread_id() 产出形态（零调用者兼容符号）
        "user-x",  # 开发模式客户端自填
        "user-0123456789AB",  # 大写 hex 不是两代实现会产出的形态
        "user-0123456789abc",  # 13 位 ⇒ 长度不属两代
        "tenant-acme",  # 主体化后的新格式（天然不在待迁移集合）
        "dev-default-thread",
        "deadbeefdeadbeef",  # 无前缀
    ],
)
def test_is_credential_digest_rejects_other_shapes(thread_id):
    assert migrate.is_credential_digest(thread_id) is False


@pytest.mark.parametrize("thread_id", ["user-alice-session-1", "user-x"])
def test_needs_manual_review_flags_unmatched_user_prefix(thread_id):
    """``user-`` 前缀但不命中正则 ⇒ 不动并列入人工核实（误捞负例）。"""
    assert migrate.needs_manual_review(thread_id) is True


def test_needs_manual_review_spares_new_and_legacy_shapes():
    assert migrate.needs_manual_review(_LEGACY_12) is False
    assert migrate.needs_manual_review("tenant-acme") is False


def test_session_dir_name_matches_federation_upload_layout():
    # federation /api/upload：target_dir = updated_dir / f"session_{safe_thread_id}"
    assert migrate.session_dir_name("user-deadbeef") == "session_user-deadbeef"


def test_plan_session_renames_maps_legacy_digest_to_principal_target(tmp_path):
    src = tmp_path / migrate.session_dir_name(_LEGACY_32)
    src.mkdir()
    (src / "a.txt").write_text("x", encoding="utf-8")

    pairs, skipped, review, target = migrate.plan_session_renames(tmp_path, "acme")
    assert target == resolve_thread_identity("acme") == "tenant-acme"
    assert skipped == [] and review == []
    assert pairs == [(src, tmp_path / migrate.session_dir_name(target))]


def test_plan_session_renames_noop_when_already_target(tmp_path):
    (tmp_path / migrate.session_dir_name("tenant-acme")).mkdir()  # 已是新格式
    pairs, skipped, review, _ = migrate.plan_session_renames(tmp_path, "acme")
    assert pairs == [] and review == []
    assert len(skipped) == 1 and "幂等" in skipped[0]


def test_plan_session_renames_refuses_to_overwrite(tmp_path):
    """碰撞不覆盖：目标已存在时列为 skipped，交人工核实（防静默丢历史）。"""
    (tmp_path / migrate.session_dir_name(_LEGACY_12)).mkdir()
    (tmp_path / migrate.session_dir_name("tenant-acme")).mkdir()

    pairs, skipped, _review, _ = migrate.plan_session_renames(tmp_path, "acme")
    assert pairs == []
    # 两条 skipped 各自的职责不同，均需存在：目标目录幂等跳过 + 旧目录拒绝覆盖
    assert len([s for s in skipped if "拒绝覆盖" in s]) == 1, skipped
    assert len([s for s in skipped if "幂等" in s]) == 1, skipped


def test_plan_session_renames_does_not_rename_unmatched_dirs(tmp_path):
    """两个误捞负例均不改名（否则会把 monitor 兼容符号/开发会话挂到错误主体上）。"""
    for name in ("user-alice-session-1", "user-x", "tenant-acme", "dev-default-thread"):
        (tmp_path / migrate.session_dir_name(name)).mkdir()

    pairs, _skipped, review, _ = migrate.plan_session_renames(tmp_path, "acme")
    assert pairs == []
    assert sorted(review) == ["user-alice-session-1", "user-x"]


def test_plan_session_renames_refuses_to_merge_two_digests(tmp_path):
    """同一目标不得静默合并两个会话：第二个计入 skipped + 人工核实。"""
    (tmp_path / migrate.session_dir_name(_LEGACY_12)).mkdir()
    (tmp_path / migrate.session_dir_name(_LEGACY_32)).mkdir()

    pairs, skipped, review, _ = migrate.plan_session_renames(tmp_path, "acme")
    assert len(pairs) == 1
    assert any("不并挂" in s for s in skipped)
    assert review == [_LEGACY_32]


def test_apply_session_renames_moves_content(tmp_path):
    src = tmp_path / migrate.session_dir_name(_LEGACY_12)
    src.mkdir()
    (src / "a.txt").write_text("payload", encoding="utf-8")
    dst = tmp_path / migrate.session_dir_name("tenant-acme")

    pairs, _skipped, _review, _ = migrate.plan_session_renames(tmp_path, "acme")
    assert migrate.apply_session_renames(pairs) == 1
    assert not src.exists()
    assert (dst / "a.txt").read_text(encoding="utf-8") == "payload"


def test_main_dry_run_does_not_rename(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("SINGLE_TENANT", raising=False)
    src = tmp_path / migrate.session_dir_name(_LEGACY_12)
    src.mkdir()

    rc = migrate.main(["--principal", "acme", "--sessions-dir", str(tmp_path)])
    assert rc == 0
    assert src.exists()  # 未加 --apply 不得动盘
    out = capsys.readouterr().out
    assert _LEGACY_12 in out and "tenant-acme" in out and "dry-run" in out


def test_main_apply_renames(tmp_path, monkeypatch):
    monkeypatch.delenv("SINGLE_TENANT", raising=False)
    src = tmp_path / migrate.session_dir_name(_LEGACY_12)
    src.mkdir()

    rc = migrate.main(["--principal", "acme", "--sessions-dir", str(tmp_path), "--apply"])
    assert rc == 0
    assert not src.exists()
    assert (tmp_path / migrate.session_dir_name("tenant-acme")).is_dir()


def test_main_requires_principal(monkeypatch, capsys):
    monkeypatch.delenv("SINGLE_TENANT", raising=False)
    assert migrate.main([]) == 2
    assert "--principal" in capsys.readouterr().err


def test_main_rejects_illegal_principal(monkeypatch, capsys):
    """主体字符集非法 ⇒ rc 2（而非静默清洗出一个碰撞目录名）。"""
    monkeypatch.delenv("SINGLE_TENANT", raising=False)
    assert migrate.main(["--principal", "a:b"]) == 2
    assert "非法" in capsys.readouterr().err


def test_verification_sql_is_read_only_and_covers_all_thread_keyed_tables():
    stmts = migrate.build_verification_sql("tenant-acme")
    joined = "\n".join(stmts)
    for table in ("checkpoints", "checkpoint_writes", "checkpoint_blobs"):
        assert f"FROM {table}" in joined
    # 只读语句：SELECT 不写；两侧 <> 目标名保幂等
    assert joined.upper().count("SELECT") == 3 and "UPDATE" not in joined
    assert "LIKE 'user-%'" in joined and "<> 'tenant-acme'" in joined


def test_checkpoint_sql_covers_all_thread_keyed_tables():
    stmts = migrate.build_checkpoint_sql("tenant-acme", [_LEGACY_12])
    joined = "\n".join(stmts)
    for table in ("checkpoints", "checkpoint_writes", "checkpoint_blobs"):
        assert f"UPDATE {table}" in joined
    # 只出语句、以绑定变量占位，不把未实跑验证的写操作固化进脚本
    assert "%s" in joined and _LEGACY_12 not in stmts[0].split("--")[0]


def test_checkpoint_sql_skips_non_digest_sources():
    """不命中正则的 id 不自动生成 UPDATE（属人工核实项，脚本不猜）。"""
    assert migrate.build_checkpoint_sql("tenant-acme", ["user-alice-session-1", "user-x"]) == []
