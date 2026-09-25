# 依赖安全风险接受登记（2026-09-25）

> 背景：v3 → main 合并后 Dependabot 报 23 个告警。经逐项对照 uv.lock 锁定版本与官方修复版本：
> - **13 个为陈旧告警**（anyio×4 / asyncmy×2 / mcp×3 / transformers×4），锁定版本已达标或包已移除，Dependabot 重扫后自动关闭；
> - **weasyprint 69→70.0 已升级修复**（agent_federation docs extra）；
> - 剩余 9 个为**上游无补丁**的依赖，全部为 dev-only（生产运行时不安装），本文件登记接受理由。

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
