# 问数上线（批次 6）现网落差与操作判据清单

> **这份文档只管一件事**：把「清单声明的终态」与「集群里此刻的实际状态」之间的落差**实测成可核对的条目**，
> 并把上线动作写成「每条命令后面写清期望读到什么」——读不到期望值就是没生效，不许凭 "apply 退出码 0" 宣称完成。
> 读数格式沿用 `docs/operations/evidence-format.md`（rev / 原样命令 / 读数 + 分母口径 / 未跑与待环境 / 所需依赖），
> 补跑与容器化的操作分层沿用 `docs/operations/testing-playbook.md`。
>
> **写就时的状态**：本文落档那一轮**没有对集群做过任何写操作**——补凭据、构建分发镜像、apply 都属 D2（人定，AI 给证据）。
> §1 的落差读数是 **2026-10-28 用 §2 那组只读命令实取的**；换 rev、换部署或有人手工补键之后**必须复跑 §2 再引这些数**，
> 现网读数不绑当时的 rev 就是过期陈述（`docs/operations/observability-pitfalls.md` 第 3 条硬规矩）。
>
> **为什么不写进 `minimal-release-runbook.md`**：那份是 2026-10-12/13 那轮上线的历史快照，其中「问数环节」的
> `SQL_DSN` / `sql_backend` 描述是**史实**（当时平台确实自己连库执行 SQL）。历史快照不改写、不外引，
> 现行机制看 `docs/adr/0011-two-text2sql-paths-convergence.md` §7.3 与本文。

## 1. 落差清单（2026-10-28 实测，6 项）

| # | 清单声明的终态 | 线上实际（该轮实取） | 什么时候炸、炸成什么形状 |
|---|---|---|---|
| 1 | `30-nl2sql-service.yaml` 的 Deployment + Service，以及 `35` / `36` 两个一次性 Job | LIVE 只有 `agent-platform` + `postgres` 两组 deploy/svc；`30` 从未 apply 过（server-side dry-run 报 `created` 而非 `configured`） | apply `30` 是**新建对象**而不是更新；此前 `/sql/train` 没有对端服务 |
| 2 | ConfigMap `agent-platform-config` 需 9 个 `NL2SQL_*` 键（`00-config.yaml` 声明 18 键 = 9 平台 + 9 `NL2SQL_*`） | **该轮读数一半是错数，2026-10-28 18:38 已复取定性**：“`NL2SQL_*` 零命中”成立（已于 17:4x 用 merge patch 补 9 键闭合）；**“取到 10 个键名 ⇒ 比清单声明多 1 个”不成立**——现 LIVE 与声明**双向差集为空**（18 = 18），且旧 rev `6ac466af` 的 `00-config.yaml` 也只声明 9 键（`NL2SQL_` 命中 0），而 merge patch 不删键 ⇒ 9+9=18，算术上不可能“多 1” | `30` 的 `configMapKeyRef` 指到不存在的键 ⇒ Pod 停在 `CreateContainerConfigError` |
| 3 | Secret `agent-platform-secrets` 需 `META_DB_DSN` / `DW_DB_DSN` | 只有 `DATABASE_URL` / `POSTGRES_PASSWORD` | `30` / `35` / `36` 三个对象全部起不来（都是非 optional 引用） |
| 4 | Secret `observability-keys` 需 `INTERNAL_HMAC_KEY` | 只有 `API_KEY` / `LLM_API_KEY` / `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` | `20`（签发侧）与 `30`（验签侧）都读不到键 ⇒ `/sql/train` 全线 401，而 `/health` 全绿（探针不碰鉴权） |
| 5 | **`20` 自己引用 `agent-platform-secrets/VALKEY_URL`（非 optional）** | 该对象没有这个键 | **本项是首轮汇报漏掉的那条**：直接 apply `20` ⇒ 平台新副本 `CreateContainerConfigError`、`rollout` 卡住，**旧 Pod 继续跑、`/health` 仍绿** ⇒ 现场看起来像"改了没生效" |
| 6 | 镜像 `nl2sql-service:dev`；`15-valkey.yaml` 的 `valkey/valkey-bundle:9.1.2` | 三台的 `k8s.io` 与 moby 库里**都只有** `agent-platform:dev`；`valkey-bundle` 只在 241 / 126 的 **moby** 里，`k8s.io` 三台皆无，125 连 moby 都没有 | apply 即 `ErrImagePull`（可变 tag + `IfNotPresent` 没有本地层可退，是**硬失败**而非静默跑旧码）；两个镜像都一次都没构建/导入过 |

