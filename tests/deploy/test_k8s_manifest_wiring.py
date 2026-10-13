"""deploy/k8s 清单接线门禁：清单必须能真的描述线上在跑的东西。

来源：2026-10-10「演示版最小可运行版本」D2「清单与线上一致化」。当时线上容器 env 里有
4 个 OTEL_* 与 LLM_API_KEY，清单却从未声明 ⇒ 任何人一次 ``kubectl apply`` 就会把可观测
和模型凭据抹掉；而 ConfigMap 里的 ``LLM_BASE_URL=api.openai.com/v1`` 是死键（线上早被
``kubectl set env`` 改成了字面值），回写前的清单会把国外模型地址注回线上。

本用例守的是同一类错：**写了但没人读的环境变量 / 缩进错位被 k8s 静默丢弃的字段**。
二者都不会让 apply 报错，只会在运行期表现成「开关没生效」。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[2]
_CONFIG = _ROOT / "deploy" / "k8s" / "00-config.yaml"
_SECRETS = _ROOT / "deploy" / "k8s" / "05-secrets.yaml"
_DEPLOY = _ROOT / "deploy" / "k8s" / "20-agent-platform.yaml"

# 由第三方库直接消费、仓库内不出现读取点的标准 env（实测：设这三个可离线加载权重）
_THIRD_PARTY_ENV = {"HF_HOME", "HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "OMP_NUM_THREADS"}

# 真实密钥永不入库。126 上它们住在集群单独建的 observability-keys（对象名早于鉴权用途）
# LANGFUSE_* 两把是 Langfuse 项目 API key（2026-10-13 无头初始化生成，
# 经 stdin 写入该对象；见 deploy/observability/langfuse.env.example 的注入去向表）
_CLUSTER_OWNED_SECRET_OBJECTS = {"observability-keys"}
_CLUSTER_OWNED_SECRET_KEYS = {"LLM_API_KEY", "API_KEY", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"}

# k8s 对未知字段不报错、直接丢（非 strict validate）⇒ 用白名单把它变成用例失败
_CONTAINER_FIELDS = {
    "name", "image", "imagePullPolicy", "ports", "env", "envFrom", "command", "args",
    "resources", "volumeMounts", "livenessProbe", "readinessProbe", "startupProbe",
    "lifecycle", "securityContext", "terminationMessagePath", "terminationMessagePolicy",
}
_POD_FIELDS = {
    "containers", "initContainers", "volumes", "restartPolicy", "terminationGracePeriodSeconds",
    "securityContext", "nodeSelector", "tolerations", "affinity", "serviceAccountName",
}

# os.getenv("X") / os.environ.get("X") / os.environ["X"] / env_bool("X", ...)
_ENV_READ_RE = re.compile(
    r"""(?:os\.getenv\(|os\.environ\.get\(|os\.environ\[|env_bool\(|env_str\(|env_int\()\s*["']"""
    r"""([A-Z][A-Z0-9_]{2,})["']"""
)


def _load(path: Path) -> list[dict]:
    docs = list(yaml.safe_load_all(path.read_text(encoding="utf-8")))
    return [d for d in docs if d]


@pytest.fixture(scope="module")
def configmap() -> dict:
    return next(d for d in _load(_CONFIG) if d["kind"] == "ConfigMap")


@pytest.fixture(scope="module")
def secret() -> dict:
    return next(d for d in _load(_SECRETS) if d["kind"] == "Secret")


def test_config_file_carries_no_secret_object():
    """构造保证而非约定：人常 apply 的那份配置文件里不能有 Secret 对象。
    "记得别把 Secret 一起 apply"迟早会被人破，写成文件切分才不会被忘掉。"""
    kinds = [d["kind"] for d in _load(_CONFIG)]
    assert "Secret" not in kinds, f"00-config.yaml 出现了 Secret 对象（{kinds}）"
    assert "Secret" in [d["kind"] for d in _load(_SECRETS)]


@pytest.fixture(scope="module")
def pod_spec() -> dict:
    dep = next(d for d in _load(_DEPLOY) if d["kind"] == "Deployment")
    return dep["spec"]["template"]["spec"]


@pytest.fixture(scope="module")
def container(pod_spec: dict) -> dict:
    return pod_spec["containers"][0]


def _consumable_env_names() -> set[str]:
    """代码里真会被读到的 env 名：app Settings 字段（pydantic-settings 无 env_prefix ⇒ 大写同名字段）
    + 内核/runtime 里的字面 os.getenv/os.environ 读取点。"""
    from agent_server.config import Settings

    names = {f.upper() for f in Settings.model_fields}
    for pkg in (
        _ROOT / "applications" / "agent_server",
        _ROOT / "packages" / "agent-core",
        _ROOT / "packages" / "agent-runtime",
    ):
        for py in pkg.rglob("*.py"):
            if py.parent.name == "__pycache__":
                continue
            names.update(_ENV_READ_RE.findall(py.read_text(encoding="utf-8")))
    return names


def _manifest_env(container: dict) -> dict[str, str]:
    """env 名 → 来源（literal / configMapKeyRef / secretKeyRef）。"""
    out: dict[str, str] = {}
    for item in container["env"]:
        if "value" in item:
            out[item["name"]] = "literal"
        elif "valueFrom" in item:
            ref = item["valueFrom"]
            out[item["name"]] = (
                "configMapKeyRef" if "configMapKeyRef" in ref else "secretKeyRef"
            )
        else:  # pragma: no cover - 清单里不该出现第三种写法
            raise AssertionError(f"env {item['name']} 既无 value 也无 valueFrom")
    return out


def _mem(value: str) -> int:
    """K8s 数量 → 字节。只覆盖清单实际用到的 Mi/Gi/M/G。"""
    m = re.fullmatch(r"(\d+)(Mi|Gi|M|G)?", str(value))
    assert m, f"无法解析内存量 {value!r}"
    n, unit = int(m.group(1)), m.group(2) or ""
    return n * {"": 1, "M": 10**6, "G": 10**9, "Mi": 2**20, "Gi": 2**30}[unit]


# ---------------------------------------------------------------------------
# ① 写了但没人读：env 名必须是代码真的消费的
# ---------------------------------------------------------------------------


def test_every_env_name_is_consumed_by_code(container):
    consumable = _consumable_env_names()
    unknown = sorted(set(_manifest_env(container)) - consumable - _THIRD_PARTY_ENV)
    assert not unknown, (
        f"清单注入了代码中找不到读取点的 env：{unknown}。"
        "env 名写错不会让 Pod 报错，只会让开关静默失效（本仓库已两次踩此模式）。"
    )


def test_guard_and_identity_switches_really_exist_in_code(container):
    """三个关键开关逐个点名，避免①的集合比较因某个恰好同名字段而蒙混过关。"""
    consumable = _consumable_env_names()
    for name in ("GUARD_ENABLED", "GUARD_BLOCK_INJECTION", "EMBEDDING_REQUIRE_REAL",
                 "SINGLE_TENANT", "DEPLOY_ENFORCE_IDENTITY", "API_KEY"):
        assert name in consumable, f"{name} 在代码里没有读取点"
        assert name in _manifest_env(container), f"{name} 未在清单中声明"


def test_local_mode_model_id_is_the_one_kernel_falls_back_to(container):
    """EMBEDDING_MODE=local 走内核落底分支，模型 id 取 INTENT_EMBEDDING_MODEL，
    不是 ConfigMap 里的 EMBEDDING_MODEL（后者只作用于 RemoteEmbedder）。"""
    env = {e["name"]: e.get("value") for e in container["env"]}
    if env.get("EMBEDDING_MODE") != "local":
        pytest.skip("非本地语义模型部署，维度前提不适用")
    assert env.get("INTENT_EMBEDDING_MODEL"), "local 模式必须显式钉住模型 id"
    from agent_server.config import get_settings

    assert get_settings().vector_dim == 512, "维度前提变了要同步改 pgvector 列宽"


# ---------------------------------------------------------------------------
# ② 死键：ConfigMap 里每个键都得被 deployment 读走
# ---------------------------------------------------------------------------


def test_configmap_has_no_dead_keys(configmap, container):
    consumed = {
        e["name"]
        for e in container["env"]
        if "valueFrom" in e and "configMapKeyRef" in e["valueFrom"]
    }
    dead = sorted(set(configmap["data"]) - consumed)
    assert not dead, f"ConfigMap 存在未被 deployment 引用的键：{dead}（死键会让清单与线上口径分叉）"


def test_configmap_llm_values_are_not_the_retired_foreign_defaults(configmap):
    """死键回归防护：api.openai.com/v1 + gpt-4o-mini 曾在清单里躺了很久，
    而线上早就是内网可达地址。谁把它们改回去，一次 apply 就会让模型当场不可用。"""
    assert "api.openai.com" not in configmap["data"]["LLM_BASE_URL"]
    assert "gpt-4o-mini" not in {configmap["data"]["LLM_MODEL"],
                                 configmap["data"]["LLM_FALLBACK_MODEL"]}


# ---------------------------------------------------------------------------
# ③ 密钥：清单只引用键名，真实值不入库
# ---------------------------------------------------------------------------


def test_no_real_secret_values_in_repo_manifest(secret):
    committed = set((secret.get("stringData") or {})) | set((secret.get("data") or {}))
    leaked = sorted(committed & _CLUSTER_OWNED_SECRET_KEYS)
    assert not leaked, f"敏感键 {leaked} 不应出现在入库清单里"


def test_secret_refs_point_at_an_existing_object(secret, container):
    """引用不能指向一个不存在的键：Pod 会以 CreateContainerConfigError 起不来，
    而那种失败常被误读成「镜像坏了」。"""
    in_repo = set((secret.get("stringData") or {})) | set((secret.get("data") or {}))
    repo_object = secret["metadata"]["name"]
    for e in container["env"]:
        ref = (e.get("valueFrom") or {}).get("secretKeyRef")
        if not ref:
            continue
        name, key = ref["name"], ref["key"]
        if name == repo_object:
            assert key in in_repo, f"{name}/{key} 在入库 Secret 里没有这个键"
        else:
            assert name in _CLUSTER_OWNED_SECRET_OBJECTS, (
                f"清单引用了未交代来源的 Secret 对象 {name}"
            )
            assert key in _CLUSTER_OWNED_SECRET_KEYS, f"{name}/{key} 不在集群自有键清单内"
            assert key not in in_repo, f"{key} 同时出现在入库对象与集群自有对象里，来源分叉"
        assert ref.get("optional") is not True, f"{key} 被标 optional 即允许静默缺凭据"


# ---------------------------------------------------------------------------
# ④ 缩进错位 = 字段被 k8s 静默丢弃
# ---------------------------------------------------------------------------


def test_no_unknown_fields_in_pod_and_container(pod_spec, container):
    stray_pod = sorted(set(pod_spec) - _POD_FIELDS)
    stray_ctr = sorted(set(container) - _CONTAINER_FIELDS)
    assert not stray_pod, f"PodSpec 出现未知字段 {stray_pod}（非 strict apply 会直接丢掉）"
    assert not stray_ctr, f"容器出现未知字段 {stray_ctr}（缩进错一层就等于没配）"


# ---------------------------------------------------------------------------
# ⑤ 探针与配额：重活不许落在探测路径上，本地模型常驻要有内存
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("probe", ("startupProbe", "readinessProbe", "livenessProbe"))
def test_probes_declare_explicit_timeout_and_hit_health(container, probe):
    """timeoutSeconds 的 API 默认值是 1s：空闲时 /health 实测中位 0.8ms 够用，
    但 CPU 推理持 GIL 时探测会被拖到秒级 ⇒ 默认值会误杀健康 Pod（三次即重启）。"""
    cfg = container[probe]
    assert cfg["httpGet"]["path"] == "/health"
    assert cfg.get("timeoutSeconds", 1) > 1, f"{probe} 未显式放宽 timeoutSeconds（默认 1s）"


def test_memory_limit_covers_local_model_residency(container):
    lim = _mem(container["resources"]["limits"]["memory"])
    req = _mem(container["resources"]["requests"]["memory"])
    assert lim >= 2 * 2**30, "本地语义模型常驻峰值实测 444MiB，1Gi 上限没有批量 encode 余量"
    assert req <= lim, "requests > limits 会让 Pod 无法通过校验"


# ---------------------------------------------------------------------------
# ⑥ 声明了 local 模式就必须把权重缓存挂进 Pod
# ---------------------------------------------------------------------------


def test_local_embedding_requires_mounted_weight_cache(pod_spec, container, configmap):
    env = {e["name"]: e.get("value") for e in container["env"]}
    if env.get("EMBEDDING_MODE") != "local":
        pytest.skip("未启用本地语义模型")
    assert env.get("HF_HUB_OFFLINE") == "1", "local 模式不离线 ⇒ 首推理时回连 huggingface.co"
    mounts = {m["mountPath"]: m for m in container.get("volumeMounts", [])}
    hf_home = env["HF_HOME"]
    mounted = [p for p in mounts if hf_home == p or hf_home.startswith(p.rstrip("/") + "/")]
    assert mounted, f"HF_HOME={hf_home} 不在任何 volumeMount 下，缓存只在宿主持有、Pod 里是空的"
    host_paths = {v["name"]: v.get("hostPath", {}) for v in pod_spec.get("volumes", [])}
    used = [host_paths[mounts[p]["name"]] for p in mounted]
    assert any(h.get("type") == "Directory" for h in used), (
        "hostPath 未写 type: Directory ⇒ 缓存不在 Pod 落到的那个节点时不报错，"
        "而是静默起来、首次推理才炸（126 三节点各自独立盘）"
    )
    # 刻意不断言 readOnly：只读挂载能否离线加载权重取决于 huggingface_hub 是否往缓存写 .lock，
    # 该项尚未实测（见清单内待办命令），把它写成断言等于把未验证的假设钉成门禁。
    assert configmap["data"]["EMBEDDING_MODEL"], "EMBEDDING_MODEL 仍是远程分支的唯一模型来源"


# ---------------------------------------------------------------------------
# ⑦ 非空洞性：把当年四类真实缺陷形状注回去，逐条确认门禁会咬
# ---------------------------------------------------------------------------


def test_gate_bites_on_the_four_defect_shapes(secret, pod_spec, container, configmap):
    import copy

    # (a) env 名拼错 → 开关静默失效
    bad_ctr = copy.deepcopy(container)
    bad_ctr["env"].append({"name": "GUARD_BLOCK_INJECTON", "value": "true"})
    with pytest.raises(AssertionError, match="找不到读取点"):
        test_every_env_name_is_consumed_by_code(bad_ctr)

    # (b) ConfigMap 死键（改回 api.openai.com 那次的形状）
    bad_cm = copy.deepcopy(configmap)
    bad_cm["data"]["LLM_BASE_URL"] = "https://api.openai.com/v1"
    with pytest.raises(AssertionError, match="api.openai.com"):
        test_configmap_llm_values_are_not_the_retired_foreign_defaults(bad_cm)
    bad_cm["data"]["SOME_UNUSED_KEY"] = "x"
    with pytest.raises(AssertionError, match="未被 deployment 引用的键"):
        test_configmap_has_no_dead_keys(bad_cm, container)

    # (c) 字段缩进错一层（terminationGracePeriodSeconds 落进容器）→ k8s 静默丢弃
    bad_pod = copy.deepcopy(pod_spec)
    bad_pod["containers"][0]["terminationGracePeriodSeconds"] = 60
    with pytest.raises(AssertionError, match="容器出现未知字段"):
        test_no_unknown_fields_in_pod_and_container(bad_pod, bad_pod["containers"][0])

    # (d) 声明 local 却没挂权重缓存 → 起来才发现不了 huggingface.co
    bad_local_pod = copy.deepcopy(pod_spec)
    bad_ctr2 = bad_local_pod["containers"][0]
    bad_ctr2["volumeMounts"] = []
    bad_local_pod["volumes"] = []
    with pytest.raises(AssertionError, match="volumeMount"):
        test_local_embedding_requires_mounted_weight_cache(
            bad_local_pod, bad_ctr2, configmap
        )

    # (e) 密钥被标 optional / 真实值入库 / 引用了没交代的 Secret 对象
    bad_ctr3 = copy.deepcopy(container)
    for e in bad_ctr3["env"]:
        ref = (e.get("valueFrom") or {}).get("secretKeyRef")
        if ref and ref.get("key") == "LLM_API_KEY":
            ref["optional"] = True
    with pytest.raises(AssertionError, match="optional"):
        test_secret_refs_point_at_an_existing_object(secret, bad_ctr3)

    bad_ctr4 = copy.deepcopy(container)
    for e in bad_ctr4["env"]:
        ref = (e.get("valueFrom") or {}).get("secretKeyRef")
        if ref and ref.get("key") == "DATABASE_URL":
            ref["key"] = "DB_URL"          # 键名与入库对象不一致
    with pytest.raises(AssertionError, match="没有这个键"):
        test_secret_refs_point_at_an_existing_object(secret, bad_ctr4)

    bad_secret = copy.deepcopy(secret)
    bad_secret["stringData"]["LLM_API_KEY"] = "sk-not-a-real-key"
    with pytest.raises(AssertionError, match="不应出现在入库清单"):
        test_no_real_secret_values_in_repo_manifest(bad_secret)

