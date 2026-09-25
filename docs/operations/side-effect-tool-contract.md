# Tool / Skill 副作用契约（v2）

> 适用版本：**v2（冻结前收尾）**。本文档**不引入任何新的 Runtime 能力**，仅把
> `agent_runtime/planner/durability.py` 中已有的 `SideEffectStore` / `IdempotencyStore`
> 抽象沉淀为 **Tool / Skill 开发者的工程契约**。
>
> 相关实现：
> - `SideEffectStore` / `InMemorySideEffectStore`（effectively-once 证据）
> - `IdempotencyStore` / `InMemoryIdempotencyStore` / `with_idempotency`（幂等缓存）
> - `ExecutionOwnershipStore.heartbeat(owner=必填)`（owner fencing）
>
> 语义边界总述见 `docs/ha/ha-durable-execution.md` §八。

---

## 1. 核心结论（先读这段）

- Runtime 保证 **at-least-once execution** 与 **effectively-once outcome**。
- **不承诺 Exactly-Once**。业务副作用的"恰好一次"必须由 Tool / Skill 自身负责。
- Runtime 只提供**幂等证据（idempotency marker）**，不提供业务副作用的原子性。
- v2 **不引入** 2PC / consensus / distributed transaction / transactional outbox 的强制实现。

---

## 2. `effect_key` 定义与唯一性语义

`SideEffectStore` 以三元组唯一标识一次副作用：

```text
effect_key = execution_id : step_id : effect_type
```

| 字段 | 含义 |
|---|---|
| `execution_id` | 一次完整执行的标识（UUID） |
| `step_id` | ExecutionGraph 中的节点 ID |
| `effect_type` | 业务副作用类型（如 `WRITE-ROW`、`SEND-EMAIL`、`skill:search`） |

语义约束（来自 `durability.py` H3 契约）：

- 同一 `(execution_id, step_id, effect_type)` **只能发生一次**。重复 attempt 的 `record()`
  调用经 `ON CONFLICT DO NOTHING`（或 InMemory 的 key 去重）被原子丢弃。
- 若一个 Skill 合法产生**多种**业务副作用（如 `WRITE-A` 与 `WRITE-B`），必须使用**不同的**
  `effect_type`，否则第二个会被错误地当成重复副作用丢弃。
- `effect_key` 是**审计证据**，不是业务副作用本身。它证明"B 接管后该 step 的副作用已落地"，
  避免 B 重复执行——但前提是业务副作用本身可安全重跑或自带幂等。

---

## 3. `idempotency_key` 定义、生成原则与生命周期

`IdempotencyStore` 契约（§9.2 Durability）：

```text
idempotency_key → 首次执行结果（缓存）
```

`with_idempotency(key, store, fn)` 语义：命中缓存直接返回，否则执行 `fn` 并缓存**成功结果**
（执行抛错不污染缓存，保证重试可重新进入）。

### 生成原则

| 原则 | 说明 |
|---|---|
| 业务语义稳定 | key 必须能唯一标识"一次业务意图"，而非一次网络请求。例如 `user:123:send-welcome-email:v1` |
| 包含版本 | 业务语义变更（如邮件模板大改）应改 key 中的版本段，避免旧缓存污染新意图 |
| 不要含随机值 | 随机值会使每次都 miss，幂等失效 |
| 跨副本共享 | 多副本场景必须注入共享后端（PG / Redis），进程内 store 仅限单进程/测试 |

### 生命周期

- **创建**：首次成功执行业务副作用前，先 `store.get(key)` 判断是否已处理。
- **命中**：返回首次结果，不再执行真实副作用。
- **失效**：由业务方策略决定（如 24h TTL、或显式 invalidate）。v2 不规定统一 TTL。
- **清理**：共享后端的 key 应由业务侧负责过期清理（v2 不在 Runtime 层做 GC）。

---

## 4. 哪些 Tool / Skill 属于"有副作用操作"

判断标准：**该操作是否对外部世界产生不可逆或可观测的变更**。

| 类别 | 示例 | 是否副作用 |
|---|---|---|
| 外部 HTTP / API 调用（写类） | 创建订单、发消息、改配置 | ✅ 是 |
| 消息发送 | 邮件、Slack / IM、短信、Webhook | ✅ 是 |
| DB 写入 | INSERT / UPDATE / DELETE 业务表 | ✅ 是 |
| 文件写入 | 落盘、对象存储上传 | ✅ 是 |
| 支付 / 计费 | 扣款、开票 | ✅ 是 |
| 只读查询 | GET 请求、SELECT、搜索 | ❌ 否（可安全重跑） |
| 纯计算 | 本地 transform、聚合 | ❌ 否 |
| LLM 调用（无外部写入） | 生成文本、摘要 | ❌ 否（除非把结果写外部） |

**原则**：只要 Tool 产生 ✅ 类效果，就必须按本文档第 6、7 节处理重复执行。

---

## 5. 外部副作用的幂等要求

| 副作用类型 | 推荐幂等策略 |
|---|---|
| 外部 HTTP / API（写） | 服务端支持 `Idempotency-Key` 头；或客户端用业务 key 去重 |
| 消息发送 | 消息体带 `idempotency_key`；消费端做去重表 |
| DB 写入 | 唯一约束 + `ON CONFLICT DO NOTHING`；或先 SELECT 再 INSERT |
| 文件写入 | 写前检查目标已存在（content-hash 比对），已存在则跳过 |
| 支付 / 计费 | **必须**服务端幂等（订单号唯一约束）；本地无法兜底 |

