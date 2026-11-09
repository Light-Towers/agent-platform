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
# ③c 操作面书面两件（README §6.3 / runbook §3.2）与清单、与已入库客户端同源
# ---------------------------------------------------------------------------

#: 两份“照着敲”的文档，各自从哪个小节标题起算正文。锚点写死成小节号而不是标题全文：
#: 小节被改名/删掉时本格会当场红（那是好事）而不是退化成空跑。
_FACE_DOCS = {
    "deploy/k8s/README.md": "### 6.3 ",
    "docs/operations/minimal-release-runbook.md": "### 3.2 ",
}
_MOUNT_NS = "/run/app-secrets/"
_LOGIN_FACE_FILE_ENVS = ("TENANT_JWT_PRIVATE_KEY_FILE", "TENANT_JWT_PUBLIC_KEYS_FILE")
#: 探针必须读的四个响应字段。“200 但字段不对”在本仓一律不算成功（与 auth.ts 的
#: `sessionFrom` 同口径），所以这四个名字同时得在已入库客户端里出现。
_ASSERTION_FIELDS = ("access_token", "tenant_id", "user_id", "is_admin")


def _face_sections() -> dict[str, str]:
    """取两份文档各自锚点小节的正文（到下一个标题为止）。

    两个细节都是为了让本格**不假绿**：
    - 切到文件末尾会放行假绿：README 后半部分的任意一处 `\"platform\"` 都能替 §6.3 顶数；
    - 判标题时必须跳代码围栏：围栏里的 `# 注释` 不是标题，否则小节正文会被自己断短。
    """
    out: dict[str, str] = {}
    for rel, anchor in _FACE_DOCS.items():
        lines = (_ROOT / rel).read_text(encoding="utf-8").splitlines(keepends=True)
        start = next((i for i, ln in enumerate(lines) if ln.startswith(anchor)), None)
        assert start is not None, f"{rel} 里找不到小节锚点 {anchor!r} ⇒ 书面件被搬走，本格空跑"
        in_fence = False
        end = len(lines)
        for j in range(start + 1, len(lines)):
            if lines[j].lstrip().startswith("```"):
                in_fence = not in_fence
                continue
            if not in_fence and re.match(r"#{2,4} ", lines[j]):
                end = j
                break
        out[rel] = "".join(lines[start:end])
    return out


def _mounted_path_literals(text: str) -> set[str]:
    """文档里“看起来是挂载命名空间下的一个文件”的字面（反引号内外都算：命令块里那些同样会被照敲）。
    两条排除都是必要的：`/run/app-secrets`（裸目录，讲层级关系时用）与 `/run/secrets`（kubelet SA
    token 那个坑，文中是**反例**）都不该被当成“照敲的人要用的路径”。"""
    return {
        m
        for m in re.findall(_MOUNT_NS + r"[A-Za-z0-9._/\-]+", text)
        if "." in m.rsplit("/", 1)[-1]
    }


def _client_auth_src() -> str:
    return (_ROOT / "web" / "src" / "api" / "auth.ts").read_text(encoding="utf-8")


def _client_auth_paths(src: str) -> set[str]:
    """已入库的凭据面客户端声明的 `/auth/*` 路径（`const X_PATH = '/auth/...'`）。
    **不取 auth_router**：那个文件此刻还在并行线手里、不在本刀可提交树内 ⇒ 若从它 import，
    候选树的未解析 import 那格会把我自己判红。客户端这一侧在 HEAD 里，够用。"""
    return set(re.findall(r"const [A-Z_]+_PATH\s*=\s*'(/auth/[^']*)'", src))


def _jwt_secret_face(pod_spec: dict) -> tuple[str, set[str]]:
    """(承载登录面的 Secret 对象名, 它的 items[].key 全集) —— 两个值都从清单派生，不在本文件手抄。"""
    for vol in pod_spec.get("volumes", []):
        sec = vol.get("secret") or {}
        keys = {i["key"] for i in sec.get("items", [])}
        if "TENANT_JWT_PRIVATE_KEY" in keys:
            return str(sec["secretName"]), keys
    raise AssertionError("清单里没有承载 TENANT_JWT_PRIVATE_KEY 的 secret 卷（③b 那格会先红）")


