# KS（知识库服务）部署 Runbook

> 范围：KS 镜像构建、运行（当前 docker moby）、单文件热更快通道与复核、k8s 化待办。
> 与 `AGENTS.md`「内网测试环境 126」一节互补；凡读数须绑 `GIT_REV`。

## 1. 现状
- KS 当前在 126 以 **docker moby** 运行：`docker-compose` 编排 `knowledge-service-web` + 伴生 `milvus` / `minio` / `neo4j` / `mongo` / `etcd`（数据全在这些伴生容器里，重启 web 容器不丢数据）。
- **KS 未纳入 k8s**（仓库 `deploy/k8s/` 清单只覆盖 `agent-platform` / `nl2sql` / `postgres` / `valkey`）。k8s 化见 §6。
- 构建入口：`applications/knowledge-service/Dockerfile`，build context = 仓库根；产物镜像默认 `knowledge-service-web:latest`。

## 2. 镜像构建（已做分层优化）
Dockerfile 已拆两层：
- **第 1 层（依赖层，极少变）**：装 torch/langchain/magic-pdf 等大依赖 + 共享包（editable）。
- **第 2 层（代码层，频繁变）**：拷业务源码 + `pip install -e . --no-deps`。

改 `import_router.py` 等源码后重 build，**只重跑第 2 层（分钟级）**，不再全量重装大依赖。

```bash
cd /opt/agent-platform/applications/knowledge-service
docker-compose --profile core build web
docker-compose --profile core up -d web   # 保留卷/网络，只换 web 镜像
```

构建前确保：`/opt/agent-platform` 已 checkout 到目标 `GIT_REV`（KS 不在 k8s 清单内，rev 门禁不拦，但跑着的镜像必须对应你想发的 rev）。

## 3. 单文件热更快通道（应急 / 提速，谨慎使用）
仅用于「单文件小改动且不愿等镜像构建」的场景。**严禁 `sed -i` 大范围改写**——此前线上 `import_router.py` 丢失 3 个已入库修复，成因正是 broad `sed` 热改漂移。

```bash
# 例：仅改了 import_router.py
docker cp applications/knowledge-service/knowledge_service/api/import_router.py \
  knowledge-service-web:/app/knowledge_service/api/import_router.py
docker restart knowledge-service-web
```

注意：热更只落在运行容器可写层，镜像本身未变；容器重建 / 迁移即丢失，须尽快补回镜像（走 §2 构建）。

## 4. 热更复核方式（防漂移，源自 AGENTS.md §环境事实 #4）
不靠「比对文件数」判断漂移——那答不了「线上这份内容丢了吗」。用三步取权威结论：

1. **取权威热改清单**（可写层 vs 镜像层，不靠推断、不漏非 .py 与删除项）：
   ```bash
   docker diff knowledge-service-web
   # 输出 C=内容变更 / A=新增 / D=删除，即容器内相对镜像的可写层改动
   ```
2. **对每个热改文件取 git blob OID（不带 `-w`，不写库）**：
   ```bash
   # 用仓库内对应文件（若容器版本更可信则用 docker cp 取出）
   git hash-object -- applications/knowledge-service/knowledge_service/api/import_router.py
   # 或容器版本：
   docker cp knowledge-service-web:/app/knowledge_service/api/import_router.py /tmp/ir.py \
     && git hash-object -- /tmp/ir.py
   ```
3. **判读是否曾入库**：
   ```bash
   git cat-file -t <上一步 OID>
   # blob    => 内容曾入库（只是镜像旧版本，安全；`git log --find-object=<OID>` 定位 commit）
   # missing => 内容从未进 git（需救回：补 commit）
   ```
4. 周期性执行 `docker diff` + `git hash-object` 全量比对，确保线上热改全部可追溯。

## 5. 验证
- 健康检查：`curl -f http://<host>:8000/health`
- G2 验收：KbUpload 表单出现「数据源类型」下拉；提交后该值在 KB 任务的 `metadata.datasource_type` 可见（Mongo 无 schema，免迁移）。

## 6. k8s 化（待办）
目标：KS web 服务纳入 k8s（与 `agent-platform` / `nl2sql` 一致），消除「docker moby + 热改通道」双轨与漂移债。
其有状态伴生组件（milvus / minio / neo4j / mongo / etcd）的 k8s 化方案待定（全量搬 k8s vs 仅 web 上 k8s、数据组件外置），见部署计划决策。
