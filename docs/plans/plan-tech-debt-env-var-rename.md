# 技术债务：通用服务改名后 env var 统一重命名

> 创建：2026-09-22
> 状态：仓库内已完成（2026-09-22）；126 服务器部署脚本待同步（用户 2026-09-23 部署）
> **2026-10-16 对码修订**：上面两格对**联邦网关三键 + KS 八个 `ZHANGUI_业务` 键成立**，对**观测两键不成立**
> （`ZHANGUI_SERVICE_NAME` / `ZHANGUI_TRACE_ENABLED` → `KNOWLEDGE_*` 是无读取方的空改名，详见「knowledge-service 内部」表注①）。
> 现口径：**13 项中 11 项真完成、2 项以改用内核中性键 `AGENT_CORE_*` 收尾**（14 处出现 / 8 个文件，2026-10-16 已修 + 钉桩）。
> 11 项的判据 = 逐个 `git grep -w <新名> -- '*.py'` 有读取方（联邦 3 项：3/4/1 个 py 文件；KS 业务 8 项：各 1~3 个）；
> 本服务 `config.py` **无 `env_prefix`**，键名按字面读 ⇒ 这两项的空改名不存在"前缀拼出来所以 grep 不到"的豁免。
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
| `ZHANGUI_SERVICE_NAME` | `KNOWLEDGE_SERVICE_NAME` ① | tracing 服务名 | .env.example |
| `ZHANGUI_TRACE_ENABLED` | `KNOWLEDGE_TRACE_ENABLED` ① | tracing 开关 | .env.example + test_tracing.py |

> ① **2026-10-16 对码更正（这两行的"已完成"当初就不成立）**：这两项改名是**纯文本替换**，未核对读取方。
> 观测逻辑的读取方早在 `426e2519`（2026-08-21，WS-1~WS-8 内核架构优化）就已移到 `agent-core` 的中性键
> `AGENT_CORE_SERVICE_NAME` / `AGENT_CORE_TRACE_ENABLED`（`packages/agent-core/agent_core/tracing.py:42-43`），
> 且 `6655fa69`（2026-09-22）时本服务 `core/tracing.py` 已是纯 shim（`getenv` 零命中）。
> ⇒ `37d93427`（2026-09-23）产出的两个 `KNOWLEDGE_*` 键名**自诞生起无任何读取方**，但被写进了
> `.env.example`、`Dockerfile`、`README`、`benchmark/README`、`docker-compose.yml`、`docs/ops-lessons-learned.md`、
> `docs/verification-checklist.md`（含一处 dated 记录正文）与单测 `delenv` —— 共 9 处、8 个文件。
> 危害形状：运维照文档设 `KNOWLEDGE_TRACE_ENABLED=true`，观测面**静默不开**（"以为开了、其实没开"）。
> 影响面计数（口径：`git grep -o` 对 `37d93427`~HEAD 提交树、仅 `applications/knowledge-service/`，
> 计**出现次数**而非行数）：**14 处、分布在 8 个文件** —— `.env.example` 3、`docs/verification-checklist.md` 2、
> `docs/ops-lessons-learned.md` 2、`docker-compose.yml` 2、`tests/unit/test_tracing.py` 2、`Dockerfile` 1、
> `README.md` 1、`benchmark/README.md` 1。
> 处置：14 处全部改用内核真读的 `AGENT_CORE_*`（`verification-checklist` 的 dated 记录正文按留档纪律保留、只加订正注）；
> 钉桩用例 `applications/knowledge-service/tests/unit/test_tracing.py::test_env_example_observability_keys_are_read_by_code`。

## 风险

- **部署 breaking**：所有 `.env` 文件、docker-compose、CI workflows、部署脚本中的 env var 名需同步更新
- **向后兼容窗口**：可考虑同时读旧名+新名（`os.getenv("NL2SQL_SERVICE_URL") or os.getenv("WENDA_DATA_AGENT_URL")`），但增加复杂度
- **建议**：一次性重命名 + 部署文档更新，不走兼容窗口

## 验收标准

- [x] 所有 env var 名统一为新名（**2026-10-16 计数修订**：13 项里 11 项如此；观测两键属空改名，已另行按表注① 处置）
- [x] `.env.example` / docker-compose.yml / README 更新
- [ ] 部署脚本（126 服务器）更新（用户 2026-09-23 部署）
- [x] 受影响包单元测试通过（knowledge-service 221 passed / agent_federation 114 passed，2026-09-22）；全量 10 session 待 CI
