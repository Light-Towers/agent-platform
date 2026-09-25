# 桶 B 降量勘察结论（2026-09-24）—— 承接 P2 后的复验

> P2 为 5 应用补齐统一 `Exception→500` 脱敏 handler（前提 ①），解锁了"删冗余 except → 冒泡 handler"（桶 B）的路径讨论。本轮对 **6 应用请求路由层**做逐站勘察 + 三重前提复验，结论：**桶 B 实际可安全删点趋近于 0，不建议为降指标动手。** 记录证据防复发（勿再盲删承重 handler）。
>
> 关联：`plan-p2-unified-exception-handlers-2026-09-24.md` §9、`plan-p0-4-blind-except-real-reduction-2026-09-24.md`、`p0-execution-retrospective-2026-09-24.md` §3。

## 1. 三重前提（判据）

删某处 `except Exception` 交全局 handler，须同时满足：
- ① 目标应用注册 `add_exception_handler(Exception,...)`——**P2 后 5 应用已满足**；
- ② 异常发生在**HTTP 请求调用栈内**（后台 asyncio 任务 / SSE 生成器 / WebSocket **全局 handler 结构上接不到**）；
- ③ 兜底 handler 的**日志上下文不弱于**原 `logger.exception(msg, ...)`，且响应形状变更不破坏对外契约。

## 2. 全仓 `except Exception`（请求路由层）分类

| 站点 | 类别 | 判定 |
|------|------|------|
| federation `server.py` 92/102/112 | lifespan 启停非致命兜底 | **C 保留**（非请求栈，启动容错） |
| federation `server.py` 228 | **后台 asyncio 任务** `logger.exception` | **C 必留**（前提②不成立，删则任务静默丢异常） |
| federation `server.py` 265/279/295 | 文件下载/列举 legacy `return {"error":...}` | **C 保留**（200+error 是该端点契约，删→500 改形状；且非纯 rethrow） |
| federation `server.py` 363 | **WebSocket** handler + `manager.disconnect` 清理 | **C 必留**（WS 非 http，前提②不成立；含资源清理） |
| ks `import_router` 130/243 | 导入后台任务 / MinIO 上传局部降级继续 | **C 必留**（后台 + 承重部分降级） |
| ks `query_router` 114/157 | health 探针 / stream 图执行兜底 | **C 必留**（探针降级 + 流式） |
| ks `query_router` **352** | 纯请求栈 `except Exception: log; raise HTTPException(500,"获取会话历史失败")` | **唯一近似 B，但不值得**（见 §3） |
| agent_server `query_router` 76/149/255/278/297/332/342/357/372 | scheduler/status/cost/context **best-effort 降级 `warning + 继续`** | **C 必留**（删则把"容错继续"变"整请求崩溃"） |
| agent_server `query_router` 312 | **SSE 生成器** 顶层 `logger.exception + yield _sse error` | **C 必留**（生成器已开流，前提②不成立） |
| nl2sql `query_router` 31 | `return SqlQueryResponse(fallback=True)` 结构化降级 | **C 保留**（200+fallback 是联邦契约，删→500 破坏契约） |
| exhibition `skill_loader` **107** | `/api/chat` `except: return JSONResponse({error:str(e), llm_config})` | **C 保留**（dev 控制台**有意的**错误呈现，llm_config 为调试信息；直出 `str(e)` 是已知 N2 类瑕疵，宜单独窄化修泄露而非删整块，见 §4） |
| exhibition `server.py` 187 | `logger.exception(request_id) + raise HTTPException(500,{code,message,request_id})` | **C 保留**（业务 request_id 来自 ExecutionContext 非 OTel，前提③不成立；detail 是结构化契约） |

## 3. ks:352 为何"不值得"

- 客户端**当前已拿脱敏 500**：ks 注册了 `StarletteHTTPException` handler，5xx → `_sanitize_detail` 通用文案，`detail="获取会话历史失败"` 本就被替换。删 except 让原生异常冒泡到 `Exception` handler，**响应信封几乎不变**（仍 `{code:INTERNAL_ERROR, msg:通用, request_id}`）。
- 唯一差异：日志标签从 `"history error for session %s"` 退化为 handler 通用 `"Unhandled exception %s %s"`（method+**path**，path 含 `/history/{session_id}` 故 session_id 仍可辨）。
- 净收益 ≈ 0，净损失 = 一条语义化日志标签。**不做**（与既定"桶 B 收益边际"一致）。

## 4. 真正值得做的（若要推进，另立小轮）

勘察顺带暴露 2 个**与桶 B 无关**的小瑕疵，宜作为独立窄化/安全项处理，**不属于本轮降量**：
- exhibition `skill_loader:109` `{"error": f"...{e}"}` 直出异常串（N2 类）——宜改固定文案 + request_id，或窄化 except 类型；**勿删整块**（llm_config 呈现是有意的）。
- 若后续要统一 5 应用 5xx 对外信封（P2b / D-2=B），需先审计前端/网关消费者，再连带重估上述站点。

## 5. 结论

桶 B 在本仓**已勘察闭合：无安全可删的降量点**（唯一候选 ks:352 净收益为负）。各应用盲捕获绝大多数是**后台/流式/WebSocket（前提②）或承重部分降级/契约形状（前提③）**，删之有害。**下一步建议转向有实质价值的 P1 项**（契约收敛 / knowledge_lifecycle / Alembic 迁移 / 多租户 ACL），而非在桶 B 上空转。
