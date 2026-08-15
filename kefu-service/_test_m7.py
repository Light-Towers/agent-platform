import sys
import asyncio

sys.path.insert(0, "../agent-core")

from agent.state import KefuState
from agent.commands import Command, INTENT_TO_COMMAND, COMMAND_DESCRIPTIONS
from agent.graph import build_kefu_graph

print("=== M7 Import 验证 ===")
print("All M7 imports OK")

print("\n=== 9 种命令 ===")
for cmd in Command:
    print(f"  {cmd.value}: {COMMAND_DESCRIPTIONS[cmd]}")

print("\n=== 主对话图构建 ===")
graph = build_kefu_graph()
print(f"Graph compiled: {graph is not None}")

print("\n=== 对话测试（补全后） ===")


async def test_conversation():
    tests = [
        ("你好", "chitchat", "您好"),
        ("查询订单 1001", "order_query", "1001"),
        ("订单 1002 的状态", "order_query", "1002"),
        ("物流 SF1234 到哪了", "logistics_query", "SF1234"),
        ("快递 YT5678 签收了吗", "logistics_query", "YT5678"),
        ("我要退款", "postsale_query", "退款"),
        ("申请换货", "postsale_query", "换货"),
        ("公司报销流程是什么", "knowledge", "报销"),
        ("年假怎么申请", "knowledge", "年假"),
        ("退换货政策", "knowledge", "退换货"),
    ]

    passed = 0
    for message, expected_intent, expected_keyword in tests:
        initial_state: KefuState = {
            "user_message": message,
            "session_id": "test",
            "tenant_id": "default",
            "intent": None,
            "slots": {},
            "flow_state": None,
            "response": None,
            "history": [],
        }
        result = await graph.ainvoke(initial_state)
        intent = result.get("intent")
        response = result.get("response", "")
        intent_ok = intent == expected_intent
        keyword_ok = expected_keyword in response
        match = "✓" if (intent_ok and keyword_ok) else "✗"
        if intent_ok and keyword_ok:
            passed += 1
        print(f"  {match} '{message}' → intent={intent}({intent_ok}), keyword='{expected_keyword}'({keyword_ok})")
        if not (intent_ok and keyword_ok):
            print(f"    response: {response[:80]}")

    print(f"\n  通过: {passed}/{len(tests)}")
    return passed == len(tests)


all_passed = asyncio.run(test_conversation())

print("\n=== Flow 子图验证 ===")
from agent.flows.order_flow import build_order_flow
from agent.flows.logistics_flow import build_logistics_flow
from agent.flows.postsale_flow import build_postsale_flow

print(f"order_flow: {build_order_flow() is not None}")
print(f"logistics_flow: {build_logistics_flow() is not None}")
print(f"postsale_flow: {build_postsale_flow() is not None}")

print("\n=== GraphRAG 验证（补全后） ===")


async def test_graph_rag():
    from agent.graph_rag import graph_rag_query

    tests = [
        ("公司报销流程", "报销"),
        ("年假怎么申请", "年假"),
        ("退换货政策", "退换货"),
        ("考勤制度", "考勤"),
        ("入职流程", "入职"),
    ]

    passed = 0
    for query, expected_keyword in tests:
        response = await graph_rag_query(query)
        ok = expected_keyword in response
        match = "✓" if ok else "✗"
        if ok:
            passed += 1
        print(f"  {match} '{query}' → 含'{expected_keyword}'")
        if not ok:
            print(f"    response: {response[:80]}")

    print(f"\n  通过: {passed}/{len(tests)}")
    return passed == len(tests)


graph_rag_passed = asyncio.run(test_graph_rag())

print("\n=== M7 验收结果 ===")
if all_passed and graph_rag_passed:
    print("M7 验收通过（骨架已补全）")
else:
    print("M7 验收失败")
    sys.exit(1)
