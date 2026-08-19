# kefu-service

客服智能体服务（从 `legacy` 迁移到 deepagents + LangGraph，Phase 7 收尾产物）。

## 定位

- 9 种命令 → LangGraph 意图路由；3 个 Flow → LangGraph 子图；GraphRAG → 知识库检索子 Agent。
- 已接入 `shared-schemas` 统一契约，对外暴露 **Agent Protocol 兼容** 接口。

## 运行

```bash
# 安装（在仓库根目录，editable 安装共享内核）
pip install -e ./agent-core -e ./shared-schemas -e ./kefu-service

# 启动（默认 :8003）
uvicorn kefu_agent:app --host 0.0.0.0 --port 8003
```

## 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/invoke` | Agent Protocol 兼容入口（接受 `graph_id` + `input`，返回 `QueryResponse`），供 `agent_federation` 联邦网关远程直连 |
| `POST` | `/api/messages` | 保留的 `legacy` 兼容入口（旧契约），内部复用统一核心逻辑 |
| `GET` | `/health` `/health/live` `/health/ready` | 健康探活 |

## 网关接入

`agent_federation/agent/config.py` 中：

- `KEFU_USE_ADAPTER=false`（默认）→ 直连本服务 `KEFU_SERVICE_URL`（默认 `http://localhost:8003`）的 `/invoke`。
- `KEFU_USE_ADAPTER=true` → 经 `kefu-adapter`（`:8002`）兼容路径。

> 历史说明：`kefu-adapter` 转换层已于 2026-08 移除（无调用方），外部 `legacy` 退役由运维执行。
