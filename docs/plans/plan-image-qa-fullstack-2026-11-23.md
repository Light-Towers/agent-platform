# 图片全链路：切分可见 + 会话传图提问 + 回答回显图片

> 状态：Proposed（待拍板）｜依据：2026-11-23 实取代码 + subagent 六点探查（路径:行号）｜触发：用户「切后文档看到图片 + 会话以图片形式问答 + 回答内容也有图片数据」
> 关联：`plan-image-citation-e2e-2026-11-23.md`（回答回显逻辑已实现部署，本方案收尾其 URL 阻断）｜设计原则：`docs/principles/README.md` P3

## 0. 三个目标与现状（实取）

| 目标 | 现状 | 真正阻断 |
|---|---|---|
| ① 切后文档看到图片 | chunk.content 含 `![摘要](MinIO URL)`，切片明细 `KbUpload.vue:424` 用纯文本 `<code>` 显示 | URL 是 `http://minio:9000`（集群内 DNS，浏览器不可达）+ 渲染位置不对 |
| ② 回答回显图片 | **已实现并部署**（rich 事件 + ImageStrip，`plan-image-citation-e2e` 刀1-4） | 同①：MinIO URL 浏览器不可达 |
| ③ 会话传图提问 | **完全没有**：agent_server 无图片上传端点、无 VL 模型配置、会话链路无图片字段（`subagent` §1-3） | 要从零建多模态输入链路 |

**共同底座**：图片 URL 浏览器不可访问。① ② 只差这个；③ 独立于它（会话上传的图另存，不依赖知识库图片 URL）。

**实施期订正（subagent 深挖 2026-11-23）**：
- **③ 完全不依赖底座**：会话传图走 `上传→image_ref→后端取字节→data URI→VL 模型`，全在集群内闭环（VL 是外部推理服务，必须用 data URI 而非 cluster 内 URL，KS `node_md_img.py:157,176` 同款）。所以①②（底座）与③（会话传图）**可解耦、并行推进**。
- **③ 存储推荐 PG bytea 表而非 MinIO**：agent_server 镜像无 minio 包（`Dockerfile:110`）、无 MinIO 凭证（只在 KS Secret）；选 MinIO 要改 Dockerfile + 注入 Secret（部署侧，网络断时做不了）。PG bytea 零新增依赖/凭证、三副本共享，设 5MB/张 + TTL 清理即可。
- **③ 最终合成点**：生产默认 deterministic 在 `planners/deterministic.py:387`；带图请求强制路由到 deterministic（开关 `image_qa_force_deterministic=True`），graph 两条路径不动、无图请求逐字零回归。
- **③ 缓存键**：不改内核，把图片签名塞进现有 `kb_scope` 字典（get/set 两处同步），或带图时整段跳过缓存。

## 1. 病根（实取）

- `node_md_img.py:306-310`：`base_url = f"{protocol}://{minio_config.endpoint}/{bucket}"`，`endpoint=minio:9000`（`minio_config.py:20`，生产实取）。MinIO 是 ClusterIP（`10.100.236.129:9000`，无 NodePort/Ingress），`minio` 主机名只集群内可解析。
- `minio_config.endpoint` **同时用于 MinIO 客户端连接**（`minio_utils.py:15`）和图片 URL 拼接——不能直接改成对外地址，必须拆分为"连接 endpoint（内）+ 对外 base URL（public）"。
- 桶默认私有（`MINIO_PUBLIC_READ=false`，`minio_utils.py:31`），匿名访问拿不到图。
- ② 的 adapter 白名单 `RICH_IMAGE_ALLOWED_HOSTS=minio`（生产），若对外 host 变化须同步，否则 `rich_answer_adapter.py:81` 拒。

## 2. 方案：一个底座 + 两条线

### 底座：让浏览器能访问知识库图片（服务①②，③不需要）

选一条（需拍板，见 §6 D1）：

- **A. MinIO NodePort + public base URL（推荐）**：MinIO Service 加 NodePort（如 30900），KS 新增 `MINIO_PUBLIC_URL`（如 `http://<节点IP>:30900`），`node_md_img.py:306-310` 改用它拼 URL（`object_name` 不变→桶内路径不变）。同步 `MINIO_PUBLIC_READ=true`（匿名只读，因浏览器带不了密钥）与 `RICH_IMAGE_ALLOWED_HOSTS` 新 host。历史文档需重传或用 URL 重写兜底。
- **B. agent_server 图片代理端点**：新增 `/img/{bucket}/{path}` 带鉴权代理到 MinIO，URL 写相对路径。**优点**：不开匿名桶、不用重传（可重写）；**代价**：新增后端端点 + 前端白名单调整，且代理要处理租户隔离。

> 安全提醒：A 开匿名只读后，**桶内所有图片公网可读**（知道 URL 即可），知识库图片可能含内部信息——这是 D2 决策，需你拍板。B 无此面。

### 线 1：切后文档看到图片（服务①）

- `KbUpload.vue` 的**切片明细**（:405-427）在 `<code>` 旁/下渲染缩略图条（复用 `ImageStrip.vue` 的轻量版），从 `chunk.content` 提取 `![](url)`，前端 scheme 二次校验（`sseReducer.ts:62` 的 `isSafeImageUrl`）。
- 并把上传后读数面板的 `previewImages` 数据也接到这里——让切分预览和历史文档都能看到图（现在只在上传后 status 在时有）。
- URL 可访问后（底座），缩略图自然显示。

### 线 2：会话传图提问（③，独立新功能）

四层全要新增（subagent §1-4 实证）：

