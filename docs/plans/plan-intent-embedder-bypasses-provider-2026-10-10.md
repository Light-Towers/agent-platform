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

## 5. 现场运行证据（2026-10-12 上线后补，比代码阅读强一级）

探针 Pod = 同一镜像 `db1a8b8`，**`EMBEDDING_MODE=mock`**，未挂 hostPath。分两轮：

| 轮 | 探针规格 | 结果 | 这条证明了什么 |
|---|---|---|---|
| r12 | `EMBEDDING_MODE=mock`，**未设** `HF_HUB_OFFLINE`/`TRANSFORMERS_OFFLINE` | `POST /query` **260s 内 0 字节**，curl rc=28 超时；服务端日志：`'[Errno 101] Network is unreachable' thrown while requesting HEAD https://huggingface.co/BAAI/bge-small-zh-v1.5/resolve/main/./modules.json` + `Retrying in 1s [Retry 1/5]`（每次 HEAD 约 60s 才失败，重试 5 次） | **配置说"用 mock"，请求路径仍然去实例化 `LocalEmbedder` 并回连 huggingface.co**。这不是静态推断，是被 `EMBEDDING_MODE` 明确设为 mock 之后现场发生的。`EMBEDDING_REQUIRE_REAL` 更管不到它——mock 后端本来就是"允许退化"的语义，而意图路由的退化走的是自己的 `except Exception` |
| r13 | 同上，但设了 `HF_HUB_OFFLINE=1`+`TRANSFORMERS_OFFLINE=1`（并故意不给权重缓存） | 请求 **12.8s** 正常完成（离线加载快速失败 ⇒ 关键词降级），不再卡 260s | 旁路的代价**完全取决于有没有离线开关**：线上清单恰好设了 `HF_HUB_OFFLINE=1` ⇒ 快速失败；**一旦这个开关被摘掉或 Pod 落到缓存不全的节点，代价就变成"每次提问先卡几分钟"**，而灯上什么都看不出来（`embedding_real` 仍 true，因为它测的是 RAG/memory 那条 `resolve_provider()` 路径） |

**这条把 §2 的严重度从"覆盖面被高估"提到"有可用性代价"**：被吞掉的不只是降级事实，还包括
**外网不可达时的重试预算**，且发生在**请求路径**而不是启动路径（启动期的重活我们特意挪出 `/health`
和 lifespan，旁路却把一次模型加载放回了请求路径上）。

拍板时请一并回答：**r13 那种"快速失败→关键词降级"是接受的稳态，还是必须让意图路由也吃到
`EMBEDDING_MODE`/`EMBEDDING_REQUIRE_REAL` 并把失败显式暴露成读数**（选项 A/B/C 见 §3，本轮仍未动手）。

## 6. 待拍板

① 选 A / B / C；② 若选 A，mock 提供方下的意图路由是"允许降级但必须报状态"还是"直接拒绝启动"。