def _check_doc_against_manifest(rel: str, sec: str, env: dict[str, str], mounted: set[str]) -> None:
    invented = _mounted_path_literals(sec) - mounted
    assert not invented, (
        f"{rel} 写了清单算不出来的容器内路径 {sorted(invented)}"
        "（照敲的人当场 FileNotFoundError，而本机门禁不会替他发现）"
    )
    for name in _LOGIN_FACE_FILE_ENVS:
        assert env[name] in sec, (
            f"{rel} 里没出现清单生效值 {name}={env[name]!r} ⇒ 改了挂载而文档没跟，是静默漂移"
        )


def _check_readme_face(readme: str, obj: str, keys: set[str], kid: str) -> None:
    assert obj in readme, f"README §6.3 没点到清单里的 Secret 对象名 {obj!r}"
    for k in sorted(keys):
        # \b 不是多余的谨慎：TENANT_JWT_PRIVATE_KEY 是 ..._KEY_FILE 的子串，
        # 不加词边界就变成“文档提过那个 env”也算过，这一格当场被自己糊掉。
        assert re.search(rf"\b{re.escape(k)}\b", readme), (
            f"README §6.3 没点到 items 的键名 {k}（对象/键改名而文档没跟）"
        )
    assert "TENANT_JWT_KID" in readme, "README §6.3 没点到 CM 的 kid 键名"
    # 带引号的字面，不是裸子串：现值叫 platform 时，裸词形会被对象名 agent-platform-jwt
    # 直接喂饱（连字符不是词字符 ⇒ \\bplatform\\b 命中中间那段），那一格就是永久空跑。
    assert f'"{kid}"' in readme, (
        f"README §6.3 没把 CM 的 kid 现值以带引号的字面写出来（期望 '{kid!r}'）"
        " ⇒ “两边逐字相同”这条只能读文档的人自己核，本格就是替他核"
    )


def _check_probe_cells(text: str, client_paths: set[str], client_src: str) -> None:
    used = set(re.findall(r'call\("[A-Z]+",\s*"(/auth/[^"]*)"', text))
    assert used, "runbook §3.2 里没有一条 call(...) ⇒ 探针格子被换成了散文，本格空跑"
    unknown = used - client_paths
    assert not unknown, f"探针打了客户端没有的路径 {sorted(unknown)}（端点名靠猜那一型）"
    assert used >= {"/auth/register", "/auth/login", "/auth/me"}, f"探针缺端点：{sorted(used)}"
    for field in _ASSERTION_FIELDS:
        assert field in text, f"探针不再读 {field} ⇒ 该字段的判据没人在现网核了"
        assert field in client_src, f"{field} 在已入库客户端里消失了（文档在读一个没人产出的键）"


def test_login_face_docs_are_same_source_with_manifest_and_client(container, pod_spec, configmap):
    """书面两件的六向同源：容器内路径 / 两个 `*_FILE` 生效值 / Secret 对象名 /
    items 键名 / CM 的 kid 现值 / 探针端点与响应字段。

    为什么值当单独一格：①b 与 §3.2 是“现网能不能签得出来”的唯一可照敲路径，
    而它们写的都是字面（路径、键名、端点）。字面漂了不会让 apply 报错、不会让 gate 红，
    只会让下一个拿手册的人对着一个不存的路径查半天（③ 那格防的就是同一型，只是当时只有清单一侧）。
    """
    env = {e["name"]: e.get("value") for e in container["env"]}
    mounted = _secret_file_paths(pod_spec)
    sections = _face_sections()
    for rel, sec in sections.items():
        _check_doc_against_manifest(rel, sec, env, mounted)
    client_src = _client_auth_src()
    obj, keys = _jwt_secret_face(pod_spec)
    _check_readme_face(
        sections["deploy/k8s/README.md"],
        obj,
        keys,
        str((configmap.get("data") or {})["TENANT_JWT_KID"]),
    )
    _check_probe_cells(
        sections["docs/operations/minimal-release-runbook.md"],
        _client_auth_paths(client_src),
        client_src,
    )


