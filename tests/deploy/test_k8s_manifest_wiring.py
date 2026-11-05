"""deploy/k8s 清单接线门禁：清单必须能真的描述线上在跑的东西。

来源：2026-10-10「演示版最小可运行版本」D2「清单与线上一致化」。当时线上容器 env 里有
4 个 OTEL_* 与 LLM_API_KEY，清单却从未声明 ⇒ 任何人一次 ``kubectl apply`` 就会把可观测
和模型凭据抹掉；而 ConfigMap 里的 ``LLM_BASE_URL=api.openai.com/v1`` 是死键（线上早被
``kubectl set env`` 改成了字面值），回写前的清单会把国外模型地址注回线上。

本用例守的是同一类错：**写了但没人读的环境变量 / 缩进错位被 k8s 静默丢弃的字段**。
二者都不会让 apply 报错，只会在运行期表现成「开关没生效」。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[2]
_K8S = _ROOT / "deploy" / "k8s"
_CONFIG = _K8S / "00-config.yaml"
_SECRETS = _K8S / "05-secrets.yaml"
_DEPLOY = _K8S / "20-agent-platform.yaml"
_NL2SQL = _K8S / "30-nl2sql-service.yaml"  # 平台要调它，地址与它的 Service 对象必须能算出同一个值
#: 会被 apply 的全部工作负载清单。ConfigMap 的“有没有死键”要按**消费方全集**算：
#: 00-config 现在同时服务平台（20）、问数服务（30）与两个一次性 Job（35/36），
#: 只拿 20 的容器做分母，就会把 30/36 的真引用误判成死键（并反过来鼓励大家拆成两份 CM）。
_WORKLOADS = (_DEPLOY, _NL2SQL, _K8S / "35-nl2sql-dbsql-job.yaml", _K8S / "36-nl2sql-meta-init-job.yaml")

# 由第三方库直接消费、仓库内不出现读取点的标准 env（实测：设这三个可离线加载权重）
_THIRD_PARTY_ENV = {"HF_HOME", "HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "OMP_NUM_THREADS"}

# 真实密钥永不入库。126 上它们住在集群单独建的 observability-keys（对象名早于鉴权用途）
# LANGFUSE_* 两把是 Langfuse 项目 API key（2026-10-13 无头初始化生成，
# 经 stdin 写入该对象；见 deploy/observability/langfuse.env.example 的注入去向表）
# agent-platform-jwt（PR-2c）：登录面签名密钥另开一个对象 —— 与观测凭据不同轮换轨，
# 补键走 kubectl patch 合并写（apply 是整对象替换）；分对象后“patch 错对象”的影响面
# 从「观测面与登录面一起挂」缩到只挂一边。生成与写入命令见 deploy/k8s/README.md §6.3。
_CLUSTER_OWNED_SECRET_OBJECTS = {"observability-keys", "agent-platform-jwt"}
# INTERNAL_HMAC_KEY（2026-10-28 补）：20 是签发侧、自己也要从卷里读这把键。这里少列一个键 =
# 入库 demo Secret 可以添一把"能签合法租户"的对称密钥而不被拦，而在 30 那侧的同名门禁会红。
_CLUSTER_OWNED_SECRET_KEYS = {
    "LLM_API_KEY",
    "API_KEY",
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
    "INTERNAL_HMAC_KEY",
    # 登录面两把（私钥 + {kid: PEM} 公钥集）。列进这份清单的含意是：它们只可能来
    # 自集群自有对象 ⇒ 一旦有人把它们写进 05-secrets.yaml 的 demo 值，
    # test_no_real_secret_values_in_repo_manifest 当场红（这一格靠的就是本行的存在）。
    "TENANT_JWT_PRIVATE_KEY",
    "TENANT_JWT_PUBLIC_KEYS",
}

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


def _manifest_effective_env(container: dict, configmap: dict) -> dict[str, str]:
    """env 名 → **从清单能读到的生效值**：literal 直取、configMapKeyRef 从 CM 取值；
    secretKeyRef 跳过（真实值永不入库，能拿到的只有键名）。登录面的四把参数全靠它合成。"""
    data = configmap.get("data") or {}
    out: dict[str, str] = {}
    for e in container["env"]:
        if "value" in e:
            out[e["name"]] = str(e["value"])
        else:
            ref = (e.get("valueFrom") or {}).get("configMapKeyRef")
            if ref:
                assert ref["name"] == configmap["metadata"]["name"], (
                    f"{e['name']} 引用了另一份 CM（{ref['name']}），本函数不跟它跨对象"
                )
                out[e["name"]] = str(data[ref["key"]])
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


def _cm_key_refs(node: object) -> set[tuple[str, str]]:
    """递归收集 (configMap 名, 键名) 引用。

    不按 `env[].valueFrom.configMapKeyRef` 的固定路径取：envFrom / volume / projected
    都是同一份 CM 的合法消费方，只扫 env 会把它们当成死键。
    """
    if isinstance(node, dict):
        ref = node.get("configMapKeyRef")
        out: set[tuple[str, str]] = set()
        if isinstance(ref, dict) and "name" in ref and "key" in ref:
            out.add((ref["name"], ref["key"]))
        for value in node.values():
            out |= _cm_key_refs(value)
        return out
    if isinstance(node, list):
        acc: set[tuple[str, str]] = set()
        for item in node:
            acc |= _cm_key_refs(item)
        return acc
    return set()


def _cm_refs_across_workloads() -> set[tuple[str, str]]:
    refs: set[tuple[str, str]] = set()
    for path in _WORKLOADS:
        for doc in _load(path):
            refs |= _cm_key_refs(doc)
    return refs


def test_configmap_has_no_dead_keys(configmap):
    consumed = {
        key
        for name, key in _cm_refs_across_workloads()
        if name == configmap["metadata"]["name"]
    }
    dead = sorted(set(configmap["data"]) - consumed)
    assert not dead, (
        f"ConfigMap 存在未被任何工作负载引用的键：{dead}"
        "（死键会让清单与线上口径分叉：改它的人得不到任何反馈）"
    )


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
# ③b 登录面密钥（PR-2c）：卷侧来源、挂载路径同源、按清单值真签真验
# ---------------------------------------------------------------------------


def _secret_file_paths(pod_spec: dict) -> set[str]:
    """清单自己算得出的「容器内密钥文件路径」全集：secret 卷的 items[].path ×
    该卷在容器上的 mountPath。不从 env 里读路径（那正是被测的那一条边）。"""
    mounts = {
        m["name"]: str(m["mountPath"]).rstrip("/")
        for m in pod_spec["containers"][0].get("volumeMounts", [])
    }
    out: set[str] = set()
    for vol in pod_spec.get("volumes", []):
        sec = vol.get("secret") or {}
        base = mounts.get(vol.get("name", ""))
        if not base or not sec:
            continue
        out |= {f"{base}/{item['path']}" for item in sec.get("items", [])}
    return out


def test_volume_secret_sources_are_explained_objects(pod_spec):
    """卷侧的 Secret 引用以前没有任何一格查（③ 只看 env 里的 secretKeyRef）。
    secretName 漂了 = Pod 起不来（读数明显）；**items[].path 写错是另一种形状**：Pod 起来了、
    /health 全绿，登录面当场 503 —— 后者才是本格要防的假灯。"""
    for vol in pod_spec.get("volumes", []):
        sec = vol.get("secret")
        if not sec:
            continue
        obj = sec["secretName"]
        assert obj in _CLUSTER_OWNED_SECRET_OBJECTS, (
            f"卷 {vol['name']} 引用了未交代来源的 Secret 对象 {obj}"
        )
        for item in sec.get("items", []):
            assert item["key"] in _CLUSTER_OWNED_SECRET_KEYS, (
                f"{obj}/{item['key']} 不在集群自有键清单内"
            )
        assert sec.get("defaultMode"), (
            f"卷 {vol['name']} 未声明 defaultMode（密钥要 0440 + fsGroup 才不被同 Pod 其他进程读到）"
        )


def test_login_face_key_paths_are_mounted_shapes(container, pod_spec):
    """两个 *_FILE 的值必须能在清单里算出来（不是“看着像一条路径”）。
    改了挂载层级而 env 没跟，现场是“签不出令牌”的 503，而不是启动失败。"""
    env = {e["name"]: e.get("value") for e in container["env"]}
    paths = _secret_file_paths(pod_spec)
    for name in ("TENANT_JWT_PRIVATE_KEY_FILE", "TENANT_JWT_PUBLIC_KEYS_FILE"):
        value = env.get(name)
        assert value, (
            f"{name} 未注入 ⇒ identity.load_* 按空串早退，登录面整体 503（而 /health 全绿）"
        )
        assert value in paths, (
            f"{name}={value} 不在 secret 卷算出的路径集 {sorted(paths)} 里（挂载与 env 分叉）"
        )


def test_login_signing_params_from_manifest_are_self_consistent(container, configmap, tmp_path, monkeypatch):
    """把清单声明的那组值拿去**真签一枚、再走真 verify_token 验回来**。

    为什么不只比数字：kid 与公钥 JSON 顶层键、TTL 与上限、iss/aud 默认值是四把互相顶的参数，
    在清单里全长得像字符串，对着看只会漏（本轮实测过一次：ttl=28800 超上限 3600，症状是
    “登录 200、下一个请求 401”）。跑一次真实通路 = 四把一起钉。
    密钥是本用例现造的随机 RSA，只活在 tmp_path：仓里连一枚可用的演示私钥都不该有。
    """
    pytest.importorskip("jwt", reason="验签要 agent-runtime[identity]（PyJWT[crypto]）")
    from agent_runtime.identity import mint_token, verify_token
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    env = _manifest_effective_env(container, configmap)
    # 先清 CI/本机残留的同名 env，再按清单值设：否则测的不是清单而是一台机器的环境。
    for k in ("TENANT_JWT_ISSUER", "TENANT_JWT_AUDIENCE", "TENANT_JWT_MAX_TTL_S", "TENANT_JWT_CLOCK_SKEW"):
        monkeypatch.delenv(k, raising=False)
        if k in env:
            monkeypatch.setenv(k, env[k])
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    pub = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()
    monkeypatch.setenv("TENANT_JWT_PRIVATE_KEY_FILE", str(tmp_path / "jwt.key"))
    (tmp_path / "jwt.key").write_text(priv, encoding="utf-8")
    # 公钥集按清单的 kid 命名（这一句就是“两边必须逐字相同”那条约束的可执行形）
    (tmp_path / "jwt-pubs.json").write_text(
        json.dumps({env["TENANT_JWT_KID"]: pub}), encoding="utf-8"
    )
    monkeypatch.setenv("TENANT_JWT_PUBLIC_KEYS_FILE", str(tmp_path / "jwt-pubs.json"))

    ttl = int(env["AUTH_TOKEN_TTL"])
    token = mint_token(
        env.get("SINGLE_TENANT", "default"),
        user_id="manifest-selftest",
        private_key_pem=priv,
        kid=env["TENANT_JWT_KID"],
        ttl=ttl,
    )
    claims = verify_token(token)  # kid 对不上 / TTL 超上限 / iss-aud 分叉都在这跑里抛
    assert claims.user_id == "manifest-selftest", claims
    assert claims.exp is not None and claims.iat is not None
    assert int(claims.exp) - int(claims.iat) == ttl, f"清单声明 ttl={ttl}，实际签出的不是这个数"


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
# ⑥b 跨服务调用地址：必须与对方 Service 对象算得出同一个值
# ---------------------------------------------------------------------------


def _nl2sql_service() -> dict:
    return next(d for d in _load(_NL2SQL) if d["kind"] == "Service")


def test_nl2sql_service_url_matches_the_service_object(container):
    """平台调问数服务的地址，必须能从 30 的 Service 对象算出来。

    之前这里写的是 localhost:8001——集群内根本不通（localhost 是 Pod 自己），
    而平台侧探针全绿：坏掉的只有“学习反馈”这一条用户路径。地址、端口、namespace
    三件都得跟 Service 对象比，而不是在测试里抄第 N 份字面值。
    """
    svc = _nl2sql_service()
    ports = svc["spec"]["ports"]
    assert len(ports) == 1, f"30 的 Service 期望单端口：{ports}"
    expected = f"http://{svc['metadata']['name']}:{ports[0]['port']}"
    items = [e for e in container["env"] if e["name"] == "NL2SQL_SERVICE_URL"]
    assert items, "平台未注入 NL2SQL_SERVICE_URL ⇒ /sql/train 无法转发到问数服务"
    assert "value" in items[0], "跨服务地址不是字面值，去查它引用了哪份 CM 键（两消费方同值就分叉了）"
    assert items[0]["value"] == expected, (
        f"平台里的 NL2SQL_SERVICE_URL={items[0]['value']!r}，而 30 的 Service 算出来是 {expected!r}"
    )
    dep_ns = next(d for d in _load(_DEPLOY) if d["kind"] == "Deployment")["metadata"]["namespace"]
    assert svc["metadata"]["namespace"] == dep_ns, (
        "短名 DNS 只在同 namespace 解得出；两边不同 ns 就要写全限定名"
    )


def test_platform_does_not_inject_sql_dsn(container):
    """平台不注入 SQL_DSN（问数数据面已换到 nl2sql-service，ADR-0011 选项 A）。

    批次 4 摘掉注入时 `sql_dsn` 仍是 Settings 字段 ⇒ 通用死键门禁（①）验不出它：它“有效”，
    但当时的唯一读点是 /health 的 `sql_backend=detect_dialect(settings.sql_dsn)`，注它只会让
    那盏灯拿**平台库**的方言冒充问数读数（问数真正用的是 nl2sql_dw）。批次 5（2026-10-28）
    把字段与灯一并退役后，①已经能咬住这个名字；本用例仍要点名的理由是：若有人为了让①过关
    而把 `sql_dsn` 加回 Settings，①会再度沉默，而这里会直接说清“为什么这个名字不许回来”。
    """
    assert "SQL_DSN" not in _manifest_env(container), (
        "平台清单注入了 SQL_DSN：平台侧已无任何代码读它（字段随批次 5 退役），"
        "业务库连接串属于 nl2sql-service 的 DW_DB_DSN"
    )


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
    with pytest.raises(AssertionError, match="未被任何工作负载引用的键"):
        test_configmap_has_no_dead_keys(bad_cm)

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

    # (f) 把已退役的 SQL_DSN 注回平台（假灯形状）⇒ 专属门禁要红
    bad_ctr5 = copy.deepcopy(container)
    bad_ctr5["env"].append({"name": "SQL_DSN", "value": "postgresql://x/y"})
    with pytest.raises(AssertionError, match="SQL_DSN"):
        test_platform_does_not_inject_sql_dsn(bad_ctr5)

    # (g) 地址改回 localhost 或 Service 改名后没同步 ⇒ 与 Service 对象的比对要红
    bad_ctr6 = copy.deepcopy(container)
    for e in bad_ctr6["env"]:
        if e["name"] == "NL2SQL_SERVICE_URL":
            e["value"] = "http://localhost:8001"
    with pytest.raises(AssertionError, match="NL2SQL_SERVICE_URL"):
        test_nl2sql_service_url_matches_the_service_object(bad_ctr6)

