"""
F01-F06 Foundation 脚手架 — 从 mingyang-warehouse 迁移至 agent-platform。

本包包含 P0 Foundation 六件套的数据侧脚手架实现：
  F01 execution_context.py  — ExecutionContext 编解码 + scope 校验 + 审计
  F02 data_egress.py        — 数据分级 / 出域策略 / 模型路由
  F03 knowledge_lifecycle.py — 知识状态机 DRAFT→PUBLISHED→EXPIRED + 审计
  F04 metric_registry.py    — 指标六态 + readiness 映射
  F05 evaluation.py         — Golden Set 四类 + 越权/过期检测
  F06 production_readiness_gate.py — 六门门禁 + 审计
  P1  skill_router.py       — discriminator→Tool 映射 + scope 校验

迁移来源：mingyang-warehouse/ontology/web/backend/（2026-09-22 迁移）
迁移原因：warehouse 只做数据服务，agent 能力统一归 agent-platform（两项目清晰边界）
"""
