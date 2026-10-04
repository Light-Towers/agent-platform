# 部署侧取证 runbook：会话身份存量 + 回退审计 operator 形态

> 用途：把两件**至今未取证**的部署侧事实变成「一条通道、一次代跑」的可执行清单，
> 而不是散落在方案里的"待运维核实"。本 runbook **全程只读**，不写、不删、不改任何数据。
>
> | 取证目标 | 为什么必须拿到 | 未拿到时的口径 |
> |---|---|---|
> | A. `checkpoints` 里存量 `user-*` thread_id 是否非零 | 决定 B7b-4 枚举式迁移是否需要真正执行重挂、兼容窗口多长 | 迁移脚本正确性不依赖存量数（存量为零即空转），但**不得表述为"迁移已验证"** |
> | B. `revert_audit.operator` 历史行的形态与基数 | 决定 `docs/plans/plan-audit-operator-principal-2026-10-03.md` §5 的可选脱敏 SQL 是否需要执行（旧值 = 明文部署密钥） | 不得声称"历史库里没有落过密钥" |
>
> 关联登记：`docs/TODO.md` §8（部署侧运维交接项）、`docs/plans/plan-codeql-b7b-principal-thread-identity-2026-10-01.md` §9 末两段。

## 1. 通道（三选一，按代价排序）

本机（Windows 开发机）**三条路都不通**。但 2026-10-04 重探后**根因已订正**：此前账面写的「`126` 在 banner 交换前被关闭 ⇒ 属服务端侧限制（fail2ban / `hosts.deny` / `MaxStartups` 一类）」是**误判**，本机从未真正到达过对端，那 5 次「同签名」重复观察没有排除任何东西。

**订正后的根因：本机网络位置 + 本地代理 TUN 劫持（不是对端封禁）**

- 本机在 `WLAN 192.168.1.11/24`，与部署段 `192.168.100.0/24` **不同网段**；`Find-NetRoute -RemoteIPAddress 192.168.100.126` ⇒ `nextHop=198.18.0.1`，流量进的是 `Meta`（`Meta Tunnel`，Clash Verge / `verge-mihomo` 的 TUN，持有 `0.0.0.0/0 via 198.18.0.2`），不是物理网关。本机 `OpenVPN TAP-Windows6` 适配器存在但状态 `Disconnected`。（推断非实测：2026-09 的经验记录里 126 的 SSH/SFTP 曾走通，说明当时网络位置或代理规则与现在不同。）
- 该 TUN 对**整段所有端口**都「完成三次握手后立刻关闭」：126 的 `2375/2376/22/6443/8000/30443/12345/9999/8888/4321/5432` 全报 `TcpTestSucceeded=True`，而**随机且不存在的** `192.168.100.254:12345`、`.99:22`、`.241:8000`、`.125:6443` 同样"成功"。⇒ **在这台机器上 `TcpTestSucceeded=True` 不含任何信息**（TCP 层假阳性），它既不能证明端口开放，也不能证明服务在场。
- 应用层实取（只读 GET，探针 `.codeartsdoer/temp/probe_deploy_channels.py`，输出落 `deploy_channel_probe.txt`）：`http://126:2375/_ping` ⇒ `RemoteDisconnected`；`https://126:2376/_ping` 与 `https://126:6443/version` ⇒ `SSLEOFError [UNEXPECTED_EOF_WHILE_READING]`；裸 socket 读 22 / 2375 ⇒ `recv` 返回 0 字节。⇒ 一条请求都没落到真服务，**连"端口开没开"都判不出来**。
- 本机工具面（`Get-Command` 实取，非 `$LASTEXITCODE`）：`docker` / `kubectl` / `helm` / `psql` / `minikube` / `kind` / `colima` **present=False**；Docker Desktop 未安装；`wsl -l -v` 报未装发行版；无 `~/.kube/config`；仓库根无 `.env`。主 `docker-compose.yml` 不发布 5432，HA compose 只绑 `127.0.0.1:5433`。

**通道清单（按代价排序；原第 2 条「恢复 126 的 22 端口访问」不再成立，已撤下——对端从未拒绝过我们）**

1. **（首选）运维/用户在可达环境代跑 §2 + §3，把输出原样贴回**——本 runbook 的每条查询都设计为"输出不含敏感原值"，可直接入档。
2. **自助解阻（须由本人操作，因涉及本机路由/代理状态）**：在与 `192.168.100.0/24` 同网段的机器上跑；或连上 `OpenVPN`；或把该段加进代理 bypass（mihomo 的 `DIRECT` 规则 / TUN `exclude` 列表），并确认物理网关确有到该段的路由。**改完先做对照复核**：对 `192.168.100.254:12345` 这类"必然不存在"的端口再测一次，若仍 `TcpTestSucceeded=True` 就说明劫持仍在，取证结论照旧不可得。
3. 临时 `NodePort` 暴露只读 psql（**属临时扩面，用完必撤**）：`kubectl -n agent-platform expose deploy/postgres --type=NodePort --name=pg-ro-tmp` → 取回 `NodePort` → 跑完立即 `kubectl -n agent-platform delete svc pg-ro-tmp`。

