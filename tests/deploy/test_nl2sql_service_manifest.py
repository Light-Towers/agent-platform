r"""批次 3：`deploy/k8s/30-nl2sql-service.yaml` 的接线门禁。

守的都是同一类形状：**apply 不报错、Pod 起得来、但那个开关其实没生效**。
平台侧已经有同类门禁（`test_k8s_manifest_wiring.py`），本份把它对问数服务这一半补齐，
并加上只有跨清单才会出现的分叉（30 在线召回 vs 36 元库构建读到的向量口径不是同一份值）。

判据一律引用代码里的常量/字段，不在用例里抄第二份字面值：抄一份就多出一个人需要
同时改两处、而没有任何机器判据会红的地方。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[2]
_K8S = _ROOT / "deploy" / "k8s"
_SERVICE = _K8S / "30-nl2sql-service.yaml"
_META_JOB = _K8S / "36-nl2sql-meta-init-job.yaml"
_PLATFORM = _K8S / "20-agent-platform.yaml"
_CONFIG = _K8S / "00-config.yaml"
_SECRETS = _K8S / "05-secrets.yaml"

#: 向量口径与数据源作用域：元库列宽（36 写）与在线召回（30 读）必须同源。
_SHARED_META_KEYS = ("VECTOR_DIM", "EMBEDDING_BACKEND", "EMBEDDING_MODEL", "TOKENIZER", "DATASOURCE_ID")

#: 本服务镜像里**没有消费方**的键（批次 1 查实：镜像不带 [langfuse] extra，且全仓只有
#: agent_server/agent/llm.py 调 get_langfuse_callbacks）。注进去是死键——"配了不生效"
#: 比"没配"更难查，所以把它写成禁止项，而不是留一句注释指望下一个人读到。
_FORBIDDEN_ENV = {"LANGFUSE_HOST", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"}

#: 平台清单那套自定义 OTEL_* env 名：agent_server 的 Settings 有这些字段，nl2sql 的没有
#: （extra="ignore" ⇒ 静默吞掉）。nl2sql 的观测读取点是 agent_core.tracing 的内核名。
_PLATFORM_ONLY_OTEL = {"OTEL_ENABLED", "OTEL_ENDPOINT", "OTEL_EXPORTER", "OTEL_SERVICE_NAME"}

#: 第三方库直接读的标准 env（仓内无读取点是正常的，实测设这三个可离线加载权重）
_THIRD_PARTY_ENV = {"HF_HOME", "HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "OMP_NUM_THREADS"}

#: 不许被 Secret 卷占用的挂载路径。2026-10-28 在 126 用本镜像实跑探针：**只读 tmpfs 先占住
#: /run/secrets 后，runc 再为 SA token 建 /var/run/secrets/kubernetes.io 子目录就是 EROFS**，
#: 容器创建失败、Pod 永远起不来（apply 不报错、清单看起来完全合法）。镜像里 /var/run 就是 /run。
_SA_TOKEN_SHADOW_PATHS = ("/run/secrets", "/var/run/secrets")

#: 集群自有 Secret 对象与其键（真实值永不入库，见 05-secrets.yaml 头部）
_CLUSTER_OWNED_SECRET_OBJECTS = {"observability-keys"}
_CLUSTER_OWNED_SECRET_KEYS = {
    "LLM_API_KEY",
    "API_KEY",
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
    "INTERNAL_HMAC_KEY",
}

_ENV_READ_RE = re.compile(
    r"""(?:os\.getenv\(|os\.environ\.get\(|os\.environ\[|env_bool\(|env_str\(|env_int\()\s*["']"""
    r"""([A-Z][A-Z0-9_]{2,})["']"""
)


def _docs(path: Path) -> list[dict]:
    out = [d for d in yaml.safe_load_all(path.read_text(encoding="utf-8")) if d]
    assert out, f"{path.name} 解析出 0 个对象（YAML 缩进/语法问题）"
    return out


def _deployment() -> dict:
    hits = [d for d in _docs(_SERVICE) if d["kind"] == "Deployment"]
    assert len(hits) == 1, f"30 应恰有一个 Deployment：{[d['kind'] for d in _docs(_SERVICE)]}"
    return hits[0]


def _service() -> dict:
    hits = [d for d in _docs(_SERVICE) if d["kind"] == "Service"]
    assert len(hits) == 1, f"30 应恰有一个 Service：{[d['kind'] for d in _docs(_SERVICE)]}"
    return hits[0]


def _pod_spec() -> dict:
    return _deployment()["spec"]["template"]["spec"]


def _container() -> dict:
    ctrs = _pod_spec()["containers"]
    assert len(ctrs) == 1, f"30 期望单容器（多容器就要交代各自的职责与探针）：{len(ctrs)}"
    return ctrs[0]


def _meta_job_container() -> dict:
    docs = _docs(_META_JOB)
    jobs = [d for d in docs if d["kind"] == "Job"]
    assert len(jobs) == 1, f"36 应恰有一个 Job：{[d['kind'] for d in docs]}"
    ctrs = jobs[0]["spec"]["template"]["spec"]["containers"]
    assert len(ctrs) == 1, f"36 期望单容器：{len(ctrs)}"
    return ctrs[0]


def _configmap() -> dict:
    hits = [d for d in _docs(_CONFIG) if d["kind"] == "ConfigMap"]
    assert len(hits) == 1, f"00-config 应恰有一个 ConfigMap：{len(hits)}"
    return hits[0]


def _env_items(ctr: dict) -> list[dict]:
    return ctr["env"]


def _env_names(ctr: dict) -> set[str]:
    return {e["name"] for e in _env_items(ctr)}


def _cm_ref(name: str, ctr: dict) -> tuple[str, str]:
    """取某个 env 的 configMapKeyRef (对象名, 键名)；不是 CM 引用即判失败。"""
    for e in _env_items(ctr):
        if e["name"] != name:
            continue
        ref = (e.get("valueFrom") or {}).get("configMapKeyRef")
        assert ref, f"env {name} 不是 configMapKeyRef（值被写成了字面量：跨清单必然分叉）"
        return ref["name"], ref["key"]
    raise AssertionError(f"清单没有注入 env {name}")


def _secret_volumes(pod: dict) -> dict[str, dict]:
    return {v["name"]: v["secret"] for v in pod.get("volumes", []) if "secret" in v}


def _workload_pod_and_container(path: Path) -> tuple[dict, dict]:
    """按文件取（PodSpec, 单容器）。20/30 两份清单的密钥形状要拿同一套判据跑，
    不在第二份文件里抄一套简化版——简化版就是“签发侧没被同样的门禁看住”。"""
    workload = next(d for d in _docs(path) if d["kind"] in ("Deployment", "Job"))
    pod = workload["spec"]["template"]["spec"]
    ctrs = pod["containers"]
    assert len(ctrs) == 1, f"{path.name} 期望单容器：{len(ctrs)}"
    return pod, ctrs[0]


def _secret_mount_for(pod: dict, ctr: dict, key_path: str) -> tuple[dict, dict] | None:
    """按密钥文件路径找出（挂载项, Secret 卷定义）；路径不在任何 Secret 卷下则 None。

    单侧判据与跨清单比对共用这一份实现：否则“挂载点怎么算”会有两套口径，
    而两边都错得很自洽时，门禁会一起绿。
    """
    secret_volumes = _secret_volumes(pod)
    for m in ctr.get("volumeMounts", []):
        vol = secret_volumes.get(m["name"])
        if vol is not None and key_path.startswith(str(m["mountPath"]).rstrip("/") + "/"):
            return m, vol
    return None


def _hmac_shape(pod: dict, ctr: dict) -> dict[str, object]:
    """密钥挂载的六件事实（路径/来源对象/键/投影文件名/模式/fsGroup）。

    两侧任一项分叉，表现都是“/sql/train 全线 401 而两侧探针全绿”：签出去的头验不过，
    不是“哪里报错”而是“哪里都不报错”。逐字段列出值，比在散文里写一句“要一致”更能指认“哪一件不同”。
    """
    env = {e["name"]: e.get("value") for e in _env_items(ctr)}
    key_path = str(env.get("INTERNAL_HMAC_KEY_FILE") or "")
    mount, vol = _secret_mount_for(pod, ctr, key_path) or ({}, {})
    items = vol.get("items") or []
    return {
        "key_file": key_path,
        "mount_path": mount.get("mountPath"),
        "secret_name": vol.get("secretName"),
        "secret_key": items[0]["key"] if items else None,
        "projected": items[0]["path"] if items else None,
        "mode": vol.get("defaultMode"),
        "fs_group": (pod.get("securityContext") or {}).get("fsGroup"),
    }


def _secret_objects_in_repo() -> tuple[str, dict[str, str]]:
    """入库那份 demo Secret 的（对象名, 键→值）。值都是 demo 口径，不涉密。"""
    sec = next(d for d in _docs(_SECRETS) if d["kind"] == "Secret")
    values = dict(sec.get("stringData") or {})
    values.update(sec.get("data") or {})
    return sec["metadata"]["name"], values


def _nl2sql_consumable_env_names() -> set[str]:
    """nl2sql-service 进程真能读到的 env 名。

    三个来源逐个点名，不靠"看起来应该有读取点"：
    1. Settings 字段大写（pydantic-settings 无 env_prefix，大写即 env 名）；
    2. agent-core / agent-runtime / 本包里的字面 getenv 读取点；
    3. 以常量形式传给 getenv 的那几个（identity_assembly 显式命名、tracing 的 ENV_*）——
       它们不匹配字面量正则，**漏加就会把正确的清单判成死键**。

    只扫产品代码：测试里的一句 `os.environ["X"]` 不能证明进程读 X，把它算进
    “可读集合”就等于允许清单注一个只有测试在消费的死键。
    """
    from agent_core import tracing
    from agent_runtime.identity_assembly import ENFORCE_ENV, FAILFAST_ENV, HMAC_KEY_ENV
    from nl2sql_service.conf.settings import Settings

    names: set[str] = {f.upper() for f in Settings.model_fields}
    for pkg in (
        _ROOT / "applications" / "nl2sql-service",
        _ROOT / "packages" / "agent-core",
        _ROOT / "packages" / "agent-runtime",
    ):
        for py in pkg.rglob("*.py"):
            if _is_test_or_artifact(py, pkg):
                continue
            names.update(_ENV_READ_RE.findall(py.read_text(encoding="utf-8")))
    names.update({ENFORCE_ENV, FAILFAST_ENV, HMAC_KEY_ENV})
    names.update({tracing.ENV_OTEL_ENDPOINT, tracing.ENV_TRACE_ENABLED, tracing.ENV_SERVICE_NAME})
    return names


def _is_test_or_artifact(py: Path, pkg: Path) -> bool:
    """只挡测试/产物目录。`nl2sql_service/scripts/` 不挡：它们是 36 Job 真在跑的产品代码。"""
    parts = set(py.relative_to(pkg).parts)
    return bool(parts & {"tests", "golden", "__pycache__"}) or "conftest" in parts


# ---------------------------------------------------------------------------
# ① 基本形状：Service 与 Deployment 说的是同一个端口
# ---------------------------------------------------------------------------


def test_service_and_container_port_agree_with_probes():
    """Service 的 targetPort、containerPort、三个探针的 port 必须是一个数。

    不同步的形状是"服务活着、Service 不转"或者"探针打在一个没人听的口上"，
    而镜像 CMD 里的 8000 是第四个副本（Dockerfile.nl2sql-service 的 --port）。
    """
    ctr = _container()
    ports = [p["containerPort"] for p in ctr["ports"]]
    assert ports == [8000], f"containerPort 期望 [8000]（与镜像 CMD 一致），实际 {ports}"
    svc = _service()
    assert svc["spec"]["type"] == "ClusterIP", "与既有清单同规约：不直接暴露"
    for p in svc["spec"]["ports"]:
        assert p["targetPort"] == ports[0], f"Service targetPort={p['targetPort']} 打不到容器端口"
    for probe in ("startupProbe", "readinessProbe", "livenessProbe"):
        assert ctr[probe]["httpGet"]["port"] == ports[0], f"{probe} 的端口与 containerPort 不同"


def test_service_selector_matches_pod_labels():
    sel = _service()["spec"]["selector"]
    labels = _deployment()["spec"]["template"]["metadata"]["labels"]
    assert sel.items() <= labels.items(), f"Service selector {sel} 选不到 Pod labels {labels}（Endpoint 会是空的）"


def test_image_is_the_batch1_tag_and_pull_policy_local():
    ctr = _container()
    assert ctr["image"] == "nl2sql-service:dev", (
        f"镜像 tag 是 {ctr['image']!r}：应为批次 1 的 nl2sql-service:dev"
        "（build.sh 的 dockerfile_for 只认这个名字，写成别的会构建出'名字是 nl2sql、内容是平台'的镜像）"
    )
    assert not ctr["image"].endswith(":latest"), "latest tag 让'rev 门禁'失去意义（回滚没有旧 tag 可指）"
    assert ctr["imagePullPolicy"] == "IfNotPresent", "本地构建镜像分发到三节点，不拉远端"


def test_runs_as_non_root_uid_matching_image():
    sc = _container().get("securityContext", {})
    assert sc.get("runAsNonRoot") is True and sc.get("runAsUser") == 10001, (
        "uid 必须是镜像里的 appuser(10001)：换成别的 uid 时，只读挂载的权重缓存与"
        "Secret 卷的属主判定都不再成立（fsGroup 也是同一个 10001）"
    )
    assert _pod_spec().get("securityContext", {}).get("fsGroup") == sc["runAsUser"], (
        "Pod fsGroup 必须等于 runAsUser：Secret 卷 defaultMode 0440 是 root:<group>，"
        "两者不同号时进程读不到密钥文件（表现为 /sql/train 全线 401，而不是启动失败）"
    )


# ---------------------------------------------------------------------------
# ② env 名必须被代码读到；平台专属名与死键不许出现在这里
# ---------------------------------------------------------------------------


def test_every_env_name_is_consumed_by_the_service():
    consumable = _nl2sql_consumable_env_names()
    unknown = sorted(_env_names(_container()) - consumable - _THIRD_PARTY_ENV)
    assert not unknown, (
        f"30 注入了 nl2sql-service 读不到的 env：{unknown}。"
        "写错名字不会让 Pod 报错，只会让开关静默失效（Settings 是 extra=\"ignore\"）。"
    )


def test_no_langfuse_keys_injected_on_a_build_without_the_callback_wiring():
    _assert_no_forbidden_env(_container())


def test_observability_uses_the_kernel_env_names_not_the_platforms():
    """观测两键：env 名用内核名，值引平台 CM 的既有键。

    注 `OTEL_ENDPOINT`/`OTEL_ENABLED`（平台那套自定义名）会全绿地什么也不发生：
    nl2sql 的 Settings 没有这些字段，而 kernel 读的是 OTEL_EXPORTER_OTLP_ENDPOINT /
    AGENT_CORE_TRACE_ENABLED。值仍引 agent-platform-config 的 OTEL_* 键：端点只能写
    宿主 IP（Jaeger 在 126 的 moby 上、不在集群内），两处各写一份就是第二个会漏的端点。
    """
    _assert_observability_env(_container())


# ---------------------------------------------------------------------------
# ③ 跨清单单源：向量口径与数据源作用域不许有两份字面值
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("env_name", _SHARED_META_KEYS)
def test_shared_knobs_come_from_the_prefixed_configmap(env_name):
    assert _cm_ref(env_name, _container()) == ("agent-platform-config", f"NL2SQL_{env_name}"), (
        f"{env_name} 必须引 CM 键 NL2SQL_{env_name}（env 名 = 应用读的字段名，CM 键带前缀 = 不与平台同名词混用）"
    )


@pytest.mark.parametrize("env_name", _SHARED_META_KEYS)
def test_meta_job_reads_the_same_configmap_keys_as_the_service(env_name):
    """36 建元库列宽、30 在线召回：两侧必须是**同一个 CM 键**。

    两侧各留字面值时，"改一处"的 commit 看上去完全自洽，而线上是"写进 512 的列、
    拿 1024 的向量去查"——没有任何探针会红（列宽与向量维度不匹配在 PG 侧才报，
    而那时报的是 SQL 失败，看不出是清单分叉）。
    """
    _assert_same_shared_key(_meta_job_container(), _container(), env_name)


def test_configmap_actually_carries_the_referenced_keys():
    cm = _configmap()
    missing = sorted(f"NL2SQL_{k}" for k in _SHARED_META_KEYS if f"NL2SQL_{k}" not in cm["data"])
    assert not missing, f"00-config.yaml 缺这些键：{missing}（configMapKeyRef 指空 = Pod 起不来）"


@pytest.mark.parametrize("env_name", ("ALLOWED_TABLES", "SENSITIVE_COLUMNS"))
def test_list_typed_env_values_are_json_literals(env_name):
    """List[str] 的 env 值必须是 JSON：逗号串不是"按逗号切"。

    实测（本机，pydantic-settings 当前版本）：`ALLOWED_TABLES=users,orders` 抛
    `SettingsError: error parsing value for field "allowed_tables" from source
    "EnvSettingsSource"` ⇒ 容器 CrashLoop。清单里看着更自然的写法，落到线上是起不来。
    """
    _assert_list_json(_configmap(), env_name)


def test_data_permission_lists_are_not_empty():
    """空清单 = L2 表白名单与 L3 敏感列脱敏两层从配置面上不存在，而服务照绿。

    这不是"风格偏好"：README 把三层纵深当卖点宣传，判据要能证明应用侧那两层真有值。
    """
    cm = _configmap()
    assert json.loads(cm["data"]["NL2SQL_ALLOWED_TABLES"]), "ALLOWED_TABLES 为空 ⇒ L2 不校验表"
    assert json.loads(cm["data"]["NL2SQL_SENSITIVE_COLUMNS"]), "SENSITIVE_COLUMNS 为空 ⇒ L2 黑名单与 L3 掩码都没靶子"


def test_allowed_tables_match_the_dw_fixture_schema():
    """白名单必须与 dw fixture 建出来的表逐一对得上。

    对不齐的两种形状都坏：少写一张 = 真表被 L2 拒了（问数答"表不存在"），
    多写一张 = 白名单宣称可查而库里没有（元知识与数据面分叉）。
    """
    _assert_tables_match_fixture(_configmap())


# ---------------------------------------------------------------------------
# ④ 探针：三条各探各的，且档位与服务侧常量对齐
# ---------------------------------------------------------------------------


def test_probes_split_alive_and_ready_as_the_contract_requires():
    """startup/readiness 走 /ready（探两池），liveness 走 /health（共享契约恒 healthy）。

    把 liveness 并进 /ready 的后果：库断了一小时后进程开始重启，而重启修不好库——
    只把可观测面（span/日志）和 in-flight 请求一起陪葬。
    """
    _assert_probe_split(_container())


def test_readiness_timeout_is_looser_than_the_service_probe_budget():
    """readinessProbe.timeoutSeconds 必须 > 服务侧 _READY_PROBE_TIMEOUT_S。

    那个常量是"取连接 + SELECT 1"的总预算；探针比它短就会在服务还在等池时先判失败——
    dw 池是 OLAP 画像（语句超时 30s 档），慢是设计内的慢。常量从代码 import，
    不在这里抄第二份数字。
    """
    _assert_readiness_timeout(_container())


def test_startup_probe_window_covers_cold_model_load():
    """本地 bge 冷加载实测 0.3–10.2s（CPU torch 镜像、只读挂载），加两次池 open。

    窗口给的是失败预算而不是保险：真起不来时事件里要能看到真原因，而不是"探针超时"。
    """
    cfg = _container()["startupProbe"]
    window = cfg["periodSeconds"] * cfg["failureThreshold"]
    assert window >= 60, f"startupProbe 窗口只有 {window}s（冷加载 + 双池 open 的画像不止它）"
    assert cfg.get("timeoutSeconds", 1) > 1, "timeoutSeconds 默认 1s 会误杀在等池的探针"


def test_liveness_allows_restarts_only_on_real_hang():
    cfg = _container()["livenessProbe"]
    assert cfg["periodSeconds"] * cfg["failureThreshold"] >= 30, "liveness 窗口过窄会把 GC 停顿判成死锁"


def test_grace_period_covers_the_dw_statement_timeout():
    """排水窗口必须比 dw 的语句超时长，否则发布期会静默截断长查询。

    不声明的话吃 k8s 默认 30s，而 dw 语句超时的代码默认也是 30s——两个数相等时
    SIGKILL 正好落在合法查询的尾巴上，而探针全绿、发布“成功”，事后无错可查。
    阈值从 Settings 字段默认值取，不在这里抄一份 30000。
    """
    from nl2sql_service.conf.settings import Settings

    stmt_ms = Settings.model_fields["dw_db_statement_timeout_ms"].default
    grace = _pod_spec().get("terminationGracePeriodSeconds")
    assert grace, "未声明 terminationGracePeriodSeconds：默认 30s 与 dw 语句超时同长"
    assert grace * 1000 > stmt_ms, (
        f"grace={grace}s 不大于 dw 语句超时 {stmt_ms}ms ⇒ 发布时最后一批长查询被 SIGKILL"
    )


# ---------------------------------------------------------------------------
# ⑤ 身份档与密钥文件
# ---------------------------------------------------------------------------


def test_identity_tier_is_failfast_with_observe_not_enforce():
    """DEPLOY_ENFORCE_IDENTITY=true 与平台同档；TENANT_JWT_ENFORCE 显式留 false。

    enforce 档不在这里顺带打开：/ready **不在** IdentityMiddleware 的 skip 面里
    （skip 只有 /health、/metrics、/docs 等），kubelet 的探测不带凭据 ⇒ 打开它会把
    Pod 打成永远 NotReady。这条不是"配错了"，是该档需要先安排探针——写进清单注释与用例，
    免得下一个人把 env 与探针当成两件不相干的事改。
    """
    env = {e["name"]: e.get("value") for e in _env_items(_container())}
    assert env.get("DEPLOY_ENFORCE_IDENTITY") == "true"
    assert env.get("TENANT_JWT_ENFORCE") == "false", "enforce 档属另一决策（且要先解决 /ready 被 401）"
    _assert_ready_is_not_skipped()


def test_single_tenant_matches_the_meta_job_write_scope():
    """30 的断言租户 == 36 的写入租户。

    不一致的形状是"元知识灌成功、召回恒空"：build 侧按 settings.default_tenant 写行，
    在线按服务端断言过滤，两侧不同号时没有任何探针会红（36 头部的 ⚠ 就是这条）。
    """
    env = {e["name"]: e.get("value") for e in _env_items(_container())}
    job_env = {e["name"]: e.get("value") for e in _env_items(_meta_job_container())}
    assert env.get("SINGLE_TENANT"), "30 未声明 SINGLE_TENANT"
    assert env["SINGLE_TENANT"] == job_env.get("DEFAULT_TENANT"), (
        f"30 SINGLE_TENANT={env['SINGLE_TENANT']!r} != 36 DEFAULT_TENANT={job_env.get('DEFAULT_TENANT')!r}"
        "：元知识写 A 读 B，召不回且不报错"
    )


@pytest.mark.parametrize("path", (_PLATFORM, _SERVICE), ids=("20 签发侧", "30 验签侧"))
def test_hmac_key_is_a_projected_secret_file_not_an_env_value(path):
    """两侧都是**文件**型密钥（load_hmac_key 只读 INTERNAL_HMAC_KEY_FILE，不读 env 值）。

    20（agent_server）是签发侧、30（nl2sql-service）是验签侧，两侧靠同一套判据跑：
    只在问数服务那边把门禁钉好，等于平台那边“改坏没人拦”。

    判据按六件事逐个查，缺一件就是"看着挂了、其实读不到/读多了"：
    env 指向的路径 = 挂载点 + 投影出的文件名；卷只投一个键；来源是集群自有对象；
    模式 0440 + fsGroup；挂载路径不遮 SA token；密钥不落在入库的 demo Secret 里
    （一把能签"合法租户"的对称键进仓库 = 人人可跨租户写元知识）。
    """
    pod, ctr = _workload_pod_and_container(path)
    _assert_hmac_volume(pod, ctr)
    repo_object, repo_keys = _secret_objects_in_repo()
    key = _hmac_shape(pod, ctr)["secret_key"]
    assert key not in repo_keys, f"{key} 出现在入库 Secret {repo_object} 里：真实签名密钥永不入库"


def _assert_same_hmac_shape(sign: dict[str, object], verify: dict[str, object]) -> None:
    diff = {k: (sign.get(k), verify.get(k)) for k in sign if sign.get(k) != verify.get(k)}
    assert not diff, (
        f"签发侧(20) 与验签侧(30) 的密钥形状分叉 {diff}：表现是 /sql/train 全线 401 "
        "而两侧探针全绿（验不过不会让任何一边报错）"
    )
    assert sign["fs_group"], (
        "0440 必须搭 Pod fsGroup（实测：无 fsGroup 时卷内文件 root:root，uid 10001 读不到）"
    )


def test_signing_and_verifying_sides_share_one_key_shape():
    """20 签的头由 30 验：六件事实逐件对齐，分叉任一件都是“401 但处处全绿”。"""
    plat_pod, plat_ctr = _workload_pod_and_container(_PLATFORM)
    svc_pod, svc_ctr = _workload_pod_and_container(_SERVICE)
    _assert_same_hmac_shape(_hmac_shape(plat_pod, plat_ctr), _hmac_shape(svc_pod, svc_ctr))


# ---------------------------------------------------------------------------
# ⑥ 权重缓存与凭据引用
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", (_PLATFORM, _SERVICE, _META_JOB), ids=("20", "30", "36"))
def test_hf_home_literal_is_the_same_in_every_workload(path):
    """三处 HF_HOME 字面值必须逐字相同，且都被 hostPath(type: Directory) 覆盖。

    写成 CM 键反而会更脆：平台那份 CM 的 EMBEDDING_* 是另一个消费方的口径，
    而这里的判据只是"同一个挂载点别写三种拼法"。指到没缓存的目录时，服务不是报错而是
    回连 huggingface.co（集群无外网 ⇒ 表现成"Pod 活着但一直不 Ready"）。
    """
    docs = _docs(path)
    workload = next(d for d in docs if d["kind"] in ("Deployment", "Job"))
    pod = workload["spec"]["template"]["spec"]
    ctr = pod["containers"][0]
    env = {e["name"]: e.get("value") for e in _env_items(ctr)}
    hf_home = env.get("HF_HOME")
    assert hf_home, f"{path.name} 未声明 HF_HOME"
    assert env.get("HF_HUB_OFFLINE") == "1" and env.get("TRANSFORMERS_OFFLINE") == "1", (
        f"{path.name} 少了离线两键 ⇒ 首次加载回连 huggingface.co"
    )
    mounts = {m["name"]: m for m in ctr.get("volumeMounts", [])}
    covered = [
        m for m in mounts.values()
        if hf_home == m["mountPath"] or hf_home.startswith(m["mountPath"].rstrip("/") + "/")
    ]
    assert covered, f"{path.name} 的 HF_HOME={hf_home} 不在任何挂载下（缓存在宿主、Pod 里是空的）"
    volumes = {v["name"]: v for v in pod.get("volumes", [])}
    for m in covered:
        host_path = volumes[m["name"]].get("hostPath")
        assert host_path and host_path.get("type") == "Directory", (
            f"{path.name} 的权重缓存卷没写 type: Directory：缓存不在本节点时不报调度失败，"
            "而是起来后静默回连外网（126 三节点各自独立盘）"
        )
    assert hf_home == "/opt/ap-models/hf-cache", f"HF_HOME 写成 {hf_home!r}：与另两处字面值分叉"


def test_secret_refs_are_either_in_repo_object_or_cluster_owned():
    """引用不存在的键 = Pod 起不来且常被误读成"镜像坏了"；来源没交代 = 无法审计。"""
    repo_object, repo_keys = _secret_objects_in_repo()
    for e in _env_items(_container()):
        ref = (e.get("valueFrom") or {}).get("secretKeyRef")
        if not ref:
            continue
        name, key = ref["name"], ref["key"]
        if name == repo_object:
            assert key in repo_keys, f"{name}/{key} 在入库 Secret 里没有这个键"
        else:
            assert name in _CLUSTER_OWNED_SECRET_OBJECTS, f"引用了未交代来源的 Secret 对象 {name}"
            assert key in _CLUSTER_OWNED_SECRET_KEYS, f"{name}/{key} 不在集群自有键清单内"
            assert key not in repo_keys, f"{key} 同时住在两个对象里，来源分叉"
        assert ref.get("optional") is not True, f"{key} 被标 optional 即允许静默缺凭据"


# ---------------------------------------------------------------------------
# ⑦ 清单写了 = 应用读到（整张 env 面走一遍真解析）
# ---------------------------------------------------------------------------


def test_manifest_env_actually_lands_in_settings(monkeypatch, tmp_path):
    """把 30 的 env 按清单语义注满，实走一遍 ``get_settings()``。

    为何不只看清单：本包有个真实的优先级陷阱——``get_settings`` 把 app_config.yaml 的值
    作为 init kwargs 传给 Settings，而 pydantic-settings 里 init kwargs 优先级**高于 env**
    （Q18 的根因：真部署的 embedding 维度/模型二义）。现在的解法是“env 已提供的字段
    从 YAML override 里剔除”，但那是一段逻辑，不是一个保证——env 名写错、JSON 形状写错、
    剔除逻辑退场时，清单依旧 apply 成功、Pod 依旧 Ready，只是读到了镜像里那份
    app_config.yaml 的陈旧值（1024 维、bge-m3 那一路）。本用例就是钉“读到的 = 写的”。

    cwd 换成空目录：Settings 的 ``env_file=".env"`` 是 CWD 相对的，容器里没这份文件，
    仓根有——不隔离就会把本机 .env 当成"env 已提供"，测的不是容器里那条路径。
    """
    from nl2sql_service.conf import settings as settings_module

    values = _manifest_env_values()
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    monkeypatch.chdir(tmp_path)
    settings_module.get_settings.cache_clear()
    try:
        s = settings_module.get_settings()
        cm = _configmap()["data"]
        assert s.vector_dim == int(cm["NL2SQL_VECTOR_DIM"]), "向量维度不是清单值（被镜像里的 YAML 盖了）"
        assert s.embedding_backend == cm["NL2SQL_EMBEDDING_BACKEND"]
        assert s.embedding_model == cm["NL2SQL_EMBEDDING_MODEL"]
        assert s.tokenizer == cm["NL2SQL_TOKENIZER"]
        assert s.datasource_id == cm["NL2SQL_DATASOURCE_ID"]
        assert s.allowed_tables == json.loads(cm["NL2SQL_ALLOWED_TABLES"]), (
            "L2 白名单不是清单值——空清单在运行面看不出来，只是不再拒外表"
        )
        assert s.sensitive_columns == json.loads(cm["NL2SQL_SENSITIVE_COLUMNS"])
        assert s.result_masking_enabled is True
        assert s.default_query_role == cm["NL2SQL_DEFAULT_QUERY_ROLE"]
        # LLM 两键引平台 CM：问数侧读到的必须是同一条模型（现网换 rev 只改 00-config 一处）
        assert s.llm_model == cm["LLM_MODEL"]
        assert s.llm_base_url == cm["LLM_BASE_URL"]
        assert s.meta_db_dsn and s.dw_db_dsn
    finally:
        settings_module.get_settings.cache_clear()


def _manifest_env_values() -> dict[str, str]:
    """把 30 的 env 解析成“容器里真会看到的那些字符串”。

    CM 引用取 00-config 的字面值；Secret 引用取 05-secrets 的 demo 值（入库的就是 demo），
    集群自有对象的键用占位串——本用例只验“能不能读到”，不验凭据内容。
    """
    cm = _configmap()["data"]
    _repo_object, repo_values = _secret_objects_in_repo()
    out: dict[str, str] = {}
    for e in _env_items(_container()):
        if "value" in e:
            out[e["name"]] = str(e["value"])
            continue
        ref = e["valueFrom"]
        if "configMapKeyRef" in ref:
            out[e["name"]] = cm[ref["configMapKeyRef"]["key"]]
        else:
            out[e["name"]] = repo_values.get(ref["secretKeyRef"]["key"], "占位不入密")
    return out


# ---------------------------------------------------------------------------
# ⑧ 非空洞性：每条判据都要吃得到它想拦的形状
# ---------------------------------------------------------------------------


def test_gates_bite_on_the_shapes_they_reject():
    import copy

    ctr = _container()

    # (a) 注了平台侧的 OTEL 名：内核读不到，观测面静默 DISABLED
    bad = copy.deepcopy(ctr)
    bad["env"].append({"name": "OTEL_ENDPOINT", "value": "http://x/v1/traces"})
    with pytest.raises(AssertionError, match="平台自定义的 OTEL env 名"):
        _assert_observability_env(bad)

    # (b) 把 liveness 并进 /ready：库断了重启进程
    bad2 = copy.deepcopy(ctr)
    bad2["livenessProbe"]["httpGet"]["path"] = "/ready"
    with pytest.raises(AssertionError, match="liveness"):
        _assert_probe_split(bad2)

    # (c) readiness timeout 回到默认 1s（比服务侧 3s 预算短）
    bad3 = copy.deepcopy(ctr)
    bad3["readinessProbe"]["timeoutSeconds"] = 1
    with pytest.raises(AssertionError, match="不大于服务侧预算"):
        _assert_readiness_timeout(bad3)

    # (d) 36 改回字面值：与 30 的 CM 引用分叉
    docs = copy.deepcopy(_docs(_META_JOB))
    for e in docs[0]["spec"]["template"]["spec"]["containers"][0]["env"]:
        if e["name"] == "VECTOR_DIM":
            e.pop("valueFrom")
            e["value"] = "1024"
    with pytest.raises(AssertionError, match="不是 configMapKeyRef"):
        _assert_same_shared_key(docs[0]["spec"]["template"]["spec"]["containers"][0], ctr, "VECTOR_DIM")

    # (e) List[str] 用逗号串（本机实测：SettingsError ⇒ CrashLoop）
    cm_name = next(d for d in _docs(_CONFIG) if d["kind"] == "ConfigMap")
    bad_cm = copy.deepcopy(cm_name)
    bad_cm["data"]["NL2SQL_ALLOWED_TABLES"] = "users,orders"
    with pytest.raises(json.JSONDecodeError):
        _assert_list_json(bad_cm, "ALLOWED_TABLES")

    # (f) 白名单与 fixture 分叉（多写一张库里没有的表）
    bad_cm2 = copy.deepcopy(cm_name)
    bad_cm2["data"]["NL2SQL_ALLOWED_TABLES"] = '["users", "orders", "refunds"]'
    with pytest.raises(AssertionError, match="不一致"):
        _assert_tables_match_fixture(bad_cm2)

    # (g) 密钥卷挂了整个 Secret 对象（多塞 API_KEY/LANGFUSE_* 进这个 Pod）
    bad4 = copy.deepcopy(_pod_spec())
    for vol in bad4["volumes"]:
        if "secret" in vol:
            vol["secret"].pop("items")
    with pytest.raises(AssertionError, match="只投"):
        _assert_hmac_volume(bad4, ctr)

    # (h) LANGFUSE 死键注回来了
    bad5 = copy.deepcopy(ctr)
    bad5["env"].append({"name": "LANGFUSE_HOST", "value": "http://x:3000"})
    with pytest.raises(AssertionError, match="死键"):
        _assert_no_forbidden_env(bad5)

    # (i) 运维把 /ready 加进了 skip 面（或装配点开始传自定义）："enforce 档不必先改探针"的
    #     前提当场作废，不拦就会在翻档那天得到一批 NotReady 的 Pod
    with pytest.raises(AssertionError, match="skip"):
        _assert_ready_is_not_skipped(skip=("/health", "/ready"))
    with pytest.raises(AssertionError, match="装配"):
        _assert_ready_is_not_skipped(assembly_src="app.add_middleware(IdentityMiddleware, skip_paths=())")

    # (j) 密钥卷改挂 /run/secrets（连带把 env 路径改对，绕过“路径要等于挂载点”那条）：
    #     清单看起来完全合法，但 Pod 永远起不来（SA token EROFS）
    bad6 = copy.deepcopy(_pod_spec())
    ctr6 = bad6["containers"][0]
    for m in ctr6["volumeMounts"]:
        if m["name"] in _secret_volumes(bad6):
            m["mountPath"] = "/run/secrets"
    for e in ctr6["env"]:
        if e["name"] == "INTERNAL_HMAC_KEY_FILE":
            e["value"] = "/run/secrets/internal_hmac.key"
    with pytest.raises(AssertionError, match="EROFS"):
        _assert_hmac_volume(bad6, ctr6)

    # (k) 只写了 0440 而删掉 Pod fsGroup：密钥在位但进程读不到 ⇒ 401 而处处全绿
    bad7 = copy.deepcopy(_pod_spec())
    bad7["securityContext"].pop("fsGroup")
    with pytest.raises(AssertionError, match="fsGroup"):
        _assert_hmac_volume(bad7, bad7["containers"][0])

    # (l) 只改一侧的密钥路径（“发了 PR 但两侧不一致”的形态）⇒ 跨清单比对要红
    plat_pod, plat_ctr = _workload_pod_and_container(_PLATFORM)
    shape = _hmac_shape(plat_pod, plat_ctr)
    with pytest.raises(AssertionError, match="分叉"):
        _assert_same_hmac_shape(shape, {**shape, "key_file": "/run/app-secrets/other"})


# --- 判据本体（用例与上面的反证共用同一份实现，避免"反证跑的是另一套代码"）---


def _assert_no_forbidden_env(ctr: dict) -> None:
    leaked = sorted(_env_names(ctr) & _FORBIDDEN_ENV)
    assert not leaked, (
        f"30 注入了 {leaked}：本镜像没装 [langfuse] extra、本包也没有 get_langfuse_callbacks 调用点"
        "⇒ 全是死键。要让 nl2sql 的 LLM 调用进 Langfuse，先在本包接回调（批次 1 已登记为观测缺口）。"
    )


def _assert_observability_env(ctr: dict) -> None:
    injected = _env_names(ctr) & _PLATFORM_ONLY_OTEL
    assert not injected, f"30 注入了平台自定义的 OTEL env 名 {sorted(injected)}（nl2sql 侧无读取点）"
    assert _cm_ref("AGENT_CORE_TRACE_ENABLED", ctr) == ("agent-platform-config", "OTEL_ENABLED")
    assert _cm_ref("OTEL_EXPORTER_OTLP_ENDPOINT", ctr) == ("agent-platform-config", "OTEL_ENDPOINT")


def _assert_probe_split(ctr: dict) -> None:
    assert ctr["startupProbe"]["httpGet"]["path"] == "/ready"
    assert ctr["readinessProbe"]["httpGet"]["path"] == "/ready"
    assert ctr["livenessProbe"]["httpGet"]["path"] == "/health", (
        "liveness 不许探 /ready：库不可达该摘流量，不该重启进程"
    )


def _assert_readiness_timeout(ctr: dict) -> None:
    from nl2sql_service.api.server import _READY_PROBE_TIMEOUT_S

    timeout = ctr["readinessProbe"].get("timeoutSeconds", 1)
    assert timeout > _READY_PROBE_TIMEOUT_S, (
        f"readiness timeoutSeconds={timeout} 不大于服务侧预算 {_READY_PROBE_TIMEOUT_S}s ⇒ 误判失败"
    )


def _assert_same_shared_key(job_ctr: dict, svc_ctr: dict, env_name: str) -> None:
    assert _cm_ref(env_name, job_ctr) == _cm_ref(env_name, svc_ctr), (
        f"{env_name} 在 30 与 36 引用了不同的 CM 键（单源被破）"
    )


def _assert_list_json(cm: dict, env_name: str) -> None:
    raw = cm["data"][f"NL2SQL_{env_name}"]
    parsed = json.loads(raw)
    assert isinstance(parsed, list) and all(isinstance(x, str) for x in parsed), (
        f"NL2SQL_{env_name} 必须是字符串数组的 JSON 字面量，实际 {raw!r}"
    )


def _assert_tables_match_fixture(cm: dict) -> None:
    fixture = (_ROOT / "deploy" / "data" / "nl2sql_dw_fixture.sql").read_text(encoding="utf-8")
    created = set(re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", fixture))
    declared = set(json.loads(cm["data"]["NL2SQL_ALLOWED_TABLES"]))
    assert created == declared, f"ALLOWED_TABLES={sorted(declared)} 与 fixture 建的表 {sorted(created)} 不一致"


def _assert_hmac_volume(pod: dict, ctr: dict) -> None:
    env = {e["name"]: e.get("value") for e in _env_items(ctr)}
    key_path = env.get("INTERNAL_HMAC_KEY_FILE")
    assert key_path, "未声明 INTERNAL_HMAC_KEY_FILE ⇒ /sql/train 的签名头永远验不过（401），而 /ready 全绿"
    assert _secret_volumes(pod), "Pod 没有任何 Secret 卷，INTERNAL_HMAC_KEY_FILE 指向的是不存在的路径"
    hit = _secret_mount_for(pod, ctr, str(key_path))
    assert hit, f"{key_path} 不在任何 Secret 卷的挂载点下"
    mount, vol = hit
    assert mount.get("readOnly"), "密钥卷必须只读"
    assert vol["secretName"] in _CLUSTER_OWNED_SECRET_OBJECTS, (
        f"密钥来自 {vol['secretName']!r}：真实密钥应在集群自有的 observability-keys，不在入库的 demo Secret"
    )
    items = vol.get("items") or []
    assert len(items) == 1 and items[0]["key"] == "INTERNAL_HMAC_KEY", (
        f"应只投 INTERNAL_HMAC_KEY 一个键，实际 {items}（整对象挂进去会把 API_KEY/LANGFUSE_* 也塞进这个 Pod）"
    )
    assert key_path.endswith(items[0]["path"]), f"env 指向 {key_path}，投影出的文件名是 {items[0]['path']}"
    assert vol.get("defaultMode") in (0o440, 440), (
        "defaultMode 需 0440：0400 是 root 独占（uid 10001 读不到），0644 是任何进程可读"
    )
    # 0440 能成立的前提是 fsGroup 把卷内文件的组改成 10001（本集群实跑：有 fsGroup → 0:10001 可读，
    # 无 fsGroup → 0:0 且 0440 不可读）。两件只写一件 = 密钥在位而进程读不到：/ready 全绿、
    # /sql/train 401（无密钥 ⇒ 拒发），运维只会去看服务日志。所以成对检查，不放行“只改了 mode”。
    assert (pod.get("securityContext") or {}).get("fsGroup") == 10001, (
        f"密钥卷依赖 Pod fsGroup=10001，实际 {pod.get('securityContext')!r}：0440 + 无 fsGroup 读不到"
    )
    # 挂载路径遮不遮 SA token：不遮不报错，遮了直接起不来（见 _SA_TOKEN_SHADOW_PATHS 的实测注录）。
    shadowed = sorted({p for p in _SA_TOKEN_SHADOW_PATHS if Path(mount["mountPath"]) == Path(p)})
    assert not shadowed, (
        f"Secret 卷挂在 {shadowed}：那是 kubelet 挂 SA token 的目录，只读 tmpfs 先占住后"
        " runc 建 kubernetes.io 子目录就是 EROFS ⇒ 容器永远创建不成功"
        "（2026-10-28 在 126 实跑重现，改用 /run/app-secrets）"
    )


def _assert_ready_is_not_skipped(
    skip: tuple[str, ...] | None = None,
    assembly_src: str | None = None,
) -> None:
    """TENANT_JWT_ENFORCE 留 observe 的前提：/ready 现在是要凭据的。

    skip 面从代码取（中间件形参默认值），不在用例里抄第二份名单；同时要求装配点
    **没有**传自定义 skip_paths——否则默认值就不是生效的那一份，判据得改成读装配实参。
    """
    import inspect

    from agent_runtime.identity_assembly import mount_identity_gate
    from agent_runtime.identity_middleware import IdentityMiddleware

    if skip is None:
        param = inspect.signature(IdentityMiddleware.__init__).parameters.get("skip_paths")
        assert param is not None and param.default is not inspect.Parameter.empty, (
            "IdentityMiddleware 的 skip 面不再是形参默认值（改成硬编码/新旋钮了？）："
            "本用例的引用通道断了，要跟着改成读真正的生效值"
        )
        skip = param.default
    if assembly_src is None:
        assembly_src = inspect.getsource(mount_identity_gate)
    assert "/ready" not in skip, (
        f"/ready 现在在 skip 面里（{skip}）：清单注释与本用例的前提要一起改——"
        "翻 enforce 不再会把 Pod 打成 NotReady，那 TENANT_JWT_ENFORCE 的取舍要重拍"
    )
    assert "skip_paths" not in assembly_src, (
        "mount_identity_gate 开始传自定义 skip_paths：默认值不再是生效的那份，"
        "本用例的判据要改成从装配实参取（否则它验的是一个没人用的名单）"
    )
