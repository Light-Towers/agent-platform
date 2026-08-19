"""Flow 子包：3 个业务 Flow 用 LangGraph 子图重表达。

对应 legacy ecs_demo/data/flows/ 下：
- flow_order.yml → order_flow.py
- flow_logistics.yml → logistics_flow.py
- flow_postsale.yml → postsale_flow.py

legacy Flow 概念 → LangGraph 子图：
- Flow.steps → 子图 nodes
- Flow.transitions → 子图 edges
- Flow.conditions → 子图 conditional edges
"""
