# 方案（待拍板）：意图路由绕过统一 embedding 提供方，导致真值灯覆盖面被高估

日期：2026-10-10　状态：**只出方案，未动代码**（按 AGENTS.md「先方案后编码」）
发现方式：本机真实浏览器实跑只读控制台（不是单测、不是 mock），日志与代码逐行对上。

## 1. 实测证据

| # | 读数 | 出处 |
|---|---|---|
| 1 | 启动期健康检查灯 `embedding_backend = "MockEmbedder"`、`embedding_real = false` | 本机 `API_KEY=demo-key-123 uvicorn agent_server.main:app :8123` → `/health` |
| 2 | 同一进程内，**首次 `/query`** 触发 `sentence_transformers` 真实加载并向 `https://huggingface.co/BAAI/bge-small-zh-v1.5/...` 发 HEAD 请求取权重，随后出现多行 `Batches: 100%`（真实 CPU 推理），该次请求从发起到出结果耗时明显拉长（19:21:56 发起 → 19:22:09 起加载） | 同一次运行的 uvicorn 日志 |
| 3 | 全仓只有两处构造 `LocalEmbedder`：`agent_core/memory/embedder.py:264`（`get_embedder()` 的落底分支）**和** `agent_core/intent/classifier.py:93` 的 `LocalEmbedder()` | grep `LocalEmbedder(` |
| 4 | 后一处**不读 `EMBEDDING_MODE`、不经 `get_embedder()`、不受 `EMBEDDING_REQUIRE_REAL` 约束**，且整段语义打分被 `try: ... except Exception:` 包住，异常时落 `_keyword_rule()`（`classifier.py:164-186`） | 实读 |
| 5 | 126 现网 Pod 内 `find_spec` 实测 `torch/sentence_transformers/transformers/huggingface_hub` **全为 False** | `docs/operations/env-126-inventory.md` §4.6 |

## 2. 影响面（三条，按严重度）

1. **底线 2 的灯被高估**：`/health` 那盏"语义检索是不是真在算"只描述 `resolve_provider()` 这条 RAG/记忆路径。意图路由（决定"这题交给哪项能力"）走的是另一条本地模型路径，**灯绿不代表它在算语义，灯红也不代表它在降级**。演示/验收时被追问"意图分流是真的吗"，现在答不出实证。
2. **现网意图路由恒为关键词降级**（证据 5 + 4）：镜像里没有 sentence-transformers ⇒ 每次 `_embedder()` 抛 ImportError ⇒ 被吞掉 ⇒ 走关键词规则。**这不是"开关没开"，是"能力没有承载面"**，与 D1 把 extra 装进镜像后才会第一次真正生效。
3. **Dockerfile 加 extra 之后引入新的首次请求代价**（证据 2）：镜像里一旦有了 ST，意图路由会在**第一次提问**时加载模型；离线集群里若缓存不在该节点或没设 `HF_HUB_OFFLINE`，加载失败**又会被同一个 except 吞成关键词降级** —— 运维看到的是"路由照常工作"，实际语义层从没跑起来。这正是本轮清单已经防住的那类"静默退化"。

维度层面不担心：`_intent_prototype_vector()` 的原型向量是**运行时算**的（不是文件里烘焙好的），换模型不会造成向量列错位，但会**静默改变路由行为**。

## 3. 选项

| 选项 | 做法 | 代价 / 风险 | 判断 |
|---|---|---|---|
| **A（建议）** | 让 `classifier._embedder()` 改走内核 `get_embedder()`，与 RAG/记忆共用同一条选型与 `EMBEDDING_REQUIRE_REAL` 护栏；意图路由需要的"必须是语义模型"由调用方在启动期校验（拿不到语义提供方就明确记一条"意图层为关键词降级"） | 意图路由的向量空间会随 `EMBEDDING_MODE` 变（mock 下原型向量变成 hash 向量，相似度失去意义）⇒ **必须同时显式暴露降级状态**，否则是把一个静默换成另一个静默 | 收敛为"单一实现 + 全局装配"，符合架构原则；但**属横切改动，需拍板** |
| B | 保持两处不动，只把 `/health` 的灯改名并加一个 `intent_router_backend` 字段，把覆盖面写清楚 | 零行为风险；但两条 embedding 路径继续各自为政 | 可作为 A 之前的过渡（本轮已先把描述文字改准确，未加新字段） |
| C | 把意图语义层从本版链路里明确宣告为"未生效"，D1.5 第一道检查加一条：现场问一个只有语义才能判对的问题，看是否真按语义分流 | 不花钱；只是把话说清 | **无论选 A/B 都该做**，属验收口径而非修复 |

## 4. 本轮已做的与未做的

- 已做（不改行为）：`/health` 两个字段的 description 里写清覆盖面与这条旁路；控制台页面上把"steps 为空"的文案从"未走受控执行边界"改成不越证的表述；本方案入库留档。
- **未做**：不动 `classifier.py`、不加 `intent_router_backend` 字段、不改 `EMBEDDING_MODE` 语义 —— 全部等拍板。

## 5. 待拍板

① 选 A / B / C；② 若选 A，mock 提供方下的意图路由是"允许降级但必须报状态"还是"直接拒绝启动"。
