# 周一 126 验证 runbook：KB 切分配置化（连上服务器后执行）

> 状态：待执行（本机无 Milvus/Mongo/内网服务，2026-11-21 全部验证阻塞） ｜ 前置：代码改动已在工作区（HEAD=0f3a26b0 未提交），需先按 §0 把代码带到 126 并重建镜像 ｜ 来源：主方案 `docs/plans/plan-kb-chunking-profile-2026-11-20.md` §6/§11、刀 2/4 LLD

## 0. 前置（连上服务器第一件事）

本机 10-session 回归：9/10 绿（KS 531 / agent_server 264 / 前端全门禁绿），root 7 failed 为既有债/环境依赖（详见主方案 §11）。**下列验证需要真 Milvus + Mongo + 内网服务，本机无法做。**

⚠️ **代码进 126 的通道是 `git bundle` + `scp`，不是 git push**（AGENTS.md 内网测试环境条款第 1 条）。本批改动**尚未提交**，所以：

1. 先由用户批示提交/建分支（合 main 须用户点头），否则 126 拿不到这批代码——**跑着的仍是旧 rev**。
2. 按 `docs/operations/nl2sql-release-checklist.md` 的 build/distribute 流程重建 **两个镜像**：KS（含切分策略 + config_hash 改动）和 agent_server（含 web 产物 + proxy 改动）。构建放 241（有 docker+git，注意 `build_with_io_guard.sh` 守卫别关、`IO_LIMIT/IO_STRIKES` 旋钮）。
3. distribute 从 241 跑时显式列 `125 126`（默认 `WORKERS=125 241` 是老形状）。
4. 读运行态 `GIT_REV` 确认是新 rev（`kubectl exec ... cat /srv/agent-platform/GIT_REV`），**别只信宿主 checkout**。

## 1. 部署态健康检查（每步先看 /health）

```
# Pod / rev
kubectl -n agent-platform get pods -o wide
kubectl -n agent-platform exec deploy/<KS-deploy> -- cat /srv/agent-platform/GIT_REV
kubectl -n agent-platform exec deploy/<platform-deploy> -- cat /srv/agent-platform/GIT_REV
# /health 200 + 关键键
kubectl -n agent-platform exec deploy/<KS-deploy> -- python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8900/health').read().decode())"
```
判据：两服务 `/health` 200，rev 与分发的新 rev 一致（AGENTS.md 观测面规矩 #3：读数绑当次 Pod GIT_REV）。

## 2. 功能端到端（核心，验证用户视角三件事）

用真实 HTTP（走 agent_server 代理 `:8000`，浏览器不直连 KS）逐项验：

**2.1 库级切分配置可读可写**
```
# 建库（带初始切分配置）
curl -X POST http://<host>:8000/kb/knowledge-bases -H '<鉴权头>' \
  -H 'Content-Type: application/json' \
  -d '{"name":"验证库","chunk_config":{"split_strategy":"char","max_content_length":1000,"chunk_overlap_ratio":0.1}}'
# 读回（GET 必须带出 chunk_config——刀 2 F-8）
curl http://<host>:8000/kb/knowledge-bases -H '<鉴权头>' | grep chunk_config
```
判据：建库响应含 `chunk_config_applied:true`；列表该库条目含 `chunk_config` 且值正确。

**2.2 上传按库配置切分 + 参数快照**
```
# 上传一份带多种标题/表格的 MD，不传任何切分参数（验证服务端读库配置兜底 F-7）
curl -X POST http://<host>:8000/kb/uploads -H '<鉴权头>' \
  -F 'files=@test.md' -F 'knowledge_id=<上一步的id>'
# 轮询 status，看切分读数
curl http://<host>:8000/kb/status/<task_id> -H '<鉴权头>'
```
判据：status 的 summary.split 显示切片数合理；对应 task 的 `index_registry` 条目 `chunk_params` 写入真实三参数（`python -c` 读 `data/index_registry.json`，容器内）。
- 若库配置是 `char`：验证未超长章节被按字符切（title_count 不主导分片）。
- 若库配置是 `line`：验证表格整块（"表格保整"读数：chunk 中表头与数据行同块）。