**同轮取到、必须与上表一起引的两条 rev 绑定事实**：线上 `20` 的容器 env **仍含 `SQL_DSN`**，且**不含** `NL2SQL_SERVICE_URL` /
`INTERNAL_HMAC_KEY_FILE` / `CACHE_ENABLED` / `CACHE_BACKEND` / `VALKEY_URL`；`deployment` 注解 `revision=16`、Pod 落在 241。
⇒ 线上跑的仍是批次 1–4 之前的形态，那一轮取的任何 `/health` 读数都不代表清单 apply 之后的行为。

## 2. 取数命令（只读，永不输出值）

上表每一条都可原地复跑。密钥与 DSN **只输出键名/对象名**（`go-template` 取 `.data` 的 key，不 base64 解码）。

```bash
export KUBECONFIG=/etc/kubernetes/admin.conf
NS=agent-platform
k() { kubectl -n $NS "$@"; }

# 落差 1：工作负载在位性（30/35/36 是否已存在）
k get deploy,svc,job -o custom-columns='KIND:.kind,NAME:.metadata.name,READY:.status.readyReplicas' --no-headers

# 落差 2：ConfigMap 键名（不取值）
k get cm agent-platform-config -o jsonpath='{.data}' \
  | python3 -c "import json,sys; print(' '.join(sorted(json.loads(sys.stdin.read()))))"

# 落差 2 的**更强判据**：双向差集为空，而不是“数键数”（18:38 实测两个 comm 皆为空；
# “10 vs 18”那种错就是只数不改导致的）。注意取清单声明的键要连缩进一起匹：
# `grep -oE '^[A-Z0-9_]+:'` 对 00-config 恒不命中（键是 2 空格缩进的），那是常见错写法。
k get cm agent-platform-config -o go-template='{{range $k, $v := .data}}{{$k}}{{"\n"}}{{end}}' | sort -u > /tmp/cm_live.txt
awk '/^  [A-Z][A-Z0-9_]+:/ {print $1}' deploy/k8s/00-config.yaml | tr -d ':' | sort -u > /tmp/cm_decl.txt
comm -3 /tmp/cm_live.txt /tmp/cm_decl.txt     # 空 = 一致；非空则逐键定性（该进清单 / 该删）

# 落差 3 / 4 / 5：两个 Secret 的键名（不取值）
for s in agent-platform-secrets observability-keys; do
  printf '%s: ' "$s"
  k get secret "$s" -o go-template='{{range $k, $v := .data}}{{$k}} {{end}}'; echo
done

# 落差 5 的精确形态：20 声明的 env 名 vs 线上 env 名（差集就是"apply 会改什么"）
k get deploy agent-platform -o jsonpath='{.spec.template.spec.containers[0].env[*].name}{"\n"}'
python3 - <<'PY'
import re, pathlib
tracked = pathlib.Path("deploy/k8s/20-agent-platform.yaml").read_text(encoding="utf-8")
print(sorted(set(re.findall(r"- name: ([A-Z][A-Z0-9_]+)", tracked))))
PY

# 落差 6：镜像在各节点容器库的在位性（逐台跑，只看 ref）
for s in /run/containerd/containerd.sock /run/containerd-k8s/containerd.sock; do
  [ -S "$s" ] && for ns in k8s.io moby; do
    ctr --address "$s" -n "$ns" images ls 2>/dev/null | awk '{print $1}' \
      | grep -E 'nl2sql|agent-platform|valkey' | sort -u | sed "s/^/[$ns] /"
  done
done
docker images --format '{{.Repository}}:{{.Tag}}' | grep -E 'nl2sql|agent-platform|valkey' || echo "(moby 无)"

# rev 绑定：读数必须知道当时跑的是哪版
k get deploy agent-platform -o jsonpath='{.metadata.annotations.deployment\.kubernetes\.io/revision}{"\n"}'
k get pods -l app=agent-platform \
  -o custom-columns='NAME:.metadata.name,NODE:.spec.nodeName,READY:.status.conditions[?(@.type=="Ready")].status' --no-headers
```

