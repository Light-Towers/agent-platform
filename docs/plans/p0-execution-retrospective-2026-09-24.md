# P0 阶段执行复盘（2026-09-24）—— 踩坑与防复发

> 记录架构审计 P0 阶段（P0-1~P0-4，含 P0-4 门禁棘轮的多轮反复）执行过程中遇到的问题、根因与下次如何避免。目的：同类任务不再犯同样错误。
> 关联：`arch-audit-2026-09-24.md` §8、`plan-p0-1-scheduler-gating-option-b-2026-09-24.md`、`plan-p0-4-blind-except-ratchet-2026-09-24.md`、`plan-p0-4-blind-except-real-reduction-2026-09-24.md`。

## 1. 逐点 `# noqa` 依附规则开关 → 加-删-加 churn

- **现象**：`# noqa: BLE001` 被 `3ccc90e` 全量加（211→0）→ 有人把 `BLE001` 移出 `select`/全局 `ignore` → `92ba46f` 把它们当"死注释"清除（只删 noqa、`except Exception` 原样留）→ 下一轮又重开 `select` 再加。跨会话反复，污染源码却零真实收益。
- **根因**：inline noqa 的**存废完全绑定该规则是否常驻 `select`**；选方案时没确认门禁规则的启用策略会长期稳定。
- **下次如何避免**：
  1. 治理"存量违规"优先用 **文件级 `per-file-ignores` 基线**（整包锁定、源码零逐点标注），而非逐点 noqa。
  2. 采用逐点 noqa 前，先确认该 lint 规则在 CI 里是**永久 select**；否则一律不写逐点 noqa。
  3. 判断某改动是否"反复"，先 `git log --oneline -- <file>` + `git show <sha>` 看历史，别在当前态里空想。

## 2. 撤销前未核 HEAD 基线 → 误判 `git restore` 能一步还原

- **现象**：想用 `git restore` 把源文件回退到"干净 + 基线"态，但 `git show HEAD:pyproject.toml` 显示 **HEAD 根本没有 M1 基线**——整个 P0-4（M1 基线 + M2 烧除）从未提交。若只 `restore`，会连 M1 基线一起丢。
- **根因**：默认"基线已提交"，未先验证工作树相对 HEAD 的真实差异。
- **下次如何避免**：撤销/回退动作前，先 `git status` + `git show HEAD:<file>` 确认哪些是已提交基线、哪些是本会话未提交增量；源文件回 HEAD、未提交的配置块用编辑工具单独重建。

## 3. 盲捕获分类靠"行号 + 模式"猜，未读完整 try 体 → P0 级定性错误

- **现象**（真实被用户逐站核查抓出）：初稿把 `import_exhibition_corpus.py:217`（实为 HTTP 上传+轮询批次降级）误判为"文件读→OSError"；`node_pdf_to_md.py` 156/239 行号与内容对调；`:134` 漏计 try 体内显式 `raise RuntimeError`。若照表执行，窄化会让网络异常/控制流异常逃逸 → **引入新崩溃路径**，恰好违反方案自定红线。
- **根因**：按 `except Exception` 行号 + 邻近调用模式套分类，没有把每个 try 体逐行读完（尤其漏"体内 raise""体内多调用混合"）。
- **下次如何避免**：
  1. 任何"批量按模式改异常处理"，**逐站读 try 体每一行**，确认 except 类型集合覆盖体内**所有**正常抛出（含显式 `raise`、多层调用）。宁可少窄不可漏抛。
  2. "删 except 交全局 handler"须同时满足三重前提：① 应用真的注册了 `add_exception_handler(Exception,...)` ② 异常在**请求调用栈内**（后台任务/SSE 生成器接不到）③ 兜底 handler 日志上下文不弱于原 `logger.exception(msg, id)`。
  3. 抽查 ≠ 全查：方案里凡标"非穷举/待逐处判定"的，批准前必须补全查。

## 4. 对"仓库级适用面"过度乐观，先动手后勘察

- **现象**：一度以为"删纯冗余 except 交全局 handler"能大面积降量；实测全局脱敏 handler **6 应用仅 1 个有**（knowledge-service），且多数盲捕获是承重降级，路适用面极窄。
- **根因**：未先量化前提（handler 覆盖面、后台/SSE 占比）就设想了收益。
- **下次如何避免**：降量/重构类方案先跑**事实勘察**（grep 覆盖面、ruff 枚举真实站点、分类计数），用数据定 scope，再写方案；别用"应该有"代替"实测有"。

## 5. 门禁任务的自证缺失

- **现象**：早期只口头说"清零/通过"，缺少可复核证据。
- **下次如何避免**：门禁/降量类改动必附**自证命令**——`ruff --config 'lint.per-file-ignores={}'` 让被豁免站点现形，核对"残留站点数 = 保留基线条目数"且**按文件 1:1**，既无过宽豁免也无漏网；`grep noqa` = 0；`check_doc_sync` 0 警告。证据先于结论。

## 6. Windows / 沙箱 / 工具链注意事项（非业务，但反复消耗）

- 本机无 `make`/`rg`：用 `uv run pytest ...` / `uv run --with ruff ruff check ...` / `Select-String`。
- PowerShell 不支持 `&&`：多命令用 `;` 连接。
- git 写操作 / uv 写工作区外缓存被沙箱拦（"Access is denied"）：加 `required_permissions='all'` 重试。
- 干净捕获 ruff 退出码：`$out = ... 2>$null; Write-Output "X_EXIT=$LASTEXITCODE"`（管道到 `Select-Object` 后 `$LASTEXITCODE` 可能失真）。
- 结构化选项（AskUserQuestion）里选项文本**勿嵌英文双引号**，会破坏 JSON；中文用转义。
- **已知环境噪声**（非本次引入）：从 monorepo 根跑 `pytest applications/knowledge-service/tests` 时 `from eval.ablation import` / `from eval.metrics import` 会因**根 `eval/` 遮蔽 `knowledge-service/eval/`** 报 collection error。下次涉及该套件测试，走 knowledge-service 自己的 CI session 目录或加 `rootdir`/`conftest` 隔离，别误判为改动引入的回归。

## 7. 流程纪律小结

- **先方案后编码**（红线）：重构/降量先在 plan 文档写目标/影响面/迁移策略/验收标准并获批，再动源码；核查抓出的错误**先改文档再改码**。
- **不凑绿**：禁止删用例/收窄断言/放宽前置来掩盖失败。
- **承重与冗余要分清**：宽捕获≠一定是债；可选通道部分降级、后台任务兜底、SSE 生成器 finally 清理都是**承重**，保留 + 文件级基线豁免即可。
