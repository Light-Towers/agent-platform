"""P14 语义缓存单轨门禁的治理测试（ADR-0013 C）。

对应方案第③层「强制门禁」：实现复制、配置散读、PG 旧表回流、生产清单回退
都必须在 CI 变红，而不是靠评审记得。正反例直接调 lint 的单文件判定，
另有一条对**当前仓库**跑全量扫描，保证门禁本身不是空转。
"""

import importlib.util
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]


def _load_script(module_name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(module_name, _ROOT / relative_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


lint = _load_script("lint_architecture_p14", "scripts/lint_architecture.py")


@pytest.mark.parametrize(
    "rel,text,needle",
    [
        (
            "applications/agent_federation/agent/cache/layers.py",
            "from valkey.asyncio import Valkey\n",
            "valkey 客户端只能在",
        ),
        (
            "applications/agent_federation/agent/main_agent.py",
            'if os.getenv("CACHE_ENABLED", "false").lower() == "true":\n    pass\n',
            "裸读 CACHE_* 环境变量",
        ),
        (
            "applications/agent_server/api/query_router.py",
            "SELECT answer FROM semantic_cache WHERE tenant_id = %s\n",
            "PG semantic_cache 表 SQL",
        ),
        (
            "applications/agent_server/api/query_router.py",
            "INSERT INTO semantic_cache (cache_key, answer) VALUES (%s, %s)\n",
            "PG semantic_cache 表 SQL",
        ),
        # ⑥ 应用层自建后端：绕过工厂就拿不到 _BACKENDS 单例 / close_cache / /health 读数
        (
            "applications/agent_server/main.py",
            'cache = ValkeySemanticCache(config, "agent_server")\n',
            "应用层直接构造缓存后端",
        ),
        (
            "applications/agent_federation/agent/cache/semantic_cache.py",
            "cache = DisabledSemanticCache(scope)\n",
            "应用层直接构造缓存后端",
        ),
    ],
)
def test_p14_flags_second_track_in_python(rel, text, needle):
    violations = lint._cache_py_violation(rel, text)
    assert any(needle in v for v in violations)


@pytest.mark.parametrize(
    "rel,text",
    [
        # 适配器内导入客户端是唯一合法位置
        (
            "packages/agent-runtime/agent_runtime/cache/valkey_backend.py",
            "from valkey.asyncio import Valkey\n",
        ),
        # config.py 是唯一允许读 CACHE_* 的地方
        (
            "packages/agent-runtime/agent_runtime/cache/config.py",
            'os.getenv("CACHE_BACKEND", "valkey")\n',
        ),
        # 迁移文件保留至 Stage 5 删表，不算回流
        (
            "packages/agent-runtime/agent_runtime/migrations/001_baseline.up.sql",
            "CREATE TABLE IF NOT EXISTS semantic_cache (id int);\n",
        ),
        # ⑥ 工厂是唯一合法构造位
        (
            "packages/agent-runtime/agent_runtime/cache/factory.py",
            "backend = ValkeySemanticCache(config, scope)\n",
        ),
    ],
)
def test_p14_allows_single_track_locations(rel, text):
    assert lint._cache_py_violation(rel, text) == []


def test_p14_app_may_import_backend_class_without_constructing_it():
    """⑥ 只认调用形：app 里 `import ValkeySemanticCache`（类型标注/测试替身需要）不得报红。

    这条是判据的**精度**守卫。若改成"出现类名即红"，`test_health.py` 那种 monkeypatch
    替身与任何 `backend: ValkeySemanticCache | None` 标注都会被误伤 ⇒ 门禁因噪音被放宽，
    而"因噪音被放宽"比"没有门禁"更糟。
    """
    assert lint._cache_py_violation(
        "applications/agent_server/api/health_router.py",
        "from agent_runtime.cache.valkey_backend import ValkeySemanticCache\n"
        "backend: ValkeySemanticCache | None = None\n",
    ) == []


def test_p14_no_application_constructs_a_backend_today():
    """正向控制：⑥ 不是"新写来等着红"的规则——现网两 app 确实都只经 `get_cache`。

    同时钉住这条事实的**取证口径**：扫的是 `applications/**` 的全部 .py（含各自 tests/），
    所以这里若红了，说明真有 app 侧构造位，而不是判据写坏了。
    """
    offenders = []
    for rel, py_file in lint._iter_scanned_py_files():
        if not rel.startswith(lint._CACHE_APP_PREFIX):
            continue
        text = py_file.read_text(encoding="utf-8-sig")
        if lint._CACHE_BACKEND_CONSTRUCTION.search(text):
            offenders.append(rel)
    assert offenders == [], offenders


def test_p14_manifest_rejects_pg_backend():
    violations = lint._cache_manifest_violation(
        "deploy/k8s/20-agent-platform.yaml", 'name: CACHE_BACKEND\nvalue: "pg"\n'
    )
    assert any("CACHE_BACKEND=pg 已退役" in v for v in violations)


def test_p14_manifest_comment_is_not_effective_config():
    text = (
        "# 禁止 CACHE_BACKEND=pg，只允许 valkey\n"
        "- name: CACHE_BACKEND\n"
        '  value: "valkey"\n'
        "- name: VALKEY_URL\n"
        "  valueFrom:\n"
        "    secretKeyRef:\n"
        "      name: agent-platform-secrets\n"
        "      key: VALKEY_URL\n"
    )
    assert lint._cache_manifest_violation("deploy/k8s/20-agent-platform.yaml", text) == []


def test_p14_manifest_requires_explicit_valkey_and_secret():
    text = "- name: CACHE_BACKEND\n  value: \"disabled\"\n"
    violations = lint._cache_manifest_violation("deploy/k8s/20-agent-platform.yaml", text)
    assert any("必须显式 CACHE_BACKEND" in v for v in violations)
    assert any("VALKEY_URL 必须从 Secret 注入" in v for v in violations)


def test_p14_compose_requires_valkey():
    violations = lint._cache_manifest_violation("docker-compose.yml", "CACHE_BACKEND: disabled\n")
    assert any("compose 也必须 CACHE_BACKEND: valkey" in v for v in violations)
    assert lint._cache_manifest_violation("docker-compose.yml", "CACHE_BACKEND: valkey\n") == []


def test_p14_current_repo_is_clean():
    """非空转反证：当前仓库必须通过全量扫描（不是只测判定函数）。"""
    assert lint.check_cache_single_track() == []


# --- P14 ⑤：valkey-bundle 镜像坐标（三处可执行引用必须一致且等于实取过的 pin） -------

def _make_pin_tree(root, tags: dict[str, str | None]):
    """按 {相对路径: 裸 tag 或 None（不写引用）} 铺出三处引用位。"""
    for rel, tag in tags.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        body = f"image: valkey/valkey-bundle:{tag}" if tag is not None else "image: some/other:1"
        path.write_text(body + "\n", encoding="utf-8")


def _run_pin_check(tmp_path, monkeypatch, tags):
    monkeypatch.setattr(lint, "ROOT", tmp_path)
    _make_pin_tree(tmp_path, tags)
    return lint._cache_bundle_pin_violations()


def _verified_tag() -> str:
    return lint._VALKEY_BUNDLE_PIN.rsplit(":", 1)[1]


# 反例用的离群坐标。**不能用 9.1.2 当反例**——那是真机在用、P14 现在强制的值
# （我一度以为它不存在，据此改了六处坐标，那条判断已被 <internal-node-01> 上的实体镜像推翻：
# lf-valkey 用它健康跑了 12 天，search 模块 ver=66049=1.2.1）。
# 所以反例要挑一个两边都不存在的坐标，判据测的是"偏离 pin"，不是"偏离我的猜测"。
_BOGUS_TAG = "9.9.9"


def test_bundle_pin_flags_the_tag_that_deviates_from_the_verified_pin(tmp_path, monkeypatch):
    """镜像坐标必须能被抓出"偏离已实取的 pin"，而不是只做彼此一致性比较。

    真实历史缺陷是"多处抄同一个**没有来源**的坐标"：它一开始抄的是 refactor-plan.md 的规划值
    （9.1.2，事后被真机证明是对的），我随后又按 git release 列表把它整体改成 9.0.1（这个是错的）。
    两次都"多处一致"，所以一致性比较对这种情形永远绿；判据必须跟一个写死的、可复核的来源比。
    现依据＝真机 `docker inspect` + `MODULE LIST` + 另一台的 repo digest，不再是 git 标签列表。
    """
    sites = dict.fromkeys(lint._VALKEY_PIN_SITES, _verified_tag())
    first = lint._VALKEY_PIN_SITES[0]
    sites[first] = _BOGUS_TAG
    violations = _run_pin_check(tmp_path, monkeypatch, sites)
    assert len(violations) == 1, violations
    assert first in violations[0]
    assert _BOGUS_TAG in violations[0]


def test_bundle_pin_accepts_uniform_verified_tag(tmp_path, monkeypatch):
    assert _run_pin_check(tmp_path, monkeypatch, dict.fromkeys(lint._VALKEY_PIN_SITES, _verified_tag())) == []


def test_bundle_pin_requires_a_reference_at_every_site(tmp_path, monkeypatch):
    """有人把 CI service 那行删掉 ⇒ 契约用例会在"本机无 Valkey 所以 skip"里静默变绿。"""
    sites = dict.fromkeys(lint._VALKEY_PIN_SITES, _verified_tag())
    last = lint._VALKEY_PIN_SITES[-1]
    sites[last] = None
    violations = _run_pin_check(tmp_path, monkeypatch, sites)
    assert any(last in v for v in violations), violations


def test_bundle_pin_current_repo_matches_verified_release():
    """对当前仓库跑真判定：三处必须都等于已实取的 bundle release tag。"""
    assert lint._cache_bundle_pin_violations() == []
    for rel in lint._VALKEY_PIN_SITES:
        text = (_ROOT / rel).read_text(encoding="utf-8-sig")
        assert lint._VALKEY_BUNDLE_PIN in text, rel
        # 现场只允许一个坐标：出现任何非 pin 的 bundle tag 都是漂移
        for ref in lint._VALKEY_IMAGE_REF.findall(text):
            assert ref == lint._VALKEY_BUNDLE_PIN, (rel, ref)


# ---- 派生扫描：门禁的"被检对象清单"本身也要有人查 ----------------------------
# 改 pin 时手写表只列了三处，"三处"这个数就是从手写表里读出来的；实际入库文件里
# 有五处在用这个镜像。这类"门禁用错了枚举"的坑不靠人记得加行，靠一条自检用例。
_REAL_EXTRA_SITES = (
    "docker-compose.yml",
    "deploy/observability/docker-compose.langfuse.yml",
    "scripts/bench_cache.py",
)


def test_derived_sites_cover_the_files_the_hand_table_missed():
    """派生必须捞出**不在手写表里**的那些引用位。

    用例里同时钉"这两处确实不在 `_VALKEY_PIN_SITES`"——否则某天有人图省事把它们补进
    手写表，这条用例就退化成"手写表 ⊆ 派生"的空转，看起来在守卫枚举、实际谁都没守。
    """
    derived = set(lint._valkey_pin_candidate_sites())
    for rel in _REAL_EXTRA_SITES:
        assert rel not in lint._VALKEY_PIN_SITES, f"{rel} 已进手写表，本用例失去意义"
        assert rel in derived, f"派生漏掉 {rel}：它会带着没发布过的 tag 静默入库"
    for rel in lint._VALKEY_PIN_SITES:
        assert rel in derived, f"手写表里的 {rel} 在派生里找不到（引用被删？表该同步）"


def test_derived_site_outside_the_hand_table_is_still_checked(tmp_path, monkeypatch):
    """派生出来的位不是"列出来看看"，是真的进判定：新加一处 compose 写错 tag 必须单独翻红。"""
    extra = "deploy/observability/docker-compose.langfuse.yml"
    monkeypatch.setattr(lint, "ROOT", tmp_path)
    _make_pin_tree(tmp_path, dict.fromkeys(lint._VALKEY_PIN_SITES, _verified_tag()))
    _make_pin_tree(tmp_path, {extra: _BOGUS_TAG})
    violations = lint._cache_bundle_pin_violations(extra_sites=[extra])
    assert len(violations) == 1, violations
    assert extra in violations[0]
    assert _BOGUS_TAG in violations[0]


def test_derived_site_without_a_reference_is_not_flagged(tmp_path, monkeypatch):
    """派生位只查"引用了就得等于 pin"，不逼每个 yml 都含 valkey——
    否则门禁会把无关的 compose 全报红，变成必须有人来关掉的噪音。"""
    monkeypatch.setattr(lint, "ROOT", tmp_path)
    _make_pin_tree(tmp_path, dict.fromkeys(lint._VALKEY_PIN_SITES, _verified_tag()))
    path = tmp_path / "docker-compose.yml"
    path.write_text("services:\n  app:\n    image: python:3.11-slim\n", encoding="utf-8")
    assert lint._cache_bundle_pin_violations(extra_sites=["docker-compose.yml"]) == []
