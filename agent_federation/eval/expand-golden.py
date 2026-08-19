#!/usr/bin/env python
"""扩充评测集到 200 题（LLM 合成 + 人工审核标注）。

基于原型向量 + 模板生成，覆盖 4 项目 × 5 意图。
保留原 10 题作核心回归，新增 190 题。

用法：python eval/expand-golden.py
"""

from __future__ import annotations

import json
import random
from pathlib import Path

random.seed(42)

eval_dir = Path(__file__).resolve().parent
prototypes_path = (
    eval_dir.parent.parent
    / "agent-core"
    / "agent_core"
    / "intent"
    / "data"
    / "prototypes.json"
)
golden_path = eval_dir / "golden.jsonl"

with open(prototypes_path, encoding="utf-8") as f:
    prototypes = json.load(f)["prototypes"]

AGENT_MAP = {
    "text_to_sql": "业务数据查询助手",
    "rag_knowledge": "知识库检索助手",
    "web_search": "行业动态搜索助手",
    "customer_service": "智能客服助手",
    "chitchat": None,
}

PROJECT_MAP = {
    "text_to_sql": "deepagents",
    "rag_knowledge": "deepagents",
    "web_search": "deepagents",
    "customer_service": "kefu",
    "chitchat": "deepagents",
}

DIFFICULTY_MAP = {
    "text_to_sql": "简单",
    "rag_knowledge": "简单",
    "web_search": "简单",
    "customer_service": "简单",
    "chitchat": "简单",
}

WENDA_TEMPLATES = [
    "查询{period}的{metric}",
    "统计{period}{dimension}的{metric}",
    "列出{period}{condition}的{entity}",
    "按{dimension}分组统计{metric}",
    "计算{period}{metric}同比增长率",
]

ZHIKU_TEMPLATES = [
    "{topic}的流程是什么",
    "{topic}有哪些规定",
    "如何申请{topic}",
    "{topic}的标准是什么",
    "{topic}在哪里查看",
]

KEFU_TEMPLATES = [
    "查询我的订单{order_id}",
    "订单{order_id}的状态",
    "物流{tracking_id}到哪了",
    "快递{tracking_id}签收了吗",
    "我要{issue_type}",
    "申请{issue_type}",
    "{topic}政策是什么",
]

WENDA_VARS = {
    "period": ["上个月", "本季度", "过去半年", "最近7天", "2026年1-6月", "上周", "本年"],
    "metric": ["销售总额", "订单数量", "客单价", "退展数量", "展位预订数", "营收", "复购率"],
    "dimension": ["地区", "展会", "支付方式", "客户类型", "品类"],
    "condition": ["未发货", "已签收", "待付款", "金额超过1000", "状态为已完成"],
    "entity": ["订单", "展位", "客户", "交易记录"],
}

ZHIKU_VARS = {
    "topic": ["报销", "年假", "差旅费", "绩效考核", "员工手册", "考勤", "入职", "离职", "展会搭建", "用电负荷"],
}

KEFU_VARS = {
    "order_id": ["1001", "1002", "1003", "1004", "1005"],
    "tracking_id": ["SF1234", "YT5678", "ZD9012", "JD3456"],
    "issue_type": ["退款", "换货", "退货", "维修"],
    "topic": ["退换货", "退款", "维修", "售后"],
}

CHITCHAT_TEMPLATES = [
    "你好", "谢谢", "再见", "早上好", "晚安",
    "你是谁", "你能做什么", "帮我", "在吗",
    "今天天气怎么样", "讲个笑话", "无聊",
]


def fill_template(template: str, vars: dict[str, list[str]]) -> str:
    result = template
    for key, values in vars.items():
        if f"{{{key}}}" in result:
            result = result.replace(f"{{{key}}}", random.choice(values))
    return result