1. **前端**：`ChatView.vue:223-283` composer 加图片选择按钮 + 预览缩略图 + 发送时把图片 POST 到新端点；`sse.ts` 请求体带 `context.images: [url]`（`QueryRequest.context` 已有该字段，`query.py:27`）。
2. **后端上传端点**：agent_server 新增 `POST /chat/upload-image`（multipart），图片存 MinIO（复用 KS 的 `fput_object` 模式或引入 minio 客户端），返回可访问 URL。**不触发知识库导入管线**（区别于 `/kb/uploads`）。
3. **会话携带图片**：`query_router.py:334-344` 把 `req.context.images` 注入 `PlannerContext`（新字段）/ graph state；prompt 构造处（`subagents/rag.py:65` 或 synthesizer）把图片构造为多模态 message（`HumanMessage(content=[{text}, {image_url}])`，照 `node_md_img.py:169-179`）。VL 模型配置：复用 KS 的 `VL_MODEL` 值（生产已配 Qwen3-VL-8B）在 agent_server 加同名配置。
4. **缓存键**：`query_router.py:98` `user_query_hash(req.query)` 只哈希文本 → 把图片签名纳入缓存键，避免同文不同图命中旧答案。

### 安全（强制）

- 上传图片：限制格式（jpg/png/webp）、大小、数量；租户隔离（存到 `tenant_id/{session_id}/` 前缀）。
- 图片 URL 一律过白名单（服务端 adapter + 前端 `isSafeImageUrl`），拒伪协议/外域。
- 会话上传走鉴权端点（登录令牌），不是匿名。
- 混合内容：若前端 HTTPS 而图片 HTTP，会被浏览器拦截——底座 URL 需与页面同协议或走相对代理（B 方案天然规避）。

## 3. 影响面

| 层 | 文件 |
|---|---|
| 底座(A) | MinIO k8s Service（gitignored，远端）、KS `minio_config.py`/`core/config.py`/`node_md_img.py`/`.env.example`、KS ConfigMap、agent_server `config.py`/`.env.example`/生产 ConfigMap |
| 线1 | `web/src/components/KbUpload.vue`、`ImageStrip.vue`（复用） |
| 线2 | `web/src/components/ChatView.vue`、`web/src/api/sse.ts`；agent_server 新上传端点 + `PlannerContext`/graph state/prompt + VL 配置；shared-schemas（如需新字段） |
| 安全/测试 | 上传端点鉴权 + 图片格式校验、缓存键含图片签名、多模态 prompt 单测、E2E |

## 4. 验收

1. 上传带图文档 → 切分明细 + 上传后读数都显示可点开的图片缩略图。
2. 会话上传一张图提问（如"这张图是什么"）→ LLM 用 VL 模型读懂图并回答。
3. 文字提问命中含图知识 → 回答区显示图片（② 复活，URL 可访问）。
4. 安全反证：外域/伪协议图片 URL 被拒；上传非图片/超限被拒；同文不同图不命中旧缓存。
5. 全量门禁 + 真环境 E2E。

## 5. 拍板结果（2026-11-23 用户「按推荐」）

- **D1（底座路线）**：**B**（agent_server 鉴权图片代理，安全、免重传、桶保持私有）。开匿名只读的 A 方案不采用（桶公网可读的安全债）。
- **D2（VL 模型）**：复用 `Qwen/Qwen3-VL-8B-Instruct`（生产已配）。agent_server 新增 `vl_model` 配置 + `build_vl_model()`，仅带图请求使用。
- **D3（历史文档）**：URL 重写兜底（前端把 `minio:9000/...` 改写走代理端点），免重传。
- **③ 存储（实施期新增决策）**：**PG bytea 表**（`chat_images`，5MB/张 + TTL），非 MinIO——避免改 Dockerfile/注入 Secret，网络断时也能纯本地推代码。
- **③ 路径范围**：只支持生产默认 deterministic，带图强制路由；graph 两路径不动、无图零回归（`image_qa_force_deterministic=True`）。

## 6. 刀次（每 PR <400 行）

1. 刀1（本地可做）：配置 + VL client（`config.py`/`agent/llm.py`/`main.py`/`.env.example`）+ 图片代理端点骨架 `api/image_router.py`（B 底座，MinIO 连接走 env 注入，真连通性待网络恢复验证）。
2. 刀2（本地可做，纯前端）：线1 切分明细缩略图 + ② 图片 URL 改写走代理（`KbUpload.vue`/`ImageStrip.vue` 复用）。
3. 刀3（本地可做）：③ 后端 —— PG `chat_images` 表 + 上传端点 `api/chat_router.py` + 图片注入 + deterministic 多模态合成 + 缓存键（subagent 设计报告 §3 标★的 5 文件 + 存储适配）。
4. 刀4（本地可做）：③ 前端 —— `ChatView.vue` 附件 UI + `context.images`（`sse.ts` 请求体）。
5. 刀5（需网络）：现网探测（agent_server→MinIO）+ 部署 + E2E + 安全反证 + 文档回写。

> 网络状态：2026-11-23 三台内网机器 SSH 不可达，刀 1-4 纯本地推进（typecheck/lint/pytest 可测）；刀 5 等网络恢复。

## 7. 与既有工作的关系

- ② 的回答回显逻辑（rich/adapter/ImageStrip）已实现部署，本方案只修其 URL 阻断，**不重写**。
- 本方案把 `plan-image-citation-e2e-2026-11-23.md` 列的"非目标：多模态推理"正式转为目标（会话传图提问）。
- 底座若选 A 开匿名只读，需登记安全债（桶公网可读）。
