# 2026-11-24 图片显示端到端验证（界面等价 HTTP 链路）

> 用户要求"直接操作界面做一轮完整上传/问答，看图片是否显示"。本机无浏览器自动化工具，
> 用浏览器会发的同一批 HTTP 请求（经本地 vite `localhost:5173` 代理 → 126 后端）做等价验证。
> 所有读数绑 rev，commit `e7de33d5`。

## 1. 链路与读数

| 步骤 | 请求 | 结果 |
|---|---|---|
| 登录 | POST /auth/login | token ✓ |
| 知识库列表 | GET /kb/knowledge-bases | 4 库 ✓ |
| 问答（命中带图文档） | POST /query | SSE: route/evidence/memory/answer/**rich**/status/done ✓ |
| rich 事件图片 | rich.images | **5 张**（知识图谱概念与技术3）✓ |
| 图片加载 | GET /img/kb-import-bucket/images/... | 5/5 HTTP 200 image/jpeg（36641/73580/76453/30801/60546 字节）✓ |

**结论：图片能显示出来了。** 修复前 rich 有图但浏览器加载不出来，根因两处（见 §2）。

## 2. 根因与修复

1. **历史图片 URL 缺斜杠**：`http://minio:9000/kb-import-bucketimages/...`（bucket 与 images 粘连）。
   旧 `node_md_img.py` 拼 URL 时 base_url 末尾与 object_name 开头都无斜杠。
   - 治本：抽 `build_image_url()` 显式加斜杠（KS 需要重建镜像才生效，只影响新文档）。
   - 兼容：前端 `toProxyImageUrl` 把历史 `kb-import-bucketimages/` 补回 `kb-import-bucket/images/`（立即生效，历史文档可显示）。
2. **本地 vite 代理缺 /img 和 /chat**：`<img src="/img/...">` 与上传请求落到 5173 的 SPA fallback。
   - 修：vite.config.ts 的 `proxied` 加 `/img`、`/chat`。

## 3. 测试固化

- `web/scripts/verify-sse.mjs` §G8 toProxyImageUrl 4 条（正常/历史缺斜杠/外域/已改写），157 断言全过。
- `applications/knowledge-service/tests/unit/test_node_md_img_url.py` 3 条（斜杠/https/多级路径）。
- `check-events.mjs` C5 扩展"消费是提供的路径前缀"匹配（前端运行时拼路径的盲点），内置自证 `/img*` 放行、`/bogus*` 报红。
- 前端 typecheck/lint/check-events/verify-sse 全绿。

## 4. 上传→切分预览（临时提权后补测，已还原）

用户授权后临时提权测试账号（双写 is_admin=true + role=admin），验后 trap 还原并独立确认 `false/viewer`：

| 步骤 | 读数 |
|---|---|
| 上传带图 Markdown（2 张真实 MinIO 图） | HTTP 200，task_ids=[f042fb90...] |
| 轮询切分状态 | completed，chunk_count=1 |
| 该文档问答命中图片 | rich.images 含**刚上传的 2 张**（URL 带正确斜杠）+ 历史 7 张（缺斜杠，前端兼容补回）✓ |
| 账号还原 | false/viewer ✓ |

**已知小局限**：上传后读数面板的 `previewImages` 从 `split.previews[].head`（前 120 字）提取图片——图片若在文档后段会被 head 截断、该面板提不到；但**切片明细**（`expandedDocImages` 从 chunk 完整 content 提取）和**回答回显**都能显示。不影响核心诉求，登记不扩大改动。

## 5. 边界

- 本次只改前端 + KS 代码，线上 agent-platform 无需重建；KS 镜像重建（导入 bug）待定，不阻断历史图片显示。
- 生产 MinIO 私有桶保持私有（未开匿名），图片经 agent_server `/img` 鉴权代理取字节。
