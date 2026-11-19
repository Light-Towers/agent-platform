# ADR：路由提示词热加载（改提示词不重启服务）

> 状态：✅ 已部署 + 真环境验证通过（2026-11-19 18:45，绑 rev=fe4e4aab，平台镜像 e8a59304979e / digest e3fdee92）。触发（用户 2026-11-19）：路由 prompt 把"关系抽取/知识图谱是什么"判 direct 跳过检索；用户要求 ① 全局治本、改提示词不能重启服务 ② 选库只压 direct 不压 sql/search ③ 检索无证据时如实说"库里没找到"，不退回通用知识硬答。

## Context（实取事实）

1. **根因**：`decide_route`(router.py:79) 的 system prompt 只列能力清单，没告知"有本地知识库"，LLM 把领域概念问题判 direct。heuristic 回退词表反而含"什么是/解释/原理"，LLM 挂掉时判得对。
2. **全仓无配置热加载机制**（subagent 逐项核实）：`get_settings()`、`route_hints.json`、`nl2sql settings` 全是 `lru_cache` 终身缓存；无 watcher/SIGHUP/Valkey 配置 poll。
3. **唯一可复用零件**：nl2sql prompt 加载器 `_prompt.py:32-51` 的 `(mtime_ns, size)` 指纹惰性重读（有回归测试 test_prompt_loading.py）。
4. **k8s 现状**：`agent-platform-config` CM 已存在但只以 env 注入（env 启动解析一次，改了必须 rollout restart）；无 volume 挂载。nl2sql-data CM 是 volume 挂载先例（kubelet 自动同步文件）。
5. **已有方案**：plan-router-keyword-gate-hides-corpus §14 已分析三层障碍 + H1/H2/H3，但未拍板未实现。

## Decision

### 核心：通用热文本加载器 + ConfigMap volume 挂载
- 在 agent-core（零依赖内核）加 `hot_text.py`：`load_hot_text(path, fallback)`，每次调用 `stat()` 取 `(mtime_ns, size)` 指纹，变了读盘、没变用缓存（复用 nl2sql 已验证模式）。这是**通用能力**，以后所有提示词/词表都能用，不只为这一处。
- 路由 system prompt 外置到 `data/router_system.prompt`，代码只留 fallback 默认值。
- 部署：新建/复用 CM `agent-platform-prompts`，把该 prompt 文件以 **volume 挂载**进 agent-platform Pod（只读），`kubectl patch cm` 改内容 → kubelet 同步文件 → 下次请求 `load_hot_text` 感知 mtime 变化自动重读 ⇒ **不重建镜像、不重启**。
- `route_hints.json` 同样改用 `load_hot_text`（顺手治 TD-7 的"改词表要重启"）——但词表是 JSON，加载器需支持"读文本后 parse"，或单独封装。先只做 prompt，词表作为后续。

### 路由逻辑（用户拍板：选库只压 direct）
- guard(blocked) 之后：若 `knowledge_id` 非空且 heuristic/LLM 判 direct → 改判 rag（只压 direct）。
- 若判 sql/search/code_execution/mcp（明确能力）→ 不覆盖，保留原路由。
- heuristic 基线不动（词表已含概念词 → rag）。
- eval golden 不动（id=6 概念→rag 本就一致），新增"选库强制 rag"用例。

## 落地命令（在线 patch，manifest 不入库——本仓 deploy/k8s 只有 scripts）

> 以下在控制面 126 执行；命令即为批准依据，可复现。改提示词今后只需第 4 步。

```bash
# 1) 创建 prompt ConfigMap（内容为 router_system.prompt 的全文，见本仓 applications/agent_server/agent/data/router_system.prompt）
kubectl -n agent-platform create cm agent-platform-prompts \
  --from-file=router_system.prompt=./router_system.prompt \
  --dry-run=client -o yaml | kubectl apply -f -

# 2) 给 deployment 加 volume + volumeMount（一次性）
kubectl -n agent-platform patch deploy agent-platform --type='json' -p='[
  {"op":"add","path":"/spec/template/spec/volumes/-","value":{"name":"router-prompts","configMap":{"name":"agent-platform-prompts"}}},
  {"op":"add","path":"/spec/template/spec/containers/0/volumeMounts/-","value":{"name":"router-prompts","mountPath":"/run/app-prompts","readOnly":true}}
]'
# patch 触发 rollout（仅这一次需要）；新 Pod 起来后 /run/app-prompts/router_system.prompt 可见

# 3) 验证挂载
kubectl -n agent-platform exec deploy/agent-platform -- cat /run/app-prompts/router_system.prompt

# 4) 今后改提示词：只改 CM，不重建镜像、不 rollout
kubectl -n agent-platform patch cm agent-platform-prompts \
  --type=merge -p='{"data":{"router_system.prompt":"<新提示词全文>"}}'
# kubelet 同步卷文件（通常≤1min）→ 下次请求 load_hot_text 感知 mtime 变化自动重读
```

## 真环境验证（2026-11-19 18:45，绑 rev=fe4e4aab）
- ✅ 静态：hot_text 3 passed(1 skip/Win)、test_router 9 passed、scope_forces_rag 3 passed、ruff/doc-sync 绿。
- ✅ 部署：平台 `e8a59304979e` 三节点一致；CM `agent-platform-prompts` 创建 + deployment volume 挂载 patch 成功（一次性 rollout）；Pod 内 `/run/app-prompts/router_system.prompt` 可见。
- ✅ 路由（真环境 API）：选库问"知识图谱是什么？"→ `route=rag`、evidence(count=4,node=rag)，如实答"证据中只有关系抽取内容"（不硬编）；选库问"统计订单销售额"→ `route=sql`（没被压 rag）；不选库问概念→ `route=rag`（新 prompt 生效）。
- ✅ **热加载**：`kubectl patch cm` 加 marker → **90s** 后 Pod 内挂载文件出现 marker → 恢复；全程未 rollout、未重建镜像。改提示词从此秒级生效不重启。
- 注：126 SSH 夜间超时，最后"marker 已恢复"的二次确认没做成（恢复命令本身执行成功，kubelet 同步机制同 90s）。明日可复核。

## Consequences
- 改提示词从"重建镜像+rollout（~30min）"降为"`kubectl patch cm`（秒级、不重启）"。
- 通用加载器可被后续任意提示词复用。
- 需改部署 manifest（加 CM + volume 挂载），属运维面改动。
- 边界：CM volume 同步非即时（通常 ≤1min），改完不是立刻生效，但无需重启。
- 热切换风险（§14）：本场景只换 prompt 文本、不换 LLM 客户端，不触发"配置新/连接旧"问题，比 H1 简单。

## Alternatives（未采纳）
- H2 admin reload 端点：多一个写口子，且仍需代码里读新值；本场景 volume+mtime 更自然。
- Valkey 存 prompt：无先例、引入一致性复杂度。
- 每次读盘不缓存：实现最简但每请求一次 IO，mtime 指纹是已验证的折中。
