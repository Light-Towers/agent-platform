r"""批次 2 数据面（35/36 两个 Job + deploy/data 脚本）的静态门禁。

为什么这一组要有用例：数据面的失败形状全是"apply 时不报错、跑起来才空转"——
文件名拼错、`\gset` 取不到的变量、被 psql 忽略的退出码、元库写进 '' 租户而在线按
'default' 召回。这些都是本批在 126 的 ap-iso-pg 上真撞过的形状，撞一次钉一条。

与 test_k8s_manifest_wiring.py 的分工：那份守平台 Deployment 的 env/探针/密钥，
本份守两个一次性 Job 的**脚本可重放性**（顺序、fail-closed 真非零、引用文件存在）。
30-nl2sql-service.yaml 接线后在这里补跨清单的模型四键一致性（36 写向量、30 读向量）。
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[2]
_K8S = _ROOT / "deploy" / "k8s"
_DATA = _ROOT / "deploy" / "data"
_DBSQL_JOB = _K8S / "35-nl2sql-dbsql-job.yaml"
_META_JOB = _K8S / "36-nl2sql-meta-init-job.yaml"
_PLATFORM = _K8S / "20-agent-platform.yaml"


def _docs(path: Path) -> list[dict]:
    return [d for d in yaml.safe_load_all(path.read_text(encoding="utf-8")) if d]


def _job(path: Path) -> dict:
    """一次性 Job 对象，顺带把"这个 Job 敢在消费集群上重跑"的几个前提钉住。"""
    docs = _docs(path)
    assert [d["kind"] for d in docs] == ["Job"], f"{path.name} 应只含 Job：{[d['kind'] for d in docs]}"
    job = docs[0]
    spec = job["spec"]["template"]["spec"]
    assert spec["restartPolicy"] == "Never", f"{path.name} 是 Job，restartPolicy 必须 Never"
    # Job 日志是取证材料（L1 负例、vector extversion、schema 状态读数都在里面）：
    # 没有 ttl 就永久堆 Pod，运维第一件事是整体删掉 namespace 里的"垃圾"，取证跟着没
    assert job["spec"].get("ttlSecondsAfterFinished"), f"{path.name} 未设 ttlSecondsAfterFinished"
    assert "backoffLimit" in job["spec"], f"{path.name} 未显式 backoffLimit（默认 6 会把失败刷成噪声）"
    return job


def _job_container(path: Path) -> dict:
    ctrs = _job(path)["spec"]["template"]["spec"]["containers"]
    assert len(ctrs) == 1, f"{path.name} 期望单容器（多容器就要交代先后契约）"
    return ctrs[0]


def _script(path: Path) -> str:
    """Job 里那段 shell（args[0]）。所有形状判据都读它，不读注释。"""
    ctr = _job_container(path)
    assert ctr["command"][:2] in (["/bin/bash", "-euo"], ["/bin/sh", "-eu"]), (
        f"{path.name} 未用 -eu：脚本里任一步失败会继续往下跑，最后 exit 0"
    )
    return "\n".join(ctr["args"])


def _env_names(path: Path) -> set[str]:
    return {e["name"] for e in _job_container(path)["env"]}


def _env_values(path: Path) -> dict[str, str]:
    return {e["name"]: e["value"] for e in _job_container(path)["env"] if "value" in e}


def _deployment_env_values(path: Path) -> dict[str, str | None]:
    """平台 Deployment 的字面 env（只用于跟 Job 做跨清单一致性对账）。"""
    hits = [d for d in _docs(path) if d["kind"] == "Deployment"]
    assert len(hits) == 1, f"{path.name} 应恰有一个 Deployment：{[d['kind'] for d in _docs(path)]}"
    ctrs = hits[0]["spec"]["template"]["spec"]["containers"]
    return {e["name"]: e.get("value") for e in ctrs[0]["env"]}


# ---------------------------------------------------------------------------
# ① 引用的数据文件必须真的在仓里（ConfigMap 由 deploy/data 整体生成，拼错名字是运行期才炸）
# ---------------------------------------------------------------------------


def test_jobs_reference_existing_data_files():
    covered: set[str] = set()
    for path in (_DBSQL_JOB, _META_JOB):
        refs = set(re.findall(r"\$AP_DATA_DIR/([A-Za-z0-9_.-]+)", _script(path)))
        assert refs, f"{path.name} 没引用任何 $AP_DATA_DIR 文件（数据面单一真相源被绕开了？）"
        missing = sorted(r for r in refs if not (_DATA / r).is_file())
        assert not missing, f"{path.name} 引用了 deploy/data 里不存在的文件：{missing}"
        covered |= refs
    # 反向：deploy/data 里每个文件都要被某个 Job 用到，否则就是"仓里有但没上库"的第二份真相
    orphan = sorted(p.name for p in _DATA.iterdir() if p.is_file() and p.name not in covered)
    assert not orphan, f"deploy/data 里这些文件没被任何 Job 应用（孤儿真相源）：{orphan}"


def test_data_mount_is_the_readonly_configmap():
    """两个 Job 的 $AP_DATA_DIR 必须就是 ConfigMap nl2sql-data 且只读。

    判据不写死路径，从 env 里取 AP_DATA_DIR：路径写两处而只改一处时，本文件①会因
    "引用文件存在" 继续绿，Job 却在运行期找不到文件。
    """
    for path in (_DBSQL_JOB, _META_JOB):
        pod = _job(path)["spec"]["template"]["spec"]
        volumes = {v["name"]: v for v in pod["volumes"]}
        mounts = {m["name"]: m for m in _job_container(path).get("volumeMounts", [])}
        assert all(m.get("readOnly") for m in mounts.values()), f"{path.name} 存在可写挂载"
        data_dir = _env_values(path)["AP_DATA_DIR"]
        data = [m for m in mounts.values() if m["mountPath"] == data_dir]
        assert len(data) == 1, f"{path.name} 没把 AP_DATA_DIR={data_dir} 挂进来"
        cm = volumes[data[0]["name"]].get("configMap", {}).get("name")
        assert cm == "nl2sql-data", (
            f"{path.name} 的数据卷来源是 {cm!r}，不是 ConfigMap nl2sql-data"
            "（内容必须来自仓根 deploy/data，不在清单里内联副本）"
        )


def test_meta_job_model_cache_is_hostpath_directory():
    """只有 36 跑 embedder，所以要权重缓存；hostPath 必须写 type: Directory。

    不写 type 的形态是：缓存不在 Pod 落到的那个节点也不报错，起来后首次加载才去
    回连 huggingface.co（集群无外网 ⇒ 挂在探测超时里）。126 三节点各自独立盘，
    跟 20-agent-platform 同一前提。
    """
    pod = _job(_META_JOB)["spec"]["template"]["spec"]
    volumes = {v["name"]: v for v in pod["volumes"]}
    mounts = {m["name"]: m for m in _job_container(_META_JOB).get("volumeMounts", [])}
    hf_home = _env_values(_META_JOB)["HF_HOME"]
    covered = [m for m in mounts.values() if hf_home == m["mountPath"] or hf_home.startswith(m["mountPath"].rstrip("/") + "/")]
    assert covered, f"HF_HOME={hf_home} 不在任何挂载下 ⇒ 缓存只在宿主，Pod 里是空的"
    for m in covered:
        host_path = volumes[m["name"]].get("hostPath")
        assert host_path and host_path.get("type") == "Directory", (
            f"{m['name']} 的 hostPath 未声明 type: Directory（缓存在不在都要响亮失败）"
        )
    # 35 不跑 python，给它挂模型卷只是多一个读写面
    dbsql_mounts = {m["name"] for m in _job_container(_DBSQL_JOB).get("volumeMounts", [])}
    assert dbsql_mounts == {"nl2sql-data"}, f"35 Job 出现预期外的挂载：{sorted(dbsql_mounts)}"


# ---------------------------------------------------------------------------
# ② psql 的连接形状：`psql "<URL>" -d <db>` 在 psql 16 会把整条 URL 当用户名（实测）
# ---------------------------------------------------------------------------


def _psql_url_dash_d_lines(script: str) -> list[str]:
    r"""返回 `psql "<URL变量>" … -d <db>` 的混写行。

    psql 的连接目标只有一个参数位：给 URL 又给 -d，psql 16 实测把整条 URL 当用户名
    ⇒ `FATAL: role "postgresql://…" does not exist`。要连别的库就换 URL 的库名段。
    """
    out = []
    for line in script.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or "psql" not in stripped:
            continue
        if re.search(r"""psql\s+"?\$\{?[A-Za-z_]\w*""", stripped) and re.search(r"\s-d\s", stripped):
            out.append(stripped)
    return out


