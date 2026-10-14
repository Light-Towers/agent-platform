# 2026-10-14 早晨开盘状态读数（rev `6ac466af` 仍在位）

> 全部为回读，不含推断。截图未入库：Jaeger/Langfuse 的 trace 页面里带业务语料原文，
> 落在仓库外 `D:/Study/local-evidence/2026-10-14/`（本机），需要留证时从这里取。

## 1. 昨天的"UI 打不开"已闭合，且**不是绑定、也不是服务挂了**

| 目标（从需求方这台机器） | 现在 | 昨天 10:33–10:49 UTC |
|---|---|---|
| `http://192.168.100.126:16686/api/services` | **200 / 92B / 8.9ms** | `000 / 5.0s` |
| `http://192.168.100.241:3000/api/public/health` | **200 / 34B / 13.1ms**（`{"status":"OK","version":"4.57.0"}`） | 先 200 后 `000 / 5.0s` |
| `http://192.168.100.126:18000/health` | **200 / 503B**（重启 port-forward 之后） | `000 / 5.0s` |
| `http://192.168.100.126:18000/console.html` | **200 / 16555B** | `000 / 5.0s` |
| 编造的 `126:2222`（对照组） | `000 / 5.0s` | 也"通" |

三条结论：

1. **Jaeger 的发布形态是运行时铁证，不是脚本推测**：`docker ps` 显示
   `0.0.0.0:16686->16686/tcp, [::]:16686->16686/tcp` ⇒ 昨天那个"IP 绑定限制"的猜测**彻底排除**
   （`deploy/k8s/scripts/jaeger.sh:25` 与 compose 的 `"3000:3000"` 此前已从文本层面排除，这次是容器实况）。
2. **`18000` 昨天打不开的直接原因是 port-forward 进程不在了**（`12ms 被拒` = 端口无人监听，
   与"5.0s 无应答"是两种不同形状）。它不是常驻服务，机器/会话一停就没 ⇒ **演示前必须先跑
   `bash deploy/k8s/scripts/portforward.sh start`，并把 `ss -tlnp | grep :18000` 当作检查项**（本轮已实跑，见 §3）。
3. **昨天那批 `000 / 5.0s` 读数有一半是本机造成的**：这台机器的流量被 TUN 模式代理客户端接管
   （`Test-NetConnection` 对编造端口也报 `TCP=True`、`Ping=False`；`Meta Tunnel 198.18.0.1/30` 是 fake-ip 段）。
   ⇒ 判"能不能打开"必须看**时延形状**：毫秒级带字节数才是真读数，**整齐 5.0s 无字节 = 本机路径问题**（坑档 §9）。

## 2. 平台侧：一次由 liveness 触发的重启（这是演示当天的真实风险）

```
pods:  agent-platform-85794678c-9hjg4  1/1 Running  RESTARTS=1 (12m ago)  NODE=ambari01
       postgres-6ff4688bb8-vn7v6       1/1 Running  RESTARTS=0             NODE=ambari03
GIT_REV（Pod 内 cat）= 6ac466af2ebf2d6d9f09b1fb181525a72268bdc3   ← 与昨天一致，代码面没动
lastState.terminated = exitCode 137, reason "Error", finishedAt 2026-10-13T10:37:56Z
events = Liveness probe failed: Get "http://10.244.2.15:8000/health": context deadline exceeded
         → Killing: Container agent-platform failed liveness probe, will be restarted
resources = limits {cpu 1, memory 2Gi} / requests {cpu 250m, memory 1Gi}
```

**定性**：137 在这里是 **kubelet 因 `/health` 超时而主动杀**（先 liveness 失败、再 `Killing` 事件、最后 137），
不是 OOMKilled（那种 `reason` 会是 `OOMKilled`），也不是人为 `docker stop`。
**时间线值得注意**：`finishedAt=10:37:56Z` 正好落在我昨天那批"UI 全打不开"的读数窗口里
（10:33 起 ssh 被关在 kex 外）⇒ 当时至少有**两件事叠在一起**：Pod 应答变慢/卡住，以及本机路由失效。
⇒ **演示前检查项加一条**：开盘先 `kubectl get events --sort-by=.lastTimestamp | grep -i unhealth`，
看 `/health` 是否已经出现过 liveness 超时；若出现过，**不要在没查清前上台**（`/health` 一卡，探针就会当场把 Pod 重启给你看）。

## 3. 面板与健康（重启 port-forward 之后，Pod 内只读）

```
/history?session_id=tenant-default&limit=50  → HTTP 200  count=0  thread=tenant-default   ← 昨天的整桶清空仍是有效状态
/health → HTTP 200 status=healthy storage=postgres sql_backend=postgres embedding_real=True llm=True
          otel_status=ACTIVE langfuse_ready=True search=False revert=True
          identity_mode=single planner=deterministic auth_enabled=True forensic=True guard_enabled=True
portforward.sh start → LISTEN 0.0.0.0:18000 (kubectl pid=3496802) + /health 200 + "OK: port-forward :18000 就绪"
```

昨天清掉的 checkpoints **没有被复验写入路径**这件事仍未闭合：`count=0` 只证明空态，不证明写路径。
**演示第一轮真实问答就是那条证据**（同时也是面板的第一条内容）。

## 4. 备份仍在位（但边界没变）

```
126:/tmp/ckpt-backup-host/  (-rw------- root)
  checkpoint_blobs.csv 289052B   checkpoints.csv 472B   checkpoint_writes.csv 79B   mtime Oct 13 18:27
```
126 与 241 的 uptime 都是 **20 天** ⇒ 昨晚"关掉服务器"关的不是这两台主机，`/tmp` 因此没被清。
**边界照旧**：仍在宿主 `/tmp`（下次真重启就可能没），且**回灌恢复路径未实跑验证**。

## 5. 浏览器面（Qoder 内置浏览器）

- 结构读数拿到了：`console.html` 真渲染出"知识库服务 · 只读控制台"整页（左=过程时间线／中=问答／右=平台自述），
  页脚三条诚实声明都在（仅限内网、会话隔离粒度到租户、提问原文与检索片段会发给模型服务、只统计用量不显示金额）。
- 未输入密钥时页面如实显示 **"状态读取失败：连接失败或服务中途不可用（请求未能完成）"**——
  `auth_enabled=True` 下这是**预期行为**，演示口径要提前说明，别让人以为服务坏了。
- **截图没拿到**：`take_screenshot` 报 `NATIVE_BROWSER_VIEWPORT_UNAVAILABLE … visibilityState=hidden`
  ⇒ 内置浏览器面板当前是隐藏 surface，需要**把 Qoder 的 Browser 面板打开**才能出图。
  结构留证（上面的 snapshot 文本）已在本文，png 待面板打开后补。