## 3. 上线序列与每步判据

> **顺序不能反**（`30` 头部与 `36` 头部同一条契约）：先补键与镜像，再起数据面（`35` → `36`），
> 服务 Ready 之后才动平台（`20`）。反过来的表现是**问数真空窗**——旧路（`SQL_DSN` 直连）已被批次 5 拆掉、
> 新路还没起来，而 `/health` 全绿、只有问数静默不可用。

| 步 | 动作 | 判据（期望读到什么） | 读不到说明什么 |
|---|---|---|---|
| 0 | 复跑 §2 | 落差表逐条与本文一致，或差异已被写明原因 | 有人手工改过线上 ⇒ 先查本仓库的部署记录（`deploy/k8s/VERIFICATION.md`），再怀疑外部改动 |
| 1 | **补键**：`agent-platform-secrets` += `META_DB_DSN`/`DW_DB_DSN`/`VALKEY_URL`；`observability-keys` += `INTERNAL_HMAC_KEY` | ① 键名清单含新键；② **既有键一个不少**（`DATABASE_URL`/`POSTGRES_PASSWORD`/`LLM_API_KEY`/`API_KEY`/`LANGFUSE_*` 仍在）| 用 `kubectl patch secret … --type merge -p '{"stringData":{"K":"V"}}'`。**禁止 `apply`**：apply 是整对象替换，会抹掉同对象其他键——`observability-keys` 里住着 `LLM_API_KEY`，抹掉等于平台连不上模型。判据②就是为这条写的（126 上实证过 merge 后 `LLM_API_KEY` 完好） |
| 2 | **构建**（放 241，不是 126）：`deploy/k8s/scripts/build.sh` | 两个 tag 都在，且镜像内 `/srv/agent-platform/GIT_REV` == 期望 rev（`build.sh` 的 rev 门禁会自己拒不等） | 宿主 checkout 的 rev ≠ 镜像内 rev 是既往实踩；构建在 126 会把同机 KS 的 etcd 打进 `slow fdatasync`（见 `AGENTS.md` 内网环境第 7 条）。**另：241 并不闲——它的 moby 上常驻整套 `lf-*` 观测后端且与 `vda(ROTA=1)` 同盘 ⇒ 守卫不得关**（10-28 实取）。守卫的 `avg10` 是 10 秒级瞬时量，pip 铺大包层天然顶到 70%+ ⇒ 默认“连续 3 次越 60%”会误杀，用脚本自带的 `IO_LIMIT/IO_STRIKES` 旋钮放宽口径（实测 80/6）而不是关守卫。**`build_with_io_guard.sh:65/99` 的 `timeout 1800` 在当前 PyPI 吞吐下不够**（实取：171 项 / 290MB+ 还在飞，单流 45–60 kB/s）⇒ 表观是 `FAIL: 构建未通过`（rc=124）而不是镜像坏了；本轮用 **`/tmp` 副本只改这一个数字**（`diff` 证明只差两行），不改构建机 checkout——改它就是新增一条“线上与仓库漂移”的债；根治要把预算 env 化（登记 `docs/operations/unconfirmed-items.md` D24） |
| 3 | **分发**：`distribute.sh` 显式列 **三台** | 每台 `ctr -n k8s.io images ls` 都能查到 `agent-platform` 与 `nl2sql-service` 两个 tag（`valkey-bundle` 同批导 `k8s.io`） | 部署无 nodeSelector ⇒ 漏一台 = 调度到那台就 `ErrImagePull`。从 241 跑必须显式列 `125 126 241`（默认 `WORKERS=125 241` 是"从 126 构建"的历史形态）。**已知缺陷：`distribute.sh:34` 的 `TARBALL="/tmp/${IMAGE%:*}.tar.gz"` 对多段镜像名（`valkey/valkey-bundle`）含 `/` ⇒ 重定向进不存在的目录，`set -e` 当场断——它报的是“无此目录”而不是“镜像坏了”，极易误读。本轮不修仓库脚本，用等效的一次性分发脚本；修它需先方案（同 D24 台账）** |
| 4 | `kubectl apply -f 00-config.yaml` | server-side dry-run 报 `configured`（不是 `created`）；实 apply 后按 §2 的取法跑 **双向差集：`comm -3` 必须为空**（线上键集 == 声明的 18 键：9 平台 + 9 `NL2SQL_*`）；非空则**逐键定性**：该进清单，还是该删 | 静默保留未知键 = 下一份清单与线上对不上时没人知道是谁多的；键少了 ⇒ 有人手工建过 CM，按 §2 差集定位再补，不要整对象替换。**本节初稿写的是“该轮实取 10 个平台键名 ⇒ 比声明多 1 个”，那是错数：10-28 18:38 按双向差集复取结果为“空”（旧 rev `6ac466af` 的清单也只声明 9 键，merge patch 不删键 ⇒ 9+9=18），见 §1 落差 2 订正** |
| 5 | `apply -f 10-postgres.yaml`（已在位则跳）+ `apply -f 15-valkey.yaml` | `valkey` Pod Ready；`kubectl exec` 内 `valkey-cli ping` = `PONG`、`MODULE LIST` 含 `search` | 缺 `search` 模块 = 用了非 bundle 镜像，L2 向量检索不可用（`15-valkey.yaml` 头部那条坐标取证就是为此写的） |
| 6 | `apply -f 35-nl2sql-dbsql-job.yaml` | `job … status.succeeded=1`，且 **Job 日志里那句行为判据自己报绿**：`OK: 写路径被库侧拒绝（L1 成立）`（脚本会用 `nl2sql_dw_reader` 真插一行 `_l1_probe`，写得动就 `exit 1`）；库里回读：`nl2sql_meta` / `nl2sql_dw` 两库在位、角色 `nl2sql_meta`（db owner）/ `nl2sql_dw_owner`（NOLOGIN 组角色）/ `nl2sql_dw_reader` 到位，`users` / `orders` 行数与 `deploy/data/nl2sql_dw_fixture.sql` 头部登记的基线一致（已支付 4 笔合计 388.50、已退款 1 行 80.00、用户城市 北京 2/上海 1/广州 1、订单按城市 北京 4/上海 1/广州 1、跨 2026-09 与 2026-10 且无 8 月） | L1 靠**行为**而不是靠读到 `GRANT SELECT` 语句成立 ⇒ 只查 `succeeded` 不够；日志 24h 后自动清（`ttlSecondsAfterFinished`），取证要么当场取要么调高它 |
| 6.5 | **引用预检**（只读，apply 36/30/20 之前）：四类前置一次查清——① 三份清单里每个 `configMapKeyRef`/`secretKeyRef` 的键在 LIVE 对象里存在；② 挂成卷的 `ConfigMap nl2sql-data`（5 键，含 `nl2sql_meta_config.yaml`）与 `Secret observability-keys` 在位；③ 三台的 hostPath `/opt/ap-models/hf-cache` 里真的有 `models--BAAI--bge-small-zh-v1.5`；④ 现有 `agent-platform` Pod 落在哪台（决定“构建机自己那份 `k8s.io` 有没有补导”是不是致命） | 全绿才按 36 → 30 → 20 走。10-28 18:52 实取：36 引用 6 项 / 30 引用 16 项 / 20 引用 15 项**全部命中**；`nl2sql-data` 5 键在位；三台均 `dir=OK bge=Y size=184M`；当时 Pod 在 `<internal-node-01>`(241) = 构建机本身 ⇒ 补导那一笔不是可选项 | 这类缺失 **server-side dry-run 不报**（env 引用的键值是 kubelet 起容器时才判），表观是 Pod 卡 `ContainerCreating` + `CreateContainerConfigError`，或 hostPath `type: Directory` 不满足直接 `Pending` ⇒ 每轮白等 5–10 分钟。本轮脚本在 `.tmp-scratch/b6_preflight_3630.sh`（未入库：要固化成 `deploy/k8s/scripts/` 得先方案，登记 D25），所以本节四类检查项本身就是可复跑口径 |
| 7 | `apply -f 36-nl2sql-meta-init-job.yaml` | `succeeded=1`；第二步的 `--status` 打出 `nl2sql_schema_meta` 键值，其中 **`vector_dim` 记为 `512`**、`schema_version` 等于当前迁移最高版；**元库里查得到行**（`nl2sql_column_info` / `nl2sql_metric_info` / `nl2sql_value_info` / `nl2sql_relation_info` / `nl2sql_alias_info` 五张表行数均 > 0） | 列宽由 `VECTOR_DIM` 在建库前定死，512 写进去、拿 1024 的向量去查就是两边各自持有字面值那类错。行数 0 而 Job 绿 = 配置与 fixture 列名对不上（`metric_config.example.yaml` 用的是 `customers`/`order_id`，与种子对不上，不能直接灌）；36 的 CPU 编码 + 建索引是本批**唯一从未实跑过的链路** |
| 8 | `apply -f 30-nl2sql-service.yaml` | ① Pod Ready（`startupProbe` 给足冷加载时间）；② `/ready` 两池 `ok`；③ `/health` 的 `sql_backend` **非 null 且等于 dw 真实方言**——自批次 5 起这一位由本服务上报，它终于是真读数了 | ③ 报 `null` = `DW_DB_DSN`/`dw_db_enabled` 没生效；探针只 `SELECT 1`，**证明的是"库连得上"，不是"元知识在位"**（步 7 才是那条判据） |
| 9 | `apply -f 20-agent-platform.yaml` + `kubectl rollout status` | ① rollout `successfully rolled out`；② 新 Pod 内 `GIT_REV` == 步 2 的 rev；③ `/health`：`nl2sql=true`、**`sql_backend=null`**、`cache_backend=valkey`、`cache_ready=true`；④ 旧 Pod 终止、`revision` +1 | ③ 的 `sql_backend` 若还是 `postgres` ⇒ 跑的是批次 5 之前的镜像（把"接上"当成了"启用"）。rollout 卡住先看 Pod `Events` 里的 `CreateContainerConfigError`（落差 5 的形状），不要靠 `rollout status` 的超时判断 |
| 10 | 批次 6 取证（见 §4） | 每条都是"后端里查得到**本次**原文"，不是状态字段 | — |