Runtime 的 `SideEffectStore` 记录**不能替代**上述业务幂等。它只解决"B 接管后不重复
`record()` 调用"这一层，不解决"真实 API 被重跑"那一层。

---

## 6. `record()` 与真实业务副作用**不是原子事务**

```text
业务副作用 ✔  →  record() ✘
      │
      ▼  进程 crash / 网络中断
B resume：checkpoint 无本 step、side_effects 无本 step
      │
      ▼  B 重跑 Skill  →  真实业务副作用 ×2
```

这是 **distributed side-effect 的经典 atomicity 问题**，单条 SQL 无法修复：

- `SideEffectStore.record()` 与业务副作用之间必然存在时间窗口；
- 窗口内崩溃 → 二者状态不一致 → B 无法区分"真的没执行"还是"执行了但没记录"。

**Runtime 的立场**：只提供 `record()` / `has()` 作为**幂等证据**，把"真实副作用是否可重跑"
的责任交给 Tool / Skill。强制 exactly-once 需要业务侧 `idempotency_key` 或 `transactional outbox`。

---

## 7. 为什么 Runtime 只提供 at-least-once + 幂等证据

- **at-least-once**：崩溃重跑是 durable execution 的固有属性，无法消除（你也想不出比
  "重跑未完成 step" 更安全的恢复方式）。
- **effectively-once（系统级结果）**：当每个业务副作用都自带幂等边界时，多次 attempt 的
  最终外部状态与单次执行一致。
- **不承诺 Exactly-Once**：要实现真正的 exactly-once，需要 2PC / consensus / distributed
  transaction，会把 v2 重新搞成一个分布式事务系统——这是 v2 明确避免的架构方向。

结论：**v2 的契约是"重复执行会发生，但业务副作用必须能安全承受重复"**。

---

## 8. Tool / Skill 开发者如何处理重复执行

1. **先判幂等 key**：进入副作用前，用 `idempotency_key` 查 `IdempotencyStore`（或业务去重表）。
2. **真实副作用在 `record()` 之前完成**：`record()` 仅为审计/去重证据，不影响业务成败。
3. **同一 step 多种副作用 → 不同 `effect_type`**：避免 `effect_key` 冲突误删。
4. **副作用设计为可重入**：即使被 B 重跑，第二次执行要么命中幂等、要么对外部状态无新影响。
5. **只读 / 纯计算 Tool 无需处理**：天然可重跑。
6. **不依赖 Runtime 替你保证 exactly-once**：这是 v2 的明确边界。

---

## 9. transactional outbox（可选业务侧方案，**不实现**）

> 本节仅作**介绍**，v2 **不强制、不实现** outbox 模式。

Outbox 解决"业务写 + 副作用记录"的原子性问题：

```text
BEGIN TX
  写业务表
  写 outbox 表（pending 副作用）
COMMIT
-- 后台 worker 扫 outbox，投递副作用，成功后标记 done
```

若你的 Tool 需要强一致（如"DB 写入"与"发消息"必须同时成功或同时失败），可在**业务侧**
自行实现 outbox，Runtime 不介入。v2 不提供 outbox 框架。

---

## 10. v2 明确不引入

| 不引入项 | 原因 |
|---|---|
| 2PC | 把 v2 变成分布式事务系统，过度工程 |
| consensus（Raft/Paxos） | 超出 v2 边界，属 v3 |
| distributed transaction | 同上 |
| strict fencing epoch / generation | 属 v3（Issue #11 V2-1 之外） |
| 强制 transactional outbox | 业务侧自选，Runtime 不强制 |
| Docker 黑盒 HA | 可选增强，不阻塞 v2 发布 |

---

## Tool / Skill Review Checklist

审核新 Tool / Skill 是否满足本契约：

```text
Tool/Skill Review Checklist
============================
[ ] 1. 是否产生外部副作用？（参考第 4 节 ✅ 列表）
        - 否 → 无需后续条目
        - 是 → 继续

[ ] 2. 副作用是否用稳定的 idempotency_key 去重？
        - key 不含随机值
        - key 含业务意图 + 版本

[ ] 3. 外部系统是否本身支持幂等？
        - HTTP API：Idempotency-Key 头 / 服务端去重
        - DB：唯一约束 + ON CONFLICT DO NOTHING
        - 消息：消费端去重表

[ ] 4. 同一 step 的多种副作用是否用不同 effect_type？
        - 避免 effect_key 冲突误删

[ ] 5. record() 调用是否在真实副作用成功之后？
        - record() 仅作审计证据，不决定业务成败

[ ] 6. 重复执行是否安全（可重入）？
        - 第二次执行命中幂等 / 对外部无新影响

[ ] 7. 是否误以为 Runtime 保证 Exactly-Once？
        - 必须明确：v2 仅 at-least-once + 幂等证据

[ ] 8. 是否引入了 2PC / consensus / distributed transaction？
        - v2 禁止，必须移除或移至 v3 规划
```

---

*本文档为 v2 Release 收尾产物，配合 `docs/ha/ha-durable-execution.md` 与
`docs/operations/ha-runbook.md` 使用。不修改任何 Runtime 代码。*