def test_dbsql_job_does_not_mix_url_and_dash_d():
    bad = _psql_url_dash_d_lines(_script(_DBSQL_JOB))
    assert not bad, (
        '35 Job 出现 `psql "<URL>" -d <db>` 混写（psql 会把 URL 当用户名）：'
        f"应换库名段 ${{DATABASE_URL%/*}}/<db>。违规行：{bad}"
    )


def test_dbsql_job_rejects_query_string_in_admin_url():
    """换库名靠字符串裁剪，带 `?sslmode=…` 会被静默丢掉（连上不加密也不报错）⇒ 必须先拦住。"""
    script = _script(_DBSQL_JOB)
    assert "*\\?*" in script, "35 Job 未对 DATABASE_URL 的查询参数做 fail-closed"
    assert "exit 1" in script, "35 Job 的查询参数检查没有真正退出"


# ---------------------------------------------------------------------------
# ③ fail-closed 必须靠 RAISE EXCEPTION：psql 16 的 `\quit 2` 参数被忽略且以 0 退出（实测）
# ---------------------------------------------------------------------------


def _quit_lines(text: str) -> list[str]:
    r"""返回非注释行里用 `\quit` 做 fail-closed 的位置。

    psql 16 实测：`\quit 2` 报 `warning: \quit: extra argument "2" ignored`，
    FATAL 打印完仍以 **0** 退出 ⇒ Job 判成功。注释里提 `\quit` 是要说清为什么不用它，不算违规。
    """
    offenders = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("--"):
            continue
        if re.match(r"\\quit\b", stripped):
            offenders.append(f"{lineno}: {stripped}")
    return offenders