## 4. 上线后取证（判据形状，具体读数落 `docs/operations/evidence/<日期>-nl2sql-release/readings.md`）

1. **身份与签头**：两侧 Pod 内 `INTERNAL_HMAC_KEY_FILE` 指向的文件可读且字节数 > 0（`wc -c`，不打印内容）；伪造 `X-Internal-Tenant` → `401`；合法签头走通 `/sql/train`。
2. **写路径端到端**：`/sql/train` → `200` + `report` 摄入计数 → 元库查得到该新行 → 下一句真问的召回里能看到它（这才叫"上线端点真的在喂数据面"）。
3. **读路径对账**：`/api/query` 三条真问与 fixture 基线逐条比——按城市订单数、已支付合计 `388.50`、"8 月"问法须 `genuinely_empty`。
4. **平台端到端**：命中 sql 特征词的提问，证据里出现 `执行的 SQL：`；Langfuse 按 traceId 查得到本次原文，且 nl2sql-service 的 span 也在（读法按 `observability-pitfalls.md`：`v2/observations?fields=io,usage`，载荷是多轮 JSON 编码）。
5. **缓存真值**：`/health` 的 `cache_backend=valkey` 之后，再取 `cache_stats` 的非零读数（命中一次再看），否则"配了但没在用"分不出来。
6. **租户隔离**：`tests/ha/test_tenant_isolation_real_pg.py` 与 nl2sql 三列恒过滤判据在现网库上复跑（两租户各灌不同数据，串味即红）；并发/限流按用户口径本轮不测。
7. **L2/L3 数据权限**：查 `ALLOWED_TABLES` 之外的表被拒；`users.phone` 在 `analyst` 角色下是掩码形态。

