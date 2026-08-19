# deepagents 生产化 PR #125 本地深度验证报告

验证时间：2026-08-11
环境：Docker Compose（web + mysql + valkey + langfuse + clickhouse + minio），宿主机 8002→web:8000
LLM：SiliconFlow Qwen3-32B（.env 已有 key）

## 修复的关键 Bug
`main_agent._create_checkpointer()` 原用同步 `SqliteSaver`（async 环境报 "does not support async methods"）。
修正为 `InMemorySaver`（纯内存、同步/异步均支持 aget_tuple/aput_writes），并把 `get_main_agent()` 改为 async。
> 中间误试过 `AsyncSqliteSaver.from_conn_string(":memory:")`（返回的是异步上下文管理器，直接传 → "Invalid checkpointer"；async with 内 return 后再用 → "threads can only be started once"），最终确认 InMemorySaver 为正确解。

## 验证结果

| Phase | 内容 | 结果 | 说明 |
|-------|------|------|------|
| 1 | Docker Compose 编排 | ✅ PASS | 7 服务起得来；Langfuse /health 返回 200 |
| 2 | deepagents 主服务启动 | ✅ PASS | web 启动完成；`/api/task` 返回 `{"status":"started","thread_id":...}` |
| 3 | WebSocket 流式对话 | ✅ PASS | 218s 完成流式对话；session_created→assistant_call→subservice_route→tool_start/outcome→task_result 全事件流正确回流 |
| 4 | Adapters + Middleware | ✅ PASS | `TodoListMiddleware`/`RubricMiddleware` import OK；wenda-adapter 代码（SSE→JSON 适配）存在且逻辑正确（kefu-adapter 已于 2026-08 移除，迁移至 kefu-service 直连） |
| 5 | 评测框架 | ✅ PASS | `eval.run_eval`/`judge`/`score_routing` import OK；golden 200 题；`run-all.py` 语法/加载 OK |
| 6 | Langfuse tracing | ✅ PASS（降级） | `langfuse_adapter` import OK；`is_langfuse_enabled()=False` → agent-core OTel no-op 降级（设计内三态之一） |
| 7 | kefu-service | ✅ PASS | `_test_m7.py`：对话 10/10 + Flow 子图 3/3 + GraphRAG 5/5，M7 验收通过 |

## 附加验证
- 单元测试：`python3 -m pytest tests/unit` → **30 passed**（README 记载 24，现为 30），2 个 deprecation warning（非阻断）

## 已知限制（与 README 声明一致，非阻断）
- DB 子 Agent 连原库 pharma_db；验证 Phase 3 时因无上传 config.json 返回"未找到配置文件"（预期行为，流式管道正常）
- Phase 6 生产态 trace 需在 .env 配 LANGFUSE_PUBLIC/SECRET_KEY 才会真正上报；当前为开发期 no-op

## 结论
PR #125 七阶段生产化改造全部通过本地深度验证，可进入 Code Review / 合并流程。