def test_data_scripts_never_use_quit_for_fail_closed():
    offenders = []
    for sql in sorted(_DATA.glob("*.sql")):
        offenders.extend(f"{sql.name}:{item}" for item in _quit_lines(sql.read_text(encoding="utf-8")))
    assert not offenders, (
        r"deploy/data 用 \quit 做 fail-closed（psql 16 忽略其参数并以 0 退出 ⇒ 假绿）："
        f"{offenders}"
    )


def test_data_scripts_fail_closed_raises():
    r"""每条断言都得是能被 ON_ERROR_STOP 抓住的真错误，而不是一句 \echo。"""
    total = 0
    for sql in sorted(_DATA.glob("*.sql")):
        text = sql.read_text(encoding="utf-8")
        total += text.count("RAISE EXCEPTION")
        if "\\if" in text:
            assert "\\set ON_ERROR_STOP on" in text, f"{sql.name} 有 \\if 分支却没开 ON_ERROR_STOP"
    assert total >= 4, f"deploy/data 的 fail-closed RAISE 少于 4 条（{total}）：断言 1/2/3 + vector 在位"


def _unguarded_gset_sources(text: str, prefix: str) -> list[str]:
    r"""返回喂给 `\gset <prefix>_` 却没包 coalesce 的表达式行（NULL ⇒ 变量直接不存在）。"""
    block = text.split(f"\\gset {prefix}")[0]
    return [
        line.strip()
        for line in block.splitlines()
        if "regexp_match(" in line and "coalesce(" not in line and not line.strip().startswith("--")
    ]


def test_dbsql_variables_are_coalesced_at_generation():
    r"""`\gset` 跳过 NULL 列 ⇒ 未定义变量在 `:'x'` 处炸成 syntax error（真因被掩盖）。

    判据取生成侧：dbsql 里每个喂给 \gset ap_ 的 regexp_match 都必须包在 coalesce 里。
    """
    text = (_DATA / "nl2sql_dbsql.sql").read_text(encoding="utf-8")
    bare = _unguarded_gset_sources(text, "ap_")
    assert not bare, f"nl2sql_dbsql.sql 里这些 \\gset 源表达式没包 coalesce（NULL 会让变量消失）：{bare}"


# ---------------------------------------------------------------------------
# ③′ 非空洞性：三个判据函数都吃得到当年的坏形状（不靠改文件验证）
# ---------------------------------------------------------------------------