## 5. 回滚路径

- 滚动前备份：`kubectl get deploy,cm,secret -n agent-platform -o json > pre-release-snapshot.json`（`05-secrets.yaml` 那份是 demo 值，真实 Secret 只在集群里，丢了就没了）。
- 旧 tag 仍在三节点的 `containerd-k8s` 库里 ⇒ 回滚 = 把 image 指回旧 tag（可逆）。本批因此属 D1/D2，不是 D3。
- **回滚不覆盖数据面**：`35`/`36` 是幂等 Job，库与元知识不会因为回滚 Deployment 而回退；要撤数据面得显式动作（`build_meta_knowledge --prune` 只删源里已不存在的条目，不是撤销本次摄入）。

## 6. 曾经卡住的两条输入（**已解除**，2026-10-28 18:2x 用户答“按建议执行”）

两条都按本节建议口径落地了，不要再当未决项重新问一遍——只有换口令时才需要重新拍：

1. **`INTERNAL_HMAC_KEY` 怎么生成**：本机密码学随机源（`secrets.token_urlsafe(24)`）生成，`kubectl patch secret observability-keys --type merge` 注入，
   全程只打印键名与字节数、值不进日志不进 shell history。开关口径不变：`DEPLOY_ENFORCE_IDENTITY` **默认关**（`AGENTS.md` 身份层那条），
   所以“开发测试不开、生产显式开”这条已经成立，不依赖本键在不在位；四条方案级短板只登记不修（D23）。