def test_face_gate_bites_on_the_doc_drift_shapes(container, pod_spec, configmap):
    """③c 的非空洞性：五种漂移形状逐条注回去（与 ⑦ 同口径，合成注入不碰盘上文件）。"""
    env = {e["name"]: e.get("value") for e in container["env"]}
    mounted = _secret_file_paths(pod_spec)
    sections = _face_sections()
    rel = "docs/operations/minimal-release-runbook.md"
    run = sections[rel]
    readme = sections["deploy/k8s/README.md"]
    obj, keys = _jwt_secret_face(pod_spec)
    kid = str((configmap.get("data") or {})["TENANT_JWT_KID"])
    client_src = _client_auth_src()

    # (a) 文档里的挂载路径少写一层子目录 ⇒ 清单算不出，必须点名
    bad = run.replace(env["TENANT_JWT_PRIVATE_KEY_FILE"], "/run/app-secrets/jwt.key")
    with pytest.raises(AssertionError, match="清单算不出来的容器内路径"):
        _check_doc_against_manifest(rel, bad, env, mounted)

    # (b) 清单换了挂载位置而文档没跟（把文档里的路径整片抹掉就是这一形的读数）
    stripped = re.sub(_MOUNT_NS + r"[A-Za-z0-9._/\-]+", "/mnt/x", run)
    with pytest.raises(AssertionError, match="改了挂载而文档没跟"):
        _check_doc_against_manifest(rel, stripped, env, mounted)

    # (c) items 键名改名而 README 没跟
    with pytest.raises(AssertionError, match="items 的键名"):
        _check_readme_face(re.sub(r"TENANT_JWT_PUBLIC_KEYS", "PUBKEYS", readme), obj, keys, kid)

    # (d) CM 里的 kid 改了名而 README 还写着旧值（带引号那一层就是这一格的可测形）
    with pytest.raises(AssertionError, match="kid 现值"):
        _check_readme_face(readme.replace(f'"{kid}"', '"old-kid"'), obj, keys, kid)

    # (e) 探针端点名靠猜（/auth/me 写成 /auth/whoami）
    with pytest.raises(AssertionError, match="客户端没有的路径"):
        _check_probe_cells(run.replace('"/auth/me"', '"/auth/whoami"'), _client_auth_paths(client_src), client_src)

    # (f) 探针退化成散文（一条 call 都没有）
    with pytest.raises(AssertionError, match="没有一条 call"):
        _check_probe_cells("", _client_auth_paths(client_src), client_src)


# ---------------------------------------------------------------------------
# ③d deploy/ 里的小节引用必须自带可解析全路径：裸 `README §N.M` 一律红
# ---------------------------------------------------------------------------

#: 射程 = deploy/ 下会被 kubectl / psql 读的那几类文件。注释里的小节引用不是装饰，
#: 是「照着敲的人」的路线图，所以它和 ③c 那六向字面同一条链上。
_CITE_SUFFIXES = (".md", ".yaml", ".yml", ".sql")
#: 裸形 = `README` 不跟 `.md` 就直接接 `§`。它的问题不是「写得简」，是**可被静默改判**：
#: 本批实测的成因就是它 —— nl2sql 侧三处注释引的 §6.3 在当时的 README 里根本不存在
#: （悬空引用），本刀新建「登录面签名密钥」占了同号之后，它们当场从「查无此节」变成
#: 「解析成功但主题全错」，比悬空更坏：照图翻过去会读到一把完全不相干的密钥。
_BARE_README_CITE = re.compile(r"(?<![\w./-])README\s+§")
_FULL_CITE = re.compile(r"([A-Za-z0-9._/\-]+\.md)\s+§(\d+(?:\.\d+)*)")
_HEADING_NUM = re.compile(r"^#{1,4}[ \t]+(\d+(?:\.\d+)*)[ \t.]")


def _deploy_cite_face() -> list[str]:
    out = []
    for path in sorted((_ROOT / "deploy").rglob("*")):
        if path.is_file() and path.suffix in _CITE_SUFFIXES:
            out.append(path.relative_to(_ROOT).as_posix())
    assert out, "deploy/ 下扫不到任何可引小节的文件 ⇒ 本格空跑，不是干净通过"
    return out


def _heading_numbers(text: str) -> set[str]:
    """fence-aware 的小节号集合。跳围栏是这一格能不能咬人的关键：README 的 shell 块里有
    `# 1.1 关 swap` 那种注释行，拿它当标题就会让 `§1.1` 这种引用被静默放行。"""
    nums: set[str] = set()
    in_fence = False
    for ln in text.splitlines():
        if ln.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = _HEADING_NUM.match(ln)
        if m:
            nums.add(m.group(1))
    return nums


