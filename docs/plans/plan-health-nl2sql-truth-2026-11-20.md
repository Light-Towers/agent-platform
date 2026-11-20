# 健康页：把退役的 sql_backend 假灯换成问数真值

> 状态：代码完成 + 静态全绿，待部署。触发（用户 2026-11-20）：平台 /health 的 `sql_backend=None` 是退役假灯（ADR-0011，恒 null），健康页却把它渲染成"未装配"警示圆，误导用户以为问数坏了。用户拍板：换成真值——展示 nl2sql-service 的 /ready。

## 实取事实
- 平台 `/health`：`nl2sql=True`（注册意愿位）、`sql_backend=None`（退役假灯，恒 null）。
- nl2sql-service `/health`：`sql_backend="postgres"`（方言真值）。
- nl2sql-service `/ready`：`pools={meta:ok, dw:ok}`（连接池健康真值）。
- 真跑问数成功（订单表记录数=6、金额统计 1468.49）⇒ 问数链路确实健康。
- 前端 `health.ts:21` 把 sql_backend 列在"数据面与工具"组，`HealthView.vue` 对 null 渲染警示圆 + 说明"问数数据面方言（由持业务库的服务上报）"。

## 关键约束（架构）
- 平台 `/health` 是**免鉴权探针路径，timeoutSeconds=1**（health_router.py:27-30）：不能在该路径同步拉 nl2sql-service，否则探针连错3次 → 容器被 SIGKILL。
- ⇒ 不能在平台 `/health` 里聚合 nl2sql 真值。

## 方案（用户拍板：展示真值）
1. **平台加独立代理端点** `GET /health/nl2sql`（非探针路径，不受 1s 约束，但免鉴权同 /health）：内部 `httpx` 拉 nl2sql-service 的 `/health` + `/ready`，聚合返回 `{sql_backend, pools, ok}`；失败降级为 `{ok:false, error}`。复用 kb_router 的代理模式（超时 + 异常捕获）。
2. **前端 health.ts**：从 `HEALTH_LAMP_GROUPS` 移除 `sql_backend`（退役字段不再当灯）；新增读取 `/health/nl2sql` 的 `nl2sqlDetail`（方真值 + 池健康）。
3. **HealthView.vue**：在"数据面与工具"组把 sql_backend 那盏替换为一段真值展示——方言 `postgres` + 连接池 meta/dw 状态（复用 `.ry-tag` 或 `.dot` 形状），说明改为"问数数据面（nl2sql-service 真值）"。
4. **check-tokens 门禁**：health.ts 字典是断言6的派生源（30字段双向比对），移除 sql_backend 后期望集自动从源派生，门禁会自动跟上（期望集只从源读，不写死 30）——需确认 check-tokens 的 health 字段双向比较逻辑不被破坏。

## 实现
- 后端 `health_router.py` 加 `GET /health/nl2sql`（免鉴权代理端点，不在探针路径）：拉 nl2sql-service 的 /health+/ready 聚合 `{ok, sql_backend, pools}`，失败降级 `{ok:false, error}`。单测 4 条（真值聚合/池故障/未配置/网络错误）。
- 前端 health.ts：sql_backend 保留登记（满足 check-tokens 断言6 双向比对——后端 schema 仍用它给 nl2sql-service 上报）但说明改"已退役，真值见下方"；cache_degraded_reason/dependencies 说明改友好；加 `getNl2sqlHealth()`。
- HealthView.vue：加"问数数据面"真值面板（方言+连接池 ok/错误）；sql_backend 灯改中性 muted 方块（不再警示圆）。

## 验证
- ✅ 静态全绿：34 后端测试 + ruff + 前端 typecheck/lint/6门禁/check-events/check-ui-consistency。
- ⏳ 待部署 + 真浏览器验证：健康页显示"问数方言 postgres / 连接池 meta=ok dw=ok"，不再有警示圆。
- 平台 Pod 探针不受影响（新端点不在 /health 路径）。

## 边界
- 不改 nl2sql-service（它已正确上报真值）。
- 不动平台 /health 的其它字段。
- 代理端点失败降级（nl2sql-service 挂了要显示明确错误，不是静默 null）。