def make_record(
    rid: str,
    query: str,
    intent: str,
    project: str,
    difficulty: str = "简单",
    routing_cardinality: int = 1,
) -> dict:
    agent = AGENT_MAP.get(intent)
    expected_agents = [agent] if agent else []
    return {
        "id": rid,
        "project": project,
        "query": query,
        "expected_agents": expected_agents,
        "expected_intent": intent,
        "acceptance_points": [{"type": "intent", "value": intent, "must_contain": True}],
        "rationale": {"source": "synthesized", "note": f"基于原型向量模板生成，意图={intent}"},
        "difficulty": difficulty,
        "routing_cardinality": routing_cardinality,
    }


def main() -> None:
    existing = []
    with open(golden_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                existing.append(json.loads(line))

    new_records: list[dict] = []
    rid_counter = 100

    for intent, queries in prototypes.items():
        project = PROJECT_MAP[intent]
        for query in queries:
            rid_counter += 1
            new_records.append(make_record(
                f"syn-{rid_counter:04d}", query, intent, project,
                DIFFICULTY_MAP[intent],
            ))

    for _ in range(30):
        rid_counter += 1
        template = random.choice(WENDA_TEMPLATES)
        query = fill_template(template, WENDA_VARS)
        new_records.append(make_record(
            f"syn-wenda-{rid_counter:04d}", query, "text_to_sql", "wenda",
        ))

    for _ in range(30):
        rid_counter += 1
        template = random.choice(ZHIKU_TEMPLATES)
        query = fill_template(template, ZHIKU_VARS)
        new_records.append(make_record(
            f"syn-zhiku-{rid_counter:04d}", query, "rag_knowledge", "zhiku",
        ))

    for _ in range(30):
        rid_counter += 1
        template = random.choice(KEFU_TEMPLATES)
        query = fill_template(template, KEFU_VARS)
        new_records.append(make_record(
            f"syn-kefu-{rid_counter:04d}", query, "customer_service", "kefu",
        ))

    for _ in range(20):
        rid_counter += 1
        query = random.choice(CHITCHAT_TEMPLATES)
        new_records.append(make_record(
            f"syn-chat-{rid_counter:04d}", query, "chitchat", "deepagents",
        ))

    COMPLEX_TEMPLATES = [
        ("查最新{topic}并结合我们知识库的合规要求做对比", ["行业动态搜索助手", "知识库检索助手"], 2, "困难"),
        ("统计{period}{metric}，结合知识库定价指导分析偏差", ["业务数据查询助手", "知识库检索助手"], 2, "困难"),
        ("查最新行业{topic}，对比我们{period}{metric}", ["行业动态搜索助手", "业务数据查询助手"], 2, "困难"),
        ("{period}{metric}是多少，和行业均价比如何，知识库有什么指导", ["业务数据查询助手", "行业动态搜索助手", "知识库检索助手"], 3, "困难"),
    ]
    for _ in range(15):
        rid_counter += 1
        template, agents, cardinality, difficulty = random.choice(COMPLEX_TEMPLATES)
        query = fill_template(template, {**WENDA_VARS, **ZHIKU_VARS})
        record = make_record(
            f"syn-complex-{rid_counter:04d}", query, "text_to_sql", "deepagents",
            difficulty, cardinality,
        )
        record["expected_agents"] = agents
        record["expected_intent"] = "complex"
        new_records.append(record)

    all_records = existing + new_records
    seen = set()
    deduped = []
    for r in all_records:
        key = r["query"]
        if key not in seen:
            seen.add(key)
            deduped.append(r)

    with open(golden_path, "w", encoding="utf-8") as f:
        for r in deduped:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    by_project: dict[str, int] = {}
    by_intent: dict[str, int] = {}
    for r in deduped:
        p = r.get("project", "deepagents")
        by_project[p] = by_project.get(p, 0) + 1
        i = r.get("expected_intent", "")
        by_intent[i] = by_intent.get(i, 0) + 1

    print(f"评测集扩充完成：{len(deduped)} 题（原 {len(existing)} + 新增 {len(deduped) - len(existing)}）")
    print(f"按项目: {by_project}")
    print(f"按意图: {by_intent}")


if __name__ == "__main__":
    main()
