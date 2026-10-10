# 方案：memory_backend 用废弃 embed_texts 签名 ⇒ 类型化记忆恒空（2026-10-10）

> 立项来源：演示版第 0 天真集群实跑。`/query` 每次都在日志里打
> `ERROR [agent_server.memory.longterm] 类型感知召回失败，降级内核/空` +
> `TypeError: embed_texts() got an unexpected keyword argument 'dim'`。
> 与模型密钥 403 无关，是一条独立的、**恒失败**的代码路径。

## 1. 实测事实（读码 + 线上日志双向，非推测）

**签名已变，调用方没跟上**：

- 现签名 `applications/agent_server/rag/embed.py:35`：`async def embed_texts(texts: list[str])`
  —— **没有 `dim` 形参**，且是 **async**。维度改由同文件 `_sync_env()`（L22-32）在每次算向量时
  把 app 配置写进 `EMBEDDING_DIM` 环境变量传给内核（这条时序本身另有独立缺陷，见第五章）。
- 旧调用方 `applications/agent_server/memory/memory_backend.py:90`：
  `return embed_texts(texts, dim=self.dim)` —— 传了不存在的 `dim=`，且在 async 函数里**没 await**。
- 同一处 `:109`（在**同步**函数 `embed_memory` 里）：
  `return embed_texts([text], dim=get_settings().vector_dim)[0]` —— 同样传 `dim=`；即便去掉 dim，
  也是对 coroutine 取 `[0]`。**两处各含两个缺陷。**

**恒失败面**：`embed_memory` 的全部真实调用点 `:137`（remember_typed 路）与 `:172`（recall_typed 路）
每次必抛 TypeError，被 `memory/longterm.py:105` 的 `except` 捕获后「降级内核/空」⇒
**类型化语义记忆的向量这一路恒为空**。它不卡主链路（被捕获），但"记忆"的语义维度是空的。

**为什么测试从来没抓到（本仓第三处同族盲区）**：

| 用例 | 手法 |
|---|---|
| `tests/memory/test_longterm_h.py:146 / :176 / :207` | `monkeypatch.setattr(mb, "embed_memory", lambda t: [0.0] * 512)` |
| `tests/governance/test_workspace_isolation.py:174` | 同上 |

四处**全部把 `embed_memory` 整个替身化**，真实函数体在测试里从未执行 ⇒ 「测试全绿」与「向量算得出来」
是两件事。这与演示版方案 A.2 新查第 2 条登记的「拦截用例把 `guard_input` 替身化」是同一个模式，
也与 R6 那轮「mock 全绿而真集群炸」同源。**修完必须补一条不打替身的用例**，否则同类回归仍不可见。

## 2. 目标与非目标

**目标**
1. 让 `embed_memory` 真的算出向量（消除 TypeError 与 coroutine 误用）。
2. 消掉 app 手写的 embedder 适配层，改用内核已有的单一实现。
3. 补一条**不经替身**的用例，钉住「真函数体可执行且返回 settings.vector_dim 维向量」。

**非目标**
- 不改 `embed_memory` 的**同步契约**（见 §3 理由），不动 `PgMemoryStore(pool, embed_memory)` 的注入形态。
- 不动 `_sync_env()` 的「每次算向量时才映射 env」这条时序（它与建表期维度派生的错位是独立议题，
  已由演示版风险 2 与第五章彻底修复项登记）。
- 不动 LocalEmbedder 在事件循环内同步推理的阻塞问题（演示版 A.2 新查第 14 条已登记，另属加固项）。

## 3. 修法（两处，不扩面）

**(a) 删除手写的 `_AppEmbedder`，改用内核 `LocalFnEmbedder`**（`agent_core/memory/embedder.py:296`）。
该类的 docstring 自述用途就是这件事：「适配宿主自有 embedding 函数…宿主只需提供函数与声明 dim」，
并附带 L2 归一化（与内置提供方一致，保证余弦相似度语义）——手写的旧适配层**两者都没做**。
⇒ 属 AGENTS.md「单一实现」，不是新增抽象。

**(b) `embed_memory` 保持 sync 签名，但走内核同步入口。**
不能改成 async 的理由（契约实测）：`memory_backend.py:237` 以 `PgMemoryStore(pool, embed_memory)`
把函数对象作为**同步回调**注入，且上表四处用例以 sync lambda 替身化——改签名会同时动注入面与
既有用例，属为修两处缺陷而扩面。
也不能用 `LocalFnEmbedder.embed()`（其 sync 入口内部是 `asyncio.run`，**在已运行的事件循环里必死锁**，
该类 docstring 自己写明了这点；而两个调用点都在 `async def` 内）。
⇒ 正确落点：在 `rag/embed.py` 增加一个 **sync 入口**，复用同模块的 `_sync_env()` 与
`EMBEDDING_REQUIRE_REAL` fail-fast 护栏（护栏逻辑不得在 memory_backend 再抄一遍），
最终 `provider.embed([text])[0]`。这与联邦侧 `semantic_memory.py:59` 的同形双胞胎
（`get_embedder().embed([text])[0]`）取向一致；差异仅在于 app 侧必须继续经过 `_sync_env()`，
否则 app 的 `embedding_*` 配置不再映射给内核，维度会与 `memories` 表错位。

## 4. 验收

1. 新用例（进 `applications/agent_server/tests/`，属 app 层集成套件）：**不打替身**，
   直接调 `memory_backend.embed_memory("…")`，断言返回长度 `== settings.vector_dim`；
   并断言 `remember_typed` / `recall_typed` 在真实 embed_memory 下不抛 TypeError。
   另钉一条非空洞性：`_AppEmbedder` 旧路径的 `dim=` 调用形态不得再出现在仓里（grep 判据）。
2. 既有四处替身用例**保持不动**（不得为凑绿改它们）；它们验的是归属/隔离逻辑，与本缺陷正交。
3. `uv run --with ruff ruff check .` + `uv run python scripts/lint_architecture.py` 绿；
   受影响 session（根 `tests/memory`、`tests/governance`、agent_server 应用层）全绿。
4. 线上反证：重建分发后，`/query` 一次真实请求的日志里**不再出现**
   「类型感知召回失败 / embed_texts() got an unexpected keyword argument 'dim'」。
   以 `kubectl logs` 实际输出为准，不凭"代码已改"宣称生效（演示版风险 8 的同一条纪律）。

## 5. 排期

不新开天数：随演示版 D2（健康检查补全）同批改代码、搭 D1 的那次构建上线。
若模型密钥 403 未解除，本修的**线上反证（验收 4）无法完成**，代码与用例可先行合入并如实标注为
「本地/CI 已验，真集群反证待密钥恢复后补」。