2. **`DW_DB_DSN` / `META_DB_DSN` 的口令口径**：口令由本轮生成（字符集构造上避开 `% @ / ? #`），**DSN 的唯一来源就是这两条 Secret**（见 `30` 头部注释），
   留档在 `applications/nl2sql-service/.env` + `.dsh/ap-release-credentials-2026-10-28.json`（两者均 gitignored，写入前 `git check-ignore -v` 实测命中）。
   **改口令必须重跑 `35`**（角色口令与 DSN 两处各持一份就分叉）。

读数与判据（含写前/写后键集对账、滚动前快照位置）见 `docs/operations/evidence/2026-10-28-nl2sql-release/readings.md` §1。

### 6.1 当初挡住这两条的原问题（保留供后人判断口径是否仍适用）

1. **`INTERNAL_HMAC_KEY` 怎么生成**：建议本机密码学随机源生成、经 stdin 注入 `kubectl patch`，全程不落盘不入 shell history；需要的是"授权我生成并注入"这句话。
2. **`DW_DB_DSN` / `META_DB_DSN` 的口令口径**：`05-secrets.yaml` 里是 `*_dev` demo 值，真实环境不许照抄。要定的是——沿用 `35` 建角色时的口令口径（并据此补 Secret），还是现网已有 `nl2sql_dw_reader` / `nl2sql_meta` 角色及既定口令（则 `deploy/data/nl2sql_dbsql.sql` 的角色名与 `05-secrets.yaml` 的 DSN 需按真实名改）。**这两条 DSN 是口令的唯一来源**（见 `30` 头部注释），改口令必须重跑 `35`。

## 7. 本文不覆盖的

- 前端/console 之外的展示面（用户口径：后端接口写好后再写前端）。
- 并发与限流（`QUERY_MAX_CONCURRENCY` / `QUERY_RATE_LIMIT_PER_MIN` 保持 0 = 关闭，与老部署行为逐字节一致）。
- `env-126-inventory.md` 的现网部署态快照更新（用户裁定：那份只本地查看、不入库）。
