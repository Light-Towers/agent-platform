# 依赖安全风险接受登记（2026-09-25）

> 背景：v3 → main 合并后 Dependabot 报 23 个告警。经逐项对照 uv.lock 锁定版本与官方修复版本：
> - **weasyprint 69→70.0 已升级修复**（agent_federation docs extra），告警已翻转 fixed；
> - **anyio / asyncmy / mcp / transformers 共 13 个为 manifest-range 误报**：uv.lock 实际锁定版本已 ≥ 官方 first_patched，但 pyproject 声明下界低于修复版，Dependabot 依赖图按「声明范围可引入漏洞版本」判定故保持 open。已于 main 经 `fix/main-dep-security-floors` 主动收紧下界（见下「本轮主动修复」），Dependabot 重扫后关闭；
> - **asyncmy 不在 uv.lock**（依赖图陈旧条目），重扫后自动关闭；
> - 剩余 9 个为**上游无补丁**的依赖，全部为 dev-only（生产运行时不安装），本文件登记接受理由。

## 本轮主动修复（收紧下界，fix/main-dep-security-floors → main）

Dependabot 依赖图按 pyproject 声明的版本范围判定，不读 uv.lock 锁定版本；故锁定已安全但声明下界过低时告警保持 open。以下改动把声明下界抬到 ≥ first_patched，重扫即关闭。

| 包 | 改动 | 关闭告警（severity×n） | first_patched | 锁定版本 | 引入位置 |
|---|---|---|---|---|---|
| mcp | `>=0.9` → `>=2.0.0` | high×3（DNS 重绑定 / WebSocket / HTTP session） | 1.28.1 | 2.0.0 | 根 `mcp` extra + `packages/agent-runtime` `mcp` extra |
| anyio | （原未声明，纯传递）→ `>=4.14.2` | critical×1 + medium×1（TLSStream IDNA 2003 / process-pool 阻塞） | 4.14.2 | 4.14.2 | 根 `[project].dependencies` |
| transformers | eval 边经 `flashrag-dev` 传递（松散）→ eval extra 显式 `>=5.15.0` | high×3 + medium×1（RCE / 路径遍历） | 5.10.0 | 5.15.0 | 根 `eval` extra（prod `knowledge-service` 早已 `>=5.15.0`） |
| asyncmy | 不在 uv.lock，无需改动 | critical×1（SQL 注入） | 无补丁但非依赖 | — | 依赖图陈旧条目，重扫自动关闭 |

> 验证：`uv lock --check` 通过（锁定版本已满足新下界，无传递漂移）；`ruff` 干净。

## 接受清单

| 包 | 锁定版本 | 告警 | 来源（反向依赖） | 上游状态 | 接受理由 |
|---|---|---|---|---|---|
| fschat (FastChat) | 0.2.36 | 4 high（SSRF ×2 / DoS ×2）+ 2 medium | 仅 `flashrag-dev` extras | 无补丁，上游近两年未发版 | 仅检索回归评测本地使用，不部署为服务，SSRF/DoS 暴露面≈0 |
| nltk | 3.10.3 | 1 high（模型工件路径穿越） | 仅 `flashrag-dev` extras | 无补丁（3.10.3 已是最新） | 仅加载本地受信模型文件时使用，不处理不可信来源工件 |
| accelerate | 1.14.0 | 2 medium | 仅 flagembedding / peft（RAG extras） | 无补丁 | 训练/推理加速库，漏洞面不在网络路径 |

## 复核触发条件

出现任一情况应重新评估并升级/替换：
1. 上游发布补丁版本（`uv lock --upgrade-package <pkg>` 即可跟进）；
2. 上述 extras 被用于生产路径（ dev-only 前提失效）；
3. 告警严重级别上调至 critical。

## 排查方法备忘

uv.lock 反向依赖解析：按 `[[package]]` 分块，取每块 `dependencies = [` 段中的 `{ name = "X" }` 条目（非版本约束格式），可定位任意传递依赖的真实引入方。