**2.3 重新上传即幂等覆盖 + H-1（重传删含 REVOKED 全部历史）**
```
# 传 A.md（V1）→ 下线 → 重传 A.md（V2，同名）→ 调恢复端点
curl -X POST http://<host>:8000/kb/documents/<kid>/restore?source_doc=A -H '<鉴权头>'
```
判据：重传后该 source_doc 只有 V2；恢复端点对"已被重传替换"的文档应 `found:false`（无 REVOKED 旧版可复活）——不会 V1 旧内容复活与 V2 并存。这是 H-1 修法 b 的核心验收。

## 3. golden 真实重标 + 评测门禁（刀 4 剩余，必须真环境）

本机玩具集 `golden_queries.jsonl` 的 `relevant_chunk_ids` 是 `c_101` 构造编号，`eval/README.md:81` 明说 Recall 全 0 属预期，**不能用于门禁**。周一按顺序：

1. **进 KS 容器**（web 容器有 eval 工具与真实集合）：
```
kubectl -n agent-platform exec -it deploy/<KS-deploy> -- sh
cd /app && python eval/gen_golden.py --from-chunks <真实chunk.jsonl> --out eval/golden_queries.real.jsonl
```
   或用 `eval/remap_golden_ids.py --dry-run` 先看映射，再正式重标。判据：输出的每条 `relevant_chunk_ids` 是真实 Milvus chunk_id（自增数字），非 `c_xxx`。
2. **三种策略各标一套**：title/char/line 各产一份 `golden_queries.real.<strategy>.jsonl`（56 条 ×3），`grade` 按真实切片相关性重标。
3. **各跑一遍评测**（新 run_id 已自带切分参数快照 + 扩展 config_hash）：
```
python eval/run_eval.py --golden eval/golden_queries.real.<strategy>.jsonl --out eval/runs/
```
   判据：单次 `metrics.json` 的 `chunk_config` 非 null、`Recall@10` 非全 0；不同策略的 `config_hash` 不同（F-15 生效）。
4. **回归门禁**：`python eval/compare_runs.py <baseline> <candidate>`，显著回归非零退出。新基线登记 **HEAD sha + 件名 + 含切分参数的 config_hash**（AGENTS.md 观测面规矩 #9）。
5. 若出"切分劈答案"badcase，开发侧回头调策略实现/补 golden 用例——**不进界面、不拦用户改配置**（主方案 §6）。

## 4. 已知限制（验证时不会被当成 bug）

- PUBLISHED 发布端点用不了：上传页移除了 `exhibition_id/venue_id`，`validate_metadata` 的"至少一个非空"失败（主方案 R-3）。**这是已知限制**，日常 DRAFT 上传即入库、检索不受影响。若周一有人点发布收到 400，不是回归。
- pgvector 后端不维护：只验 milvus 链路（主方案范围界定）。
- 上传前预览没有：只有上传后读数（F-6 砍掉，主方案 §2）。
- 真浏览器截图未验（刀 3 LLD 标注）：周一若有浏览器环境，补一次"建库→设切分→上传→看只读展示与同名提示"的渲染确认（P5）。

## 5. 收尾

- 每步读数绑当次 Pod `GIT_REV` 与 HEAD sha；换 rev 复跑（AGENTS.md #9）。
- 验证结果回写主方案 §8 P-2 状态 + 刀 4 LLD 状态行（"已验证"档须带 rev + 命令 + 读数）。
- **全部只读验证**，不装包、不改线上配置（沿用 env-126-inventory.md §5/§6 的只读纪律）；golden 重标产物写 KS 容器 `eval/` 或 /tmp，结束清理临时物。
