# 方案 → 修复：`/history` 调的是 checkpointer 上不存在的方法，精确回忆恒为空

日期：2026-10-10　类型：本轮交付的关键缺陷（底线 7 / 环节 5 的读侧）
状态：短方案（沿用缺陷 #3 的处置方式：出短方案后修），已随本方案落地修复

## 1. 发现过程（不是读代码读出来的，是浏览器里跑出来的）

本机真实 uvicorn（`API_KEY` 已注入、无 LLM 密钥）+ 真实浏览器打开只读控制台，右栏点"读取本会话历史"：
屏上显示"该会话桶下暂无已落库的对话原文"。但同一进程里 `aget_tuple()` 直接读得到 4 条消息：

```
checkpointer type: InMemorySaver
channel keys: ['messages']
messages: [('human','第一个问题'), ('ai','（无 LLM 模式）…'), ('human','第二个问题'), ('ai','（无 LLM 模式）…')]
GET /history -> 200 {"thread_id":"tenant-default","count":0,"items":[]}
```

服务日志同时打出被吞掉的真实异常：

```
ERROR [agent_server.memory.recall_exact] 精确回忆：读取 thread=tenant-default 历史失败
AttributeError: 'InMemorySaver' object has no attribute 'alist_messages'
```

## 2. 根因（三条硬读数）

| # | 事实 | 位置 |
|---|---|---|
| 1 | `get_thread_history()` 调 `checkpointer.alist_messages(...)`，而内核工厂产出的两种 checkpointer（`InMemorySaver` / `AsyncPostgresSaver`）**都没有这个方法**（实测 `hasattr(...,'alist_messages') == False`，只有 `alist`/`aget_tuple`/`aput`） | `applications/agent_server/memory/recall_exact.py:65` |
| 2 | 外层 `except Exception → logger.exception → return []`，把 AttributeError 变成"空历史 + HTTP 200" ⇒ 接口永远"成功"，永远为空 | 同上 `:68-70` |
| 3 | **同仓的正确写法早就存在**：`thread_persist.read_thread_messages()` 用 `aget_tuple` + `channel_values.messages`，且被 /query 主链路验证可用（探针读到的 4 条就是它这条路径写的） | `applications/agent_server/memory/thread_persist.py:31-37` |

为什么一直没被发现：`/history` 与 `alist_messages` 在测试里**零覆盖**（`grep -rln "alist_messages\|/history" tests applications/agent_server/tests` 无命中）；即使有覆盖，用带 `alist_messages` 的假 checkpointer 也照样绿 —— 与缺陷 #3（`embed_texts` 旧签名 + 4 处 monkeypatch）是同一个失效模式：**代码照着一份不存在的 API 契约写，宽 except + mock 把错误读数盖成"正常为空"**。

影响：底线 7（会话历史从库里读、右栏能翻出原话）与 1.2 基线里"历史回查"这一接口，**在任何模式下都不成立**。多轮记忆本身没坏（LangGraph 按 thread_id 自动累积，探针已证），坏的是"把原文翻回给人看"这一步。

## 3. 修法与取舍

| 选项 | 做法 | 判断 |
|---|---|---|
| **A（采用）** | 读侧收敛到仓里已有的正确姿势：`aget_tuple` + `channel_values.messages`；**去掉宽 except**，读取失败让异常上抛，由路由映射成 503 | 单一实现 + 不新增抽象；并把"空"与"读失败"这两种语义分开（方案的底线 7 明确要求不许拿空数组冒充"没有历史"） |
| B | 换成 `alist()` 逐 checkpoint 回溯，以拿到每条消息各自的时间戳 | 本版**不做**：现在没有任何写入方给消息带 `additional_kwargs.created_at`，逐条时间本来就没有数据；为展示而造时间戳会违反底线 5。页面也不渲染时间列，无此需求 |
| C | 给 checkpointer 补一个 `alist_messages` 适配层 | 不采用：给不存在的上游 API 造兼容层，等于把错误契约留在仓里 |

配套（都在"改错了也不报错"这一类上）：
- `thread_persist.py` 模块 docstring 里那句"读：`checkpointer.alist_messages(thread_id)`"是**过期描述**，一并订正 —— 它正是这次误导的来源之一。
- 用例必须用**真实 `InMemorySaver`**，并加一条反向用例：读取失败时**必须上抛**而不是返回 `[]`（否则修了也守不住）。
- `/history` 的 HTTP 级用例走真实 app（无 LLM 密钥也能跑：`/query` 的"无 LLM 模式"回答同样落进 checkpoint）。

## 4. 验收

1. `get_thread_history(真实 InMemorySaver, thread)` 返回追加过两轮后的 4 条原文，role 归一化为 user/assistant。
2. HTTP：带密钥 `POST /query` 一轮 → `GET /history?session_id=<任意客户端值>` 返回 `thread_id == "tenant-default"` 且 `count >= 2`。
3. 反向：给一个没有 `aget_tuple` 的替身，`get_thread_history` 必须抛异常；`/history` 必须 5xx 而不是 200+空。
4. `keyword` 过滤与 `limit` 取尾部 N 条的既有语义不变。

## 5. 遗留（不在本次修）

`recall_exact.search_in_thread()` 目前无调用方；`/history` 在 checkpointer 缺失时返 503 的分支已存在，保持不动。意图路由绕过统一 embedding 提供方另见
`plan-intent-embedder-bypasses-provider-2026-10-10.md`。
