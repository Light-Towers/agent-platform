# 技术债务：通用服务改名后 env var 统一重命名

> 创建：2026-09-22
> 状态：仓库内已完成（2026-09-22）；126 服务器部署脚本待同步（用户 2026-09-23 部署）
> 前置：通用服务改名已完成（zhanggui-zhiku → knowledge-service / wenda-data-agent → nl2sql-service）

## 背景

通用服务改名已完成（目录 + Python 包 + import + pyproject + uv.lock），但**环境变量名**仍保留旧名，属部署契约层，重命名为 breaking change，需协调部署。

## 待重命名 env var

### 联邦网关（agent_federation）

| 旧名 | 新名 | 用途 | 引用位置 |
|------|------|------|---------|
| `WENDA_DATA_AGENT_URL` | `NL2SQL_SERVICE_URL` | nl2sql-service 地址 | `agent/config.py:55`, `.env.example:45`, `README.md:44`, `eval/run-all.py:162` |
| `ZHIKU_API_URL` | `KNOWLEDGE_SERVICE_URL` | knowledge-service 地址 | `agent/config.py:61`, `api/server.py:42,68`, `tools/zhiku_tools.py:25,47,103`, `.env.example:2`, `docker-compose.yml:13`, `README.md:45`, `eval/run-all.py:172` |
| `ZHIKU_API_KEY` | `KNOWLEDGE_SERVICE_KEY` | knowledge-service 鉴权 Key | `.env.example:3`, `README.md:45` |

### knowledge-service 内部

| 旧名 | 新名 | 用途 | 引用数 |
|------|------|------|--------|
| `ZHANGUI_API_KEY` | `KNOWLEDGE_API_KEY` | 鉴权 Key | config.py + tests + benchmark |
| `ZHANGUI_RATE_LIMIT_PER_CLIENT` | `KNOWLEDGE_RATE_LIMIT_PER_CLIENT` | 限流 | config.py |
| `ZHANGUI_RATE_LIMIT_GLOBAL` | `KNOWLEDGE_RATE_LIMIT_GLOBAL` | 限流 | config.py |
| `ZHANGUI_RATE_LIMIT_WINDOW_S` | `KNOWLEDGE_RATE_LIMIT_WINDOW_S` | 限流 | config.py |
| `ZHANGUI_MAX_HISTORY_ROUNDS` | `KNOWLEDGE_MAX_HISTORY_ROUNDS` | 历史轮数 | config.py |
| `ZHANGUI_MAX_BODY_BYTES` | `KNOWLEDGE_MAX_BODY_BYTES` | 请求体上限 | config.py |
| `ZHANGUI_RETRIEVAL_YAML` | `KNOWLEDGE_RETRIEVAL_YAML` | 检索配置路径 | conf/*.py + tests |
| `ZHANGUI_RERANK_YAML` | `KNOWLEDGE_RERANK_YAML` | 重排配置路径 | conf/*.py + tests |
| `ZHANGUI_SERVICE_NAME` | `KNOWLEDGE_SERVICE_NAME` | tracing 服务名 | .env.example |
| `ZHANGUI_TRACE_ENABLED` | `KNOWLEDGE_TRACE_ENABLED` | tracing 开关 | .env.example + test_tracing.py |

## 风险

- **部署 breaking**：所有 `.env` 文件、docker-compose、CI workflows、部署脚本中的 env var 名需同步更新
- **向后兼容窗口**：可考虑同时读旧名+新名（`os.getenv("NL2SQL_SERVICE_URL") or os.getenv("WENDA_DATA_AGENT_URL")`），但增加复杂度
- **建议**：一次性重命名 + 部署文档更新，不走兼容窗口

## 验收标准

- [x] 所有 env var 名统一为新名
- [x] `.env.example` / docker-compose.yml / README 更新
- [ ] 部署脚本（126 服务器）更新（用户 2026-09-23 部署）
- [x] 受影响包单元测试通过（knowledge-service 221 passed / agent_federation 114 passed，2026-09-22）；全量 10 session 待 CI
