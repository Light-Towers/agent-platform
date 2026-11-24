# 2026-11-24 图片全链路（切分可见 + 会话传图提问 + 回答回显）生产部署取证

> 所有读数绑 rev / 镜像 ID，2026-11-24 实取。基址 126（control-plane），构建机 241，worker 125/126。
> 方案：`docs/plans/plan-image-qa-fullstack-2026-11-23.md`；内网真值见 `.intranet/keymap.json`（不入库）。

## 1. 代码基线（本机 git）

| 项 | 值 |
|---|---|
| 功能主 commit | `4e5a396d`（图片全链路刀1-4） |
| 修复序列 | `73c6398a`（Form）→ `6de9cd15`(pool.connection) → `47221e0b` → `817a571f`（psycopg3 %s/元组/fetchone）→ `b1b382bd`（VL 独立硅基流动端点） |
| 部署时 checkout | 241 `/opt/agent-platform` = `b1b382bd`, dirty=0（git bundle + scp + fetch + checkout，未 push） |

## 2. 镜像（构建 + 分发 + 回读）

| 镜像 | 构建 rev | 新 ID | A1 | 三台回读 |
|---|---|---|---|---|
| agent-platform:dev | `b1b382bd` | `5b43640c90533` | langfuse 5.2.0 import OK | 241/125/126 crictl `docker.io/library` tag 均为新 ID ✓ |

构建日志：`241:/tmp/build-vlep.log`（若清理则用 `/tmp/build-final.log` 系列）。IO 守卫 80/6 全程未熔断。

### 构建踩坑（已解，留档）
- corepack 下载 pnpm 走 `registry.npmjs.org` DNS EAI_AGAIN ⇒ 构建时加 `COREPACK_NPM_REGISTRY=https://registry.npmmirror.com/`（不入库，构建期 env）。
- 标准 `distribute.sh` 回读 grep 先命中 registry 旧 tag，精确按 `docker.io/library/agent-platform:dev` 核对才是真值。

## 3. 配置改动（全可逆，备份在 `126:/tmp/kb-img-config-backup/`）

| 对象 | 键 | 值/来源 | 回读 |
|---|---|---|---|
| agent-platform-secrets | MINIO_ACCESS_KEY / MINIO_SECRET_KEY | 从 ks-secrets 复制（值不打印） | 容器内 AK=Y SK=Y ✓ |
| agent-platform-secrets | VL_API_KEY | 从 ks-secrets SILICONFLOW_API_KEY 复制 | deploy env secretKeyRef ✓ |
| agent-platform-config | MINIO_ENDPOINT / SECURE / BUCKET | minio:9000 / false / kb-import-bucket | ✓ |
| agent-platform-config | VL_BASE_URL / VL_MODEL | https://api.siliconflow.cn/v1 / Qwen/Qwen3-VL-8B-Instruct | ✓ |
| deploy env | MINIO_* / VL_* / RICH_IMAGE_ALLOWED_HOSTS | Secret/ConfigMap 引用 | ✓ |

**VL 端点关键**：agent_server 的 `LLM_BASE_URL=api-inference.modelscope.cn` 不提供 Qwen3-VL（实测 400 "has no provider supported"）；硅基流动提供（已验 8B/32B 等），故 VL 用独立 `VL_BASE_URL/VL_API_KEY`，与 KS 同源。

## 4. migration 022（chat_images 表）

新 Pod 启动时 lifespan 自动跑 `run_migrations`，表已建成（`to_regclass('public.chat_images')` = chat_images）。PG bytea 存上传图，租户/会话索引 + created_at TTL 索引在位。

## 5. 端到端验证（真图，全通过）

| 验证 | 方法 | 结果 |
|---|---|---|
| 图片代理 `/img/{bucket}/{path}` | 带 token 取真实知识库图 | HTTP 200 / image/jpeg / 47949B / 545x623 JPEG ✓ |
| 登录 | 注册+登录 e2eimgqa001 | token 获取 ✓ |
| 上传 `/chat/upload-image` | multipart session_id + 真 JPEG | 返回 `image_ref` ✓ |
| **带图问答 `/query`** | context.images=[ref] | SSE 无 error，answer/done/evidence/memory/route/status ✓ |
| **VL 语义识别** | 真图+问题"这张图片展示什么" | 正确识别"绿色边框展览展台、Company Name 占位、花卉背景、宣传册架和座椅" ✓ |

**测试假象留档**：早先用 1x1 假 PNG 做 E2E 报 `bad header checksum in IDAT`、用 http://localhost URL 报云端拉不到——均非产品缺陷；真实用户路径（上传真图拿 ref）全通。

### 已知边角（不阻断主路径，未随本批修）
- `_resolve_images` 对客户端传的 http(s) URL 仍透传（云端 VL 拉不到 localhost，等于无效）；应改为拒绝任意 http URL（兼防 SSRF）。前端正常只传 ref，不受影响。下次部署随带修。
- `thread_persist` 历史仍纯文本，多轮带图时助手看不到上一轮的图（登记限制，方案 §7）。
- `CHAT_IMAGE_TTL_DAYS` 未显式进 ConfigMap（默认 7 天生效）。
- 既有不健康 Pod（ks-milvus 1 副本 / ks-neo4j 2 副本）与本次无关，未处理。

## 6. 回滚

备份在 `126:/tmp/kb-img-config-backup/`：两 ConfigMap + 两 Secret + deploy yaml（pre-minio / pre-vl / pre-imageqa 各时点）。回滚 = apply 原对象 + `kubectl rollout undo deploy/agent-platform`（旧镜像 ID `517f3babfee31`/`1e677958c6e70` 仍在三台 k8s.io 库）。

## 7. 后续待办

- ~~写"依赖层拆分"方案~~ → 已实施（见下 §8）。
- 修 `_resolve_images` 的 http URL 透传（SSRF + 无效）。
- 拆前端 pnpm 层（`COPY web/` 在 `pnpm install` 之前，每次重跑）——让总构建时长真正降到分钟级（见 §8）。

## 8. 上午复盘的两个机制修复（同日补做）

1. **消除测试假绿**：新增 `scripts/evidence/chat_images_real_pg_probe.py`（pgserver 本机真 PG 16.2，11 项 rc=0）。5 个 bug（Form/pool API/psycopg3 占位符/cursor API/VL 端点）曾在 fake 单测全绿下存活、部署后才暴露；现在用生产 chat_images.py 在真库往返，改动 DB/合成链后本地先跑探针。登记在 `scripts/evidence/README.md` + `ARCHITECTURE.md`。
2. **依赖层拆分**（`plan-docker-build-layer-split-2026-11-24.md`）：Dockerfile 把"装依赖"与"装业务代码"拆两层。实测改一行业务代码后 `Step 19(torch)` + `Step 21(依赖层)` 均 `Using cache`，依赖层不再重跑；线上 rev `05d9910b` 三台 rollout 成功、A1 全依赖 import OK。**但总耗时仍 692s（11.5min）**——前端 pnpm 层（Step 6/8）仍每次重跑（Dockerfile :28-35 的既有坑，独立待办）。⇒ 依赖层目标达成，整体构建快的目标只完成一半。
