# 2026-11-25 图片 VL 语义摘要（历史文档重传）生产取证

> 所有读数绑 rev / 镜像 ID / Pod，2026-11-24~25 实取。基址 126（control-plane），构建机 241，worker 125/126。
> 方案：`docs/plans/plan-image-vl-summary-and-delete-confirm-2026-11-24.md`（D1 只重传、不加 C 兜底）。
> 强度分档：**已验证**（五字段齐、判据可复跑、读数绑 rev）。

## 1. 代码版本（字段 1）

| 项 | 值 |
|---|---|
| 本机 HEAD | `3ba346d3`（`fix(ks): 图片摘要 VL 模型不支持 enable_thinking`） |
| 前序 commit | `8d737252`（D2 删除确认）、`71875019`（切分预览内嵌） |
| KS 构建 rev | 241 `/opt/agent-platform` checkout `3ba346d3`，dirty=0（git bundle + fetch + checkout，未 push） |
| KS 镜像 ID | `52acc3a5164d`（`BUILD_RC=0 ELAPSED=6615s`，慢源 + `openai_agents` 版本回溯致 110min） |
| 三台回读 | 241 / 125 / 126 的 ctr containerd-k8s 均为 `52acc3a5164d0` ✓ |
| KS Pod | `ks-web-7b947cf4c6-9qk58`，imageID `sha256:52acc3a5164d0…` ✓ |

## 2. 根因实证（修复前负控）

重传第 1 份（fix 上线前）：`后端技术中阶` 7 张图 alt **全部**是写死的"图片描述"（`HAS_PLACEHOLDER True`）。
KS 日志（实取 `kubectl logs ks-web`）：

```
node_md_img.py:summarize_image:190 - 图片摘要生成失败（LangChain框架异常）：
Error code: 400 - {'code': 20015, 'message': 'Value error, current model does not support parameter `enable_thinking`.'}
```

根因：`knowledge_service/lm/lm_utils.py:36` 的 `get_llm_client()` 硬注入 `extra_body={"enable_thinking": False}`，
硅基流动 `Qwen/Qwen3-VL-8B-Instruct` 不支持该参数 → 400 → `summarize_image` 异常兜底成"图片描述"。
即：`IMG_SUMMARY_ENABLED=true`（生产复取确认）但摘要从未真正生成。

**这是负控**：证明"开关开了＝摘要有语义"不成立，必须先修 400 再重传。

## 3. 修复与验证

- `node_md_img.py`：新增 `_get_vl_client()`（`lru_cache` 单例，直接 `ChatOpenAI(model=lv_model, api_key, base_url, temperature=0)`，
  与 agent_server `build_vl_model` 同口径，**不带 enable_thinking**），`summarize_image` 改用它。
- 单测 `test_node_md_img_vl_client.py`：钉住 `model_kwargs` 无 `enable_thinking` + `model_name == lm_config.lv_model`。

**读数**（rev `3ba346d3`，`uv run pytest applications/knowledge-service/tests/unit/test_node_md_img_vl_client.py applications/knowledge-service/tests/unit/test_node_md_img_url.py -q`）：`5 passed`。
**口径**：KS 单测 2 项 + URL 斜杠测试 3 项，无 skip / deselected，缺 MinIO 依赖由 fixture mock 屏蔽。
**未覆盖**：未跑 KS 全量 session（本轮只碰一个函数，按分层验证策略取受影响子集）；真 VL 调用由生产重传取证覆盖（见 §4）。
**前置**：本机 venv + `OPENAI_API_KEY` 由 monkeypatch 注入假值（本机无 KS 密钥）。

## 4. 生产重传（字段 2/3：命令、读数、分母）

### 4.1 执行命令（不入库的临时脚本）

> 以下脚本为一次性取证脚本，**不入库**（跑完即 `rm`）；判据本体（逻辑与读数）在本节文字中完整保留，
> 他人可据此在 agent-server Pod 内复跑。