def _check_citations(items: dict[str, str]) -> None:
    """两半：裸形必须消失（R-a），全形必须解析到真实存在的节号（R-b）。

    存在性按文件系统判，与 `scripts/check_doc_sync.py` 的版本控制清单基准不同一条链：
    那一把管的是文档正文里的**路径**引用，这一把只管 deploy/ 注释里的**节号**能不能落到
    一个真存在的标题上。被引文件只在本机存在而没入库，不在本格的射程内（如实写明，不假称覆盖）。
    """
    bare: list[str] = []
    unresolved: list[str] = []
    cache: dict[str, set[str]] = {}
    for rel, text in items.items():
        for i, ln in enumerate(text.splitlines(), 1):
            if _BARE_README_CITE.search(ln):
                bare.append(f"{rel}:{i}")
            for target, num in _FULL_CITE.findall(ln):
                if target not in cache:
                    f = _ROOT / target
                    cache[target] = _heading_numbers(f.read_text(encoding="utf-8")) if f.is_file() else set()
                if num not in cache[target]:
                    # 两种情形成因不同、处置也不同，所以分两条报：换文件名去重找，还是
                    # 那个节号本来就没写成 —— 把后者当成前者就是“把没写的东西当旧版本”。
                    if not (_ROOT / target).is_file():
                        unresolved.append(f"{rel}:{i} 引 {target}（该文件不在仓库里）")
                    else:
                        unresolved.append(f"{rel}:{i} 引 {target} §{num}（那一节不存在）")
    # 两半合并成一个判决，而不是连着两条 assert：本批真面反证实踩过——只种 P1 时第一条
    # assert 就当场退出，P2（节号不存在）根本没被判过，“1 failed”看起来满绿牙齿、
    # 其实是半口。一条消息里同时点名两类，才担得起“每条都判了”这句陈述。
    verdicts: list[str] = []
    if bare:
        verdicts.append(
            f"裸形小节引用 {bare}：只写 `README §` 而不带路径 ⇒ 下一个新建同节号的人会替它改判主题，"
            "而且改完不会有任何一格报红"
        )
    if unresolved:
        verdicts.append(f"小节引用解析不到真实标题：{unresolved}")
    assert not verdicts, "；".join(verdicts)


def test_deploy_section_citations_resolve_to_real_headings():
    """③d 正跑：deploy/ 注释里的每一条 `§` 引用都必须带着能解析的全路径。"""
    items = {rel: (_ROOT / rel).read_text(encoding="utf-8") for rel in _deploy_cite_face()}
    _check_citations(items)


def test_citation_gate_bites_on_the_four_shapes():
    """③d 的非空洞性：四种形状逐条注回去（与 ③c 同口径，合成注入不碰盘上文件）。"""
    # 正形：带全路径且节号真实存在
    _check_citations({"deploy/k8s/x.yaml": "# 见 deploy/k8s/README.md §6.3。\n"})
    # (a) 裸形 —— 正是本批被自己的新节喂成假解析的那一形
    with pytest.raises(AssertionError, match="裸形小节引用"):
        _check_citations({"deploy/k8s/x.yaml": "# 见 README §6.3。\n"})
    # (b) 全形但节号不存在
    with pytest.raises(AssertionError, match="那一节不存在"):
        _check_citations({"deploy/k8s/x.yaml": "# 见 deploy/k8s/README.md §9.9。\n"})
    # (c) 全形但文件不存在
    with pytest.raises(AssertionError, match="该文件不在仓库里"):
        _check_citations({"deploy/k8s/x.yaml": "# 见 docs/operations/no-such-file.md §1。\n"})
    # (d) 围栏里的假标题不能被当成“存在”：README 的 shell 块里就有 `# 1.1 关 swap`，
    #     不跳围栏时这一形会让 §1.1 被静默放行，(b) 也会跟着退化。
    with pytest.raises(AssertionError, match="那一节不存在"):
        _check_citations({"deploy/k8s/x.yaml": "# 见 deploy/k8s/README.md §1.1。\n"})



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
# ⑥c 入口可达面：Service 类型与钉住的 nodePort（2026-11-06 拍板 ClusterIP→NodePort）
# ---------------------------------------------------------------------------

#: k8s 默认 NodePort 分配域。域外的值不会被 API server 接受，而“域内撞了别人已占的口”
#: 本格管不着 —— 那只能对现网取，判据在 runbook §5 基线 3。
_NODEPORT_RANGE = (30000, 32767)


