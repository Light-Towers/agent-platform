# 方案（待拍板，未动代码）：优雅关闭时 tracing 的 flush 没有上界，会把 137 的窗口吃光

日期：2026-10-10　类型：横切（退出路径），属内核 `agent_core.tracing`
关联：`docs/operations/env-126-inventory.md` §4.7（exitCode 137 定性）、G6；
`docs/operations/minimal-release-runbook.md` §7.4（现场故障判据）、清单里 `terminationGracePeriodSeconds: 60`

## 1. 事实（两条读数 + 一处代码）

| # | 读数 | 出处 |
|---|---|---|
| 1 | 那次 137 的关闭序列里，先出现 **OTLP export timeout**，再出现 `failed to resolve host 'postgres'`，然后 `Shutting down` → `Waiting for background tasks to complete` → 到 `192.168.100.126:4318` 的 `No route to host` ⇒ 最终被 SIGKILL | `env-126-inventory.md` §4.7 e17[8] `kubectl logs --previous` 尾部 |
| 2 | 当时清单里探针与宽限期全是默认值（`terminationGracePeriodSeconds` 默认 30s） | `deploy/k8s/20-agent-platform.yaml` 改前 |
| 3 | `shutdown_tracing()` 调 `provider.force_flush()` **不带 `millis_timeout`**，OTel SDK 该参数默认 30000ms；紧接着 `provider.shutdown()` 还会做最后一轮导出 | `packages/agent-core/agent_core/tracing.py:498-501` |

⇒ 默认配置下，光是"退出时把 span 冲出去"就可以吃掉**整整一个 30s 宽限期**。端点可达时它很快返回（现状没人踩到）；端点不可达（本轮那次）就是"关闭被自己最不想等的事情拖住"。清单已把宽限期抬到 60s，但那只是买时间：**上界应该由代码给，而不是由 kubelet 的默认值给**。

## 2. 为什么这不是"把宽限期调大就行"

- 宽限期调大 ⇒ 滚动重启/节点驱逐的收敛时间同步变长（演示与验收都在等 `rollout status`）；
- 不可达端点下的 flush 本质是**不可能成功**的，多给 30s 也只会丢掉尾批 span，不会变出结果；
- 尾批 span 该不该保，和"保多久"是两件事：现在代码是"无限等（受 SDK 默认 30s 约束）"。

## 3. 选项

| 选项 | 做法 | 代价 | 判断 |
|---|---|---|---|
| **A（建议）** | `force_flush(millis_timeout=<可配置，默认 2000>)`，超时只记一条 WARNING（"退出时未冲完 N 个 span"），并把同一个上界传给 `shutdown()`；上界来自配置项而非硬编码 | 端点慢时可能丢尾批 span（现状是不可达时本来就丢） | 有界、可观测、与"报错脱敏不阻塞主流程"的既有取向一致 |
| B | 退出路径不动，靠 `terminationGracePeriodSeconds: 60` 兜 | 零代码改动 | 把不变量交给部署参数，**下次换环境就失效**；与本项目"由构造保证"的原则相背 |
| C | 关闭时彻底跳过 flush（fire-and-forget） | 最简单 | 不可取：正常滚动重启也会丢尾批 span，等于削弱基线 5"每次调用都能追到" |

## 4. 影响面与验收

- 影响：所有经 `init_tracing` 装配的应用（6 个 app 共用内核退出入口）——属横切，改一处全域受益，也正因如此**必须先拍板**。
- 验收（可当场证，不依赖模型密钥）：
  1. 单测：给一个会阻塞的 exporter，断言 `shutdown_tracing()` 在 `≤ 上界 + 容差` 内返回，且日志里有那条 WARNING（不得静默）。
  2. 集群：临时把 `OTEL_ENDPOINT` 指到一个不可达地址 → `kubectl delete pod` → 关闭耗时显著小于 60s、`ExitCode` 不再是 137。
  3. 反向：端点正常时尾批 span 仍在 Jaeger 里查得到（证明不是靠"不 flush"糊过去的）。

## 5. 待拍板

① 选 A/B/C；② 若选 A，默认上界取多少（建议 2000ms）与配置项命名（建议 `OTEL_SHUTDOWN_FLUSH_MS`）；③ 是否顺带把探针 `timeoutSeconds` 之外的那条"重活不进 `/health`"的不变量补成 lint（同 §6 门禁候选，见 `plan-schema-drift-existing-db-gap-2026-10-10.md` §5）。
