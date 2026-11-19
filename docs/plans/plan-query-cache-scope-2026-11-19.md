# 修复：选知识范围问"知识图谱"文档问不到（语义缓存污染）

> 状态：待部署。触发（用户 2026-11-19）：测试库上传"知识图谱"文档成功，会话选知识范围=测试库问问题却找不到。绑诊断时 rev=1e6ad03d（KS）/ 26d0b21e（平台）。

## 根因（实取坐实，两层叠加）
1. 文档本身**确实入库了**：测试库 `kb_d73b8969113d` 文档树有 `知识图谱 概念与技术3`(36 片)。用语义新颖的问法（加随机盐）绕开缓存后，RAG 正常命中（evidence count=4，准确引用"远程监督/度量指标"内容）。⇒ 检索链路没问题。
2. **语义缓存命中了旧的否定答案**：用户问的问题命中 `cache_hit` 帧（无 route/evidence/answer），直接返回之前"证据为无/无法回答"的旧答案，**根本不走检索**。两个 bug：
   - **knowledge_id 没进缓存 key**：query_router 调 cache get/set 时没传 kb_versions（默认 None），选不同库问同一问题串缓存。
   - **否定答案也缓存**：set 条件是 `if final_answer`，"证据为无"这种答案也被写缓存。文档入库后仍命中旧否定答案。

## 修复（用户拍板）
- `query_router.py`：get/set 传 `kb_versions={"kb": req.knowledge_id}`，知识范围进缓存键。
- 新增纯函数 `should_cache_answer(final_answer, cache_enabled, is_rag_route, had_evidence)`：只有「RAG 路由且零证据」的否定答案不缓存；direct 闲聊无 evidence 照常缓存（不误伤）。循环里捕获 route 的 capability 和 evidence 的 count 作为结构判据，不靠 LLM 文本措辞。
- 测试：`test_query_cache_admission.py`（新，5 条纯函数）+ 现有 cache degradation 3 条全绿。

## 验证
- ✅ 静态：14 条 query 测试全绿 + ruff；根套件 1391 passed。
- ⏳ 待部署 + 真环境：平台重建后，用户原问法应不再命中旧否定答案；选不同库同问题不串；RAG 空证据答案不再入缓存。
- 注：根套件有 1 条历史遗留失败 `test_p15_current_tree_is_clean_and_really_judged`（白名单登记 `scripts/reimport_kb_to_milvus.py` 但该文件 fe97eb19 改成 pymilvus 直搬后已无签名点），与本改动无关，单独记录待处理。