拓扑速查（`deploy/k8s/`）：namespace `agent-platform`；PG 为 Deployment `postgres`（`pgvector/pgvector:pg16`，固定在 control-plane 兼任的数据节点），库 `agent_platform` / 用户 `agent`，口令来自 Secret `agent-platform-secrets` 的 `POSTGRES_PASSWORD`。

## 2. 取证 A：存量 `user-*` thread_id

先拿到"该读的语句"本身（脚本自述，避免手抄漂移）：

```bash
uv run python scripts/migrate_thread_identity.py --principal <服务端断言租户> --emit-sql
```

默认 **dry-run**：只打印只读核实语句 + 人工核实名单，**不执行任何写操作**。把其中三条 SELECT 拿到集群里跑：

```bash
kubectl -n agent-platform exec deploy/postgres -- psql -U agent -d agent_platform -X -q -c \
  "SELECT 'checkpoints' AS tbl, count(DISTINCT thread_id) AS legacy_ids FROM checkpoints WHERE thread_id LIKE 'user-%'
   UNION ALL SELECT 'checkpoint_writes', count(DISTINCT thread_id) FROM checkpoint_writes WHERE thread_id LIKE 'user-%'
   UNION ALL SELECT 'checkpoint_blobs',  count(DISTINCT thread_id) FROM checkpoint_blobs  WHERE thread_id LIKE 'user-%';"
```

判定（逐条对应迁移脚本的分岔）：

| 现象 | 结论 | 后续动作 |
|---|---|---|
| 三表均 `0` | 无需迁移窗口 | 在 `docs/TODO.md` §8 把该项转 `[x]`，注明取证时刻 |
| 命中且形态为 `user-<12hex>` / `user-<32hex>` | 凭据摘要形态 ⇒ 待重挂 | 把命中的 `thread_id` 逐个作为 `--source` 传给脚本，按其打印的 `UPDATE` 人工执行（脚本刻意**不代执行**写操作） |
| 命中但形如 `user-x` / `user-<uid>-session-<sid>` | **非**摘要形态（dev 自填 / `monitor.build_thread_id()` 兼容符号） | 进"人工核实名单"，**不动**（迁移脚本对这类一律不改） |

目录侧补充（federation 上传会话目录，`session_<thread_id>`）：

```bash
kubectl -n agent-platform exec deploy/agent-platform -- sh -c \
  'ls -1 applications/agent_federation/updated 2>/dev/null | head -50; ls -1 applications/agent_federation/output 2>/dev/null | head -50'
```

## 3. 取证 B：`revert_audit.operator` 形态

**只看形态，不打印任何原值**（历史值可能就是可用的部署密钥）：

```bash
kubectl -n agent-platform exec deploy/postgres -- psql -U agent -d agent_platform -X -q -c \
  "SELECT count(*) AS total_rows,
          count(DISTINCT operator) AS distinct_operators,
          min(length(operator)) AS min_len,
          max(length(operator)) AS max_len,
          bool_or(operator = 'default') AS has_literal_default,
          min(reverted_at) AS first_row,
          max(reverted_at) AS last_row
   FROM revert_audit;"
```

怎么读这份输出（无需暴露原值即可定性）：

- `total_rows = 0` ⇒ 该部署从未触发过回退审计 ⇒ 方案 §5 的脱敏 SQL 无需执行，本项取证即闭合。
- `max_len` 等于当前 `API_KEY` 的长度 **且** `distinct_operators` 很小（1~2，等于历史上用过的密钥把数）⇒ 旧行**确为明文密钥**，按方案 §5 决定是否执行脱敏。
- `has_literal_default = true` ⇒ 存在 `API_KEY` 未启用（开发模式）时写入的行，值为字面量 `"default"`，无害。

若确实需要判定"某行是否等于当前密钥"，**不要把密钥送进 SQL 会话**（会进 `psql` 历史与服务端语句日志）。改在本地算摘要再比对，摘要在此仅作**等值连接子**，不承担安全强度：

```bash
# 本地：echo -n "$API_KEY" | md5sum   →   把得到的 hex 作为 :live_md5 传入
kubectl -n agent-platform exec deploy/postgres -- psql -U agent -d agent_platform -X -q \
  -v live_md5='<本地算出的 hex>' -c \
  "SELECT count(*) AS rows_matching_live_key FROM revert_audit WHERE md5(operator) = :'live_md5';"
```

## 4. 处置（取证之后才谈，均非本 runbook 自动执行）

- 脱敏历史行（可选，代价：旧行失去区分度）——由人拍板后执行：

  ```sql
  UPDATE revert_audit SET operator = 'legacy-credential-redacted'
   WHERE reverted_at < '<升级部署时刻>';
  ```

- 轮换 `API_KEY`：若历史日志/库里确认落过密钥且其访问面大于运维范围，**改值即失效**（B7b-5 后凭据已不参与任何派生，无需其它配合动作）。
- 兼容窗口内旧 `user-*` 会话目录**只读不删**（沿用 `migrate_thread_identity.py` 的「目标已存在拒绝覆盖」策略）。

## 5. 输出要求（便于直接入档）

贴回时请带上：① 命令原样；② 输出原样（本 runbook 的查询输出不含敏感值，可直接入库）；③ 执行时刻与时区；④ 在哪个集群/namespace。账面按 `docs/operations/testing-playbook.md` §2.1 的纪律附**测量时点**（对应 commit / 镜像 rev）。