def test_shape_detectors_bite_on_the_shapes_they_replace():
    # (a) 返修前的 psql 调用（真炸过：role "postgresql://…" does not exist）
    old_job_line = 'psql "$DATABASE_URL" -d nl2sql_meta -v ON_ERROR_STOP=1 -c "CREATE EXTENSION"'
    assert _psql_url_dash_d_lines(old_job_line) == [old_job_line]
    # 返修后的两个形状不能误报
    for ok_line in (
        'psql "$META_ADMIN_URL" -v ON_ERROR_STOP=1 -c "CREATE EXTENSION IF NOT EXISTS vector"',
        'psql "$META_DB_DSN" -v ON_ERROR_STOP=1 -f "$AP_DATA_DIR/nl2sql_meta_grants.sql"',
        "# psql \"$DATABASE_URL\" -d nl2sql_dw …（注释不算违规）",
    ):
        assert not _psql_url_dash_d_lines(ok_line), ok_line

    # (b) 返修前的 fail-closed（打印 FATAL 后以 0 退出）
    old_quit_block = "\\if :dbname_bad\n\\echo 'FATAL'\n\\quit 2\n\\endif"
    assert _quit_lines(old_quit_block) == ["3: \\quit 2"]
    # 注释里提一下不算违规，返修后的 DO 块也不算
    assert not _quit_lines("-- 用 RAISE EXCEPTION 不用 \\quit：psql 16 会忽略其参数")
    assert not _quit_lines("DO $$ BEGIN RAISE EXCEPTION 'x'; END $$;")

    # (c) 返修前的 \gset 源（regexp_match 不匹配 ⇒ 变量消失）
    old_block = "SELECT\n    (regexp_match(:'ap_dw_dsn', '^postgres'))[1] AS dw_user\n\\gset ap_"
    assert len(_unguarded_gset_sources(old_block, "ap_")) == 1
    new_block = "SELECT\n    coalesce((regexp_match(:'ap_dw_dsn', '^postgres'))[1], '') AS dw_user\n\\gset ap_"
    assert not _unguarded_gset_sources(new_block, "ap_")


# ---------------------------------------------------------------------------
# ④ 36 的租户与库权限：写元知识的租户必须等于在线召回的租户
# ---------------------------------------------------------------------------


def test_meta_job_tenant_matches_platform_single_tenant():
    """build_meta_knowledge 用 settings.default_tenant 写行，默认是 ''；
    而服务在 SINGLE_TENANT=default 下按 'default' 过滤 ⇒ 元知识全召不回且没有任何探针变红。
    这条一致性就是那个坑的门禁。"""
    values = _env_values(_META_JOB)
    assert values.get("DEFAULT_TENANT"), "36 Job 未显式 DEFAULT_TENANT（默认 '' 会写进没人查的租户）"
    platform_env = _deployment_env_values(_PLATFORM)
    assert values["DEFAULT_TENANT"] == platform_env.get("SINGLE_TENANT"), (
        f"36 的 DEFAULT_TENANT={values['DEFAULT_TENANT']!r} 与平台 SINGLE_TENANT="
        f"{platform_env.get('SINGLE_TENANT')!r} 不一致：元知识写A读B，召不回且不报错"
    )


def test_meta_job_does_not_receive_dw_credentials():
    """初始化元库只需要元库：把 DW_DB_DSN 注进 36 等于给一次性 Job 发跨库凭据，
    而它一步都不读 dw（dw 的只读边界是 L1，最小权限在这里要能被审计）。"""
    names = _env_names(_META_JOB)
    assert "META_DB_DSN" in names, "36 Job 没注 META_DB_DSN"
    assert "DW_DB_DSN" not in names, "36 Job 拿到了 DW_DB_DSN（它不该连业务库）"


def test_meta_job_status_comes_before_build():
    """`--status` 在读不到 nl2sql_schema_meta 时以非零退出 ⇒ 顺序必须是
    迁移 → 状态读数（vector_dim 记账）→ 构建。反了就是"没验过就灌向量"。"""
    script = _script(_META_JOB)
    idx = {
        name: script.index(name)
        for name in ("init_meta_schema --dsn", "--status", "build_meta_knowledge")
    }
    assert idx["init_meta_schema --dsn"] < idx["--status"] < idx["build_meta_knowledge"], (
        f"36 Job 三步顺序错：{idx}"
    )
    assert script.count("init_meta_schema --dsn") == 2, "36 Job 期望两次 init_meta_schema（迁移 + 状态读数）"


def test_dbsql_job_keeps_the_l1_behavioral_negative():
    """L1 的判据是行为，不是 GRANT 语句：reader 写入必须被库侧拒绝，且拒绝才算过。"""
    script = _script(_DBSQL_JOB)
    assert "_l1_probe" in script, "35 Job 丢了 L1 写路径负例"
    assert re.search(r"if psql .*_l1_probe.*; then", script, re.S), (
        "35 Job 的 L1 负例不是「写得动就失败」的形状"
    )


def test_jobs_run_as_non_root():
    for path in (_DBSQL_JOB, _META_JOB):
        sc = _job_container(path).get("securityContext", {})
        assert sc.get("runAsNonRoot") is True, f"{path.name} 未声明 runAsNonRoot"
        assert sc.get("runAsUser"), f"{path.name} 未显式 runAsUser"
