# 2026-11-23 知识库切分配置 + 图片/引用回显 + 构建加速 生产部署取证

> 所有读数绑 rev / 镜像 ID，2026-11-23 实取。基址 126（control-plane），构建机 241，worker 125/126。
> 本机标识真值见不入库的 `.intranet/keymap.json`（仓库文本一律 `<internal-host>` 占位）。

## 1. 代码基线（本机 git）

| 项 | 值 |
|---|---|
| 本批 commit 1 | `1e1ffa10bed2892b36b111bb37945beab19e02ad`（KB 切分配置 + 图片/引用回显治本） |
| 本批 commit 2 | `4c074f3716e93ecb5c2b60bb10f00ed3d9edac9d`（构建期 PyPI 源治本） |
| 部署时 checkout | 241 `/opt/agent-platform` = `4c074f37`, dirty=0（git bundle + scp + fetch + checkout，未 push） |
| 部署后本机 HEAD | `369a3977`（另有并行 web 重构 R1–R5 共 9 commit，本批两 commit 均为其祖先；那 9 commit 未部署，不在本批射程） |

## 2. 镜像（构建 + 分发 + 回读）

| 镜像 | 构建 rev | 新 ID | A1 | 三台回读 |
|---|---|---|---|---|
| agent-platform:dev | `1e1ffa10` | `1e677958c6e70` | langfuse 5.2.0 import OK | 241/125/126 crictl 均为新 ID ✓ |
| knowledge-service-web:latest | `4c074f37` | `25596b4d5da83` | knowledge_service import OK | 241/125/126 crictl 均为新 ID ✓ |

构建日志保留：`241:/tmp/build-agent-1e1ffa10.log`、`241:/tmp/build-ks-v2.log`。
IO 守卫开启（IO_LIMIT=80/IO_STRIKES=6），结束前 PSI 未熔断；KS 构建 elapsed 1687s（此前用清华源 70min+ 未完，加速生效）。

### 分发踩坑（已解，留档）
- 首轮 KS 分发脚本用裸 `ctr -n k8s.io images import`（未指定 `--address`）→ 镜像进了**默认 containerd 库**，而 kubelet 用 `/run/containerd-k8s/containerd.sock` 那个库 ⇒ crictl 回读仍是旧 ID。
- 修复：显式 `ctr --address /run/containerd-k8s/containerd.sock -n k8s.io images import` 重导三台 → crictl 回读新 ID。标准 `distribute.sh` 本就带 `--address`，手工分发必须对齐。
- 125/126 首轮 scp 在大 tarball 下未落盘（`open ... no such file`），单独重传 OK。

## 3. 配置改动（两 ConfigMap + 一 deploy env）

| 对象 | 键 | 值 | 回读 |
|---|---|---|---|
| ks-config | IMG_SUMMARY_ENABLED | true | 容器内生效 ✓ |
| ks-config | VL_MODEL | Qwen/Qwen3-VL-8B-Instruct | 容器内生效 ✓ |
| agent-platform-config | RICH_IMAGE_ALLOWED_HOSTS | minio | 容器内生效 ✓ |
| agent-platform deploy | env RICH_IMAGE_ALLOWED_HOSTS | configMapKeyRef → ap-config | 结构生效 ✓ |

白名单 `minio` 取自实取 `MINIO_ENDPOINT=minio:9000`, `MINIO_SECURE=False`（图片 URL = `http://minio:9000/kb-import-bucket/...`）。
备份：`126:/tmp/kb-img-config-backup/`（含两 ConfigMap + deploy 的原始 yaml，可回滚）。

## 4. rollout（含 hostPort 死锁修复）

- agent-platform：直接 rollout 成功，新 Pod imageID `1e677958c6e70` ready=True。
- ks-web：`nodeSelector` 钉 ambari03 + `hostPort:8000` + `maxSurge:25%` → 新 Pod 抢不到 8000 端口 Pending（"didn't have free ports"）。修复：临时 patch `maxSurge:0 / maxUnavailable:1`（先删旧释放端口）→ rollout 成功 → 恢复 25%/25%。
- 最终：`agent-platform-6676778676-x7vjd` ready / imageID `1e677958c6e70`；`ks-web-867fbfb878-dgbgb` ready / imageID `25596b4d5da83`。

## 5. 端到端验证（只读，未改生产数据）

| 验证 | 方法 | 结果 |
|---|---|---|
| 服务健康 | Pod IP curl /health | agent-platform healthy（otel ACTIVE / langfuse_ready / guard_enabled / embedding_real）；ks-web `{"ok":true}` ✓ |
| KB 切分配置代码 | KS `/collections` 返回 `chunk_config` 字段 | 4 库可见，字段在 ✓ |
| 富回答 adapter | exec 进新 Pod 直接 import `rich_answer_adapter` + `evidence_sink`，喂含 MinIO 图片链接的 chunk | 产出 2 citation + 1 图片 + source_doc ✓ |
| 白名单反证 | 同上喂外域图片 `https://evil.com/x.png` | 图片被拒（images=[]）✓ |
| SSE 接线 | 新镜像内 grep query_router.py | `bind_sink`(281) + `to_rich_answer`(389) + `yield _sse({"type":"rich"})`(391) 在位 ✓ |
| 前端产物 | web/dist/assets/index-DfAyYNR1.js 含 `rich` | ✓ |

**未做（需用户凭据/授权）**：走真实 HTTP `/query`（需登录令牌）端到端回显图片；重传带图文档验证摘要语义生成。这两项要构造生产测试数据或提供令牌，留待用户拍板。

## 6. 不健康 Pod（与部署前基线一致，未恶化）

`ks-milvus` 1 副本 ContainerStatusUnknown（33 重启）、`ks-neo4j` 2 副本（ErrImagePull/Error）——部署前即如此，与本次两服务 rollout 无关，未处理。

## 7. 回滚

备份在 `126:/tmp/kb-img-config-backup/`：两 ConfigMap 原 yaml + `pre-rollout-deploy.yaml`。回滚 = apply 原 ConfigMap + rollout undo 两 deployment（镜像 tag 不变，旧 ID `1eb567a71ff31`/`a8154d66a1ffe` 仍在三台 k8s.io 库）。