- 提权：`kubectl exec <postgres-pod> -- psql -U <u> -d <d> -c "UPDATE users SET is_admin=true, role='admin' WHERE id='e2eimgqa001'"`
- 重传（agent-server Pod 内，nohup 防 SSH 断连）：
  `Minio.get_object(kb-import-bucket, pdf_files/<日期>/<文档>.pdf)` → `httpx.post(http://localhost:8000/kb/uploads, files={files: (pdf)}, data={knowledge_id, status, enable_item_name_recognition=false})`
  → 轮询 `GET /kb/status/<task_id>` 至 `completed` → `MilvusClient.query(platform_doc_v3_bge_m3, filter='source_doc == "<文档>"', output_fields=[content,status,knowledge_id,created_at])`
  → 正则 `!\[([^\]]*)\]\(([^)]+)\)` 提取 image alt 统计。
- 降权（trap EXIT）：`UPDATE users SET is_admin=false, role='viewer' WHERE id='e2eimgqa001'`

### 4.2 读数（终验，2026-11-25 复取）

| 文档 | chunks | status / knowledge_id | 图片数 | 占位符 | 语义摘要 |
|---|---|---|---|---|---|
| 后端技术中阶 | 2 | `DRAFT` / `kb_0b03e672ee91` | 7 | 0 | **7** ✓ |
| 知识图谱 概念与技术3 | 37 | `PUBLISHED` / `kb_d73b8969113d` | 24 | 0 | **24** ✓ |

**合计**：2 份文档 / 31 张图 / **31 张语义摘要 / 0 张占位符**。两份各自单一 status 集合（无重复切片），
原 status 原样保持（DRAFT 仍 DRAFT、PUBLISHED 仍 PUBLISHED），未掉库。

**语义摘要样本**（实取，证明是画面语义而非占位）：
- 后端技术中阶：`后端初阶学习路线图：基础网络、OS、算法、前端知识与开发工具（Git、Maven、编辑器）` / `后端中阶学习路线图二维码，扫码查看完整路线与联系信息。`
- 知识图谱：`YAGO知识库标志，用于说明关系抽取在自动化知识库构建中的应用与意义。` / `关系抽取方法分类图：含开放抽取、规则方法、学习方法（含监督/半监督/远程监督）及对应章节。`

**口径**：Milvus 集合 `platform_doc_v3_bge_m3` 按 `source_doc` 精确过滤，分母为该文档全部 chunk 内 `![alt](url)` 出现次数；
`占位符` = alt 精确等于"图片描述"。修复前同口径读数为 `7/7 占位`（§2 负控），修复后 `0/31 占位`。

### 4.3 任务轨迹（诚实留档）

- 第 1 轮重传脚本（2 份连传）在第 1 份完成后 SSH 被 `Connection reset` 打断，第 2 份未传。
- 因此第 2 轮只对 `知识图谱` 补传（远端 nohup 后台跑 + 输出落盘，避免再被 SSH 断连中断），`UPLOAD 200` / task `completed`。
- 账号在两轮结束时均为 `false/viewer`（trap 生效，无残留提权）；第 2 轮完结后复取确认。

## 5. 未跑与待环境（字段 4）

- **另 4 份带图文档未重传**（2024进博会手册 / GBT30521 / GBT33490 / 国家会议中心）：实测图片在 MinIO 但切片已不在 Milvus 检索链路，用户拍板不重传、不重新入库。非待办。
- **C 兜底未实现**（问答时现场调 VL）：用户拍板不在本次射程，登记为未来可选项。
- **浏览器真截图未做**：本机无浏览器自动化，本文"语义摘要"判据是 Milvus 内容读数，不声称浏览器内已看到渲染效果。
- **KS 镜像重建耗时 110min**：慢源（阿里云 ~70–100kB/s）+ `openai_agents` 版本逐个回溯，属外部网络退化，非代码缺陷。

## 6. 所需依赖（字段 5）

- 生产：KS 镜像含 fix（`52acc3a5164d`）、agent-server Pod 内 MinIO 凭证（`MINIO_*`）、`DOC_MILVUS_URI`、admin 临时提权。
- 本地：`uv run pytest`（venv）、KS 单测 fixture mock MinIO + 假 `OPENAI_API_KEY`。
- 网络：内网可达（本轮曾断网，恢复后完成）。

## 7. 回滚

- 语义摘要写入 Milvus 切片内容，回滚 = 重传旧版本文档（旧 PDF 仍在 MinIO `pdf_files/`），或用文档下线（`REVOKED`）使其退出检索。
- 账号已还原 `false/viewer`，KS 部署策略已还原 `maxSurge/maxUnavailable=25%`。
