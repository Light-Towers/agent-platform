# 依赖安全风险接受登记（2026-09-25，v3 分支）

> 背景：工具埋点收口复审修复推送 v3 后，GitHub 在默认分支（main）报 21 个 Dependabot 告警。
> 逐项对照 **v3 的 uv.lock 锁定版本**与官方修复版本 triage（`gh api dependabot/alerts` 拉活告警 + 解析 uv.lock 取实际解析版本与反向依赖）：
> - **weasyprint 69→70.0 本轮升级修复**（agent_federation `docs` extra，dev-only）——v3 此前落后 main 一个补丁版本（main 已于 ef3c0fd 修，v3 本次补齐，避免合并回归）；
> - **anyio / mcp / transformers 为 manifest-range 误报**：v3 锁已分别为 4.14.2 / 2.0.0 / 5.15.0，均 ≥ 官方 first_patched；但 pyproject 声明下界低于修复版，Dependabot 依赖图按声明范围判定为「可引入漏洞版本」故保持 open。已于 v3 与 main 同步收紧下界（见「已修复（本轮）」），Dependabot 重扫后关闭；
> - **asyncmy 已不在 v3 锁**：依赖图陈旧条目，重扫自动关闭；
> - 剩余 3 个为上游无补丁依赖，全部 dev-only（生产运行时不安装），本文件登记接受理由。
> 注：GitHub 告警基于默认分支（main）扫描；v3 与 main 锁基本一致（v3 仅 weasyprint 此前落后，现已对齐）。

## 已修复（本轮）

| 包 | 改前→改后 | 告警 | 来源 | 说明 |
|---|---|---|---|---|
| weasyprint | 69.0 → 70.0 | 1 medium（SSRF） | agent_federation `docs` extra | dev-only（文档构建），升级到首个修复版本 70.0；`uv lock --upgrade-package weasyprint` 仅动本包，无传递版本漂移 |
| anyio | （原未声明，纯传递）→ `>=4.14.2` | critical+medium | 根 `[project].dependencies`（传递自 httpx/mcp） | 锁定 4.14.2 已达标；v3/main 同步收紧下界 |
| mcp | `>=0.9` → `>=2.0.0` | high×3 | 根 + agent-runtime `mcp` extra | 锁定 2.0.0 已达标；v3/main 同步收紧下界 |
| transformers | eval 边经 `flashrag-dev` 传递（松散）→ eval extra 显式 `>=5.15.0` | high×3+medium×1 | 根 `eval` extra（prod `knowledge-service` 早已 `>=5.15.0`） | 锁定 5.15.0 已达标；v3/main 同步收紧下界 |

## 接受清单（上游无补丁，dev-only）

| 包 | 锁定版本 | 告警 | 来源（反向依赖） | 上游状态 | 接受理由 |
|---|---|---|---|---|---|
| fschat (FastChat) | 0.2.36 | 3 high（SSRF ×2 / 资源耗尽）+ 2 medium（开放重定向 / 内容审核绕过） | 仅 `flashrag-dev` extras | 无补丁，上游近两年未发版 | 仅检索回归评测本地使用，不部署为服务，SSRF/DoS 暴露面≈0 |
| nltk | 3.10.3 | 1 high（模型工件路径穿越） | 仅 `flashrag-dev` extras | 无补丁（3.10.3 已是最新） | 仅加载本地受信模型文件时使用，不处理不可信来源工件 |
| accelerate | 1.14.0 | 1 medium（分片 checkpoint weight_map 路径遍历） | 仅 flagembedding / peft（RAG extras） | 无补丁 | 训练/推理加速库，漏洞面不在网络路径 |

## 复核触发条件

出现任一情况应重新评估并升级/替换：
1. 上游发布补丁版本（`uv lock --upgrade-package <pkg>` 即可跟进）；
2. 上述 extras 被用于生产路径（dev-only 前提失效）；
3. 告警严重级别上调至 critical。

## 排查方法备忘

uv.lock 反向依赖解析：`[[package]]` 分块取 `dependencies = [` 段中的 `{ name = "X" }` 条目（非版本约束格式），定位任意传递依赖真实引入方；`uv tree -i <pkg>` 可拉反向树，但需 `--python 3.12` 规避 deepagents 改名残留导致的多 Python 版本解析失败（py3.14/win32 split 报 deepagents 不可达）。