def _platform_service() -> dict:
    return next(d for d in _load(_DEPLOY) if d["kind"] == "Service")


def _check_entry_service(svc: dict) -> None:
    """入口 Service 的三条不变量。判据只写一遍：真格与非空洞性格共用它。

    钉的都是会让「入口一直在线」重新退化成口头承诺的漂移：
    - 换回 ClusterIP ⇒ 唯一进入路径又只剩 port-forward，而它在取证面里已经死过两次；
    - 不钉 nodePort ⇒ 每次 apply 由集群随机分配，写进手册的地址当场作废；
    - 钉了但 `port`/`targetPort` 与容器自己的 8000 分叉 ⇒ 地址对、打过去是空的。
    """
    svc_type = svc["spec"].get("type")
    assert svc_type == "NodePort", (
        f"入口 Service type={svc_type!r}：ClusterIP 下唯一进入路径是 port-forward，"
        "那是一条会断的流（依据逐字在清单 Service 段注释里）"
    )
    ports = svc["spec"]["ports"]
    assert len(ports) == 1, f"入口 Service 期望单端口：{ports}"
    p = ports[0]
    assert p.get("nodePort"), (
        "type=NodePort 却没写 nodePort ⇒ 每次 apply 随机分配，手册里那个入口地址当场作废"
    )
    lo, hi = _NODEPORT_RANGE
    assert lo <= int(p["nodePort"]) <= hi, f"nodePort={p['nodePort']} 不在默认分配域 {lo}..{hi}"
    assert p["port"] == p["targetPort"] == 8000, (
        f"入口 Service port/targetPort={p['port']}/{p['targetPort']}，而容器自己听的是 8000"
    )


def test_entry_service_is_pinned_nodeport():
    """入口必须一直在线，且它的地址必须能从清单算出来 —— 不靠“某台宿主上有个前台进程”。

    2026-11-06 拍板：Service 从 ClusterIP 换成 NodePort（D2 可达面变更；为什么改、
    露出了什么、当时的鉴权实测读数都在清单 Service 段注释里）。本格不复述那段理由，
    只钉住三件会漂移回来的形状。

    边界（本格**不**判）：该口在三台宿主上是否已被其他进程占用、集群里是否已有同名
    nodePort —— 那两条是现网读数，只能 apply 前现场核对（runbook §5 基线 3），
    把它们写成清单断言就等于把未验的假设钉成门禁。
    """
    _check_entry_service(_platform_service())


def test_runbook_entry_port_matches_the_service_object():
    """手册里那个“给人点的口”必须等于清单算出来的 nodePort，不是第 N 份手抄字面值。

    与 ⑥b 同一条纪律，只是消费方从代码换成了文档：runbook 基线 3 写死了那个号，
    清单改了端口而手册没跟，用户拿到的就是「地址在、打不通」。
    """
    expected = str(_platform_service()["spec"]["ports"][0]["nodePort"])
    text = (_ROOT / "docs/operations/minimal-release-runbook.md").read_text(encoding="utf-8")
    assert expected in text, (
        f"清单算出 nodePort={expected}，而 runbook 里没有这个口 ⇒ 手册给的入口地址已失效"
    )


def test_entry_gate_bites_on_the_four_drift_shapes():
    """⑥c 的四枚非空转反证：把四种真发生过的漂移形状注回去，逐条确认会咬。"""
    import copy

    base = _platform_service()

    bad_a = copy.deepcopy(base)
    bad_a["spec"]["type"] = "ClusterIP"
    with pytest.raises(AssertionError, match="ClusterIP"):
        _check_entry_service(bad_a)

    bad_b = copy.deepcopy(base)
    del bad_b["spec"]["ports"][0]["nodePort"]
    with pytest.raises(AssertionError, match="nodePort"):
        _check_entry_service(bad_b)

    bad_c = copy.deepcopy(base)
    bad_c["spec"]["ports"][0]["nodePort"] = 80
    with pytest.raises(AssertionError, match="默认分配域"):
        _check_entry_service(bad_c)

    bad_d = copy.deepcopy(base)
    bad_d["spec"]["ports"][0]["targetPort"] = 8080
    with pytest.raises(AssertionError, match="targetPort"):
        _check_entry_service(bad_d)


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

