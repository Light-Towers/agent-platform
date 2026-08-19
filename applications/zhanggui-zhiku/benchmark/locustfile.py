# -*- coding: utf-8 -*-
"""
检索服务压测入口（M6，方案 §10.6 **框架**，不预填任何实测数字）。

场景分档（**目标**，实测后回填 benchmark/README.md 结果表，禁止预填）：
- ``/retrieve`` 纯检索链路（POST /api/v1/retrieve，M6 新增端点）：
  目标 QPS ≥ 100、P95 < 3s、错误率 < 1% —— 全部为自有组件，目标合理；
- ``/chat`` 端到端（POST /query，含 LLM 生成）：由外部 LLM 配额决定，
  分 TTFT / total 两档，**不承诺 100 QPS** —— 外部 API 限流是硬天花板。

运行（需先安装 locust，并启用 M5 API Key）：
    locust -f benchmark/locustfile.py --host http://localhost:8000 --web-port 8089 \
        -u 50 -r 5 -t 5m --api-key <ZHANGUI_API_KEY>
    浏览器打开 http://localhost:8089 开始压测；也可 --headless 无 UI 直跑。

说明：
- golden 集位于 eval/golden_queries.jsonl（M2）；文件缺失或解析失败时退化为内置样例，
  仅用于链路冒烟，压测结论以真实 golden 为准。
- 线上端点事实：纯检索为 /api/v1/retrieve，端到端为 /query（方案 §10.6 示例中的
  /api/v1/chat 为规划命名，当前代码未实现该别名，压测直打真实端点）。
"""

import json
import random
from pathlib import Path

from locust import HttpUser, between, task, events


@events.init_command_line_parser.add_listener
def _init_parser(parser):
    """注册自定义命令行参数 --api-key（M5 启用 API Key 后压测请求需携带）。"""
    parser.add_argument("--api-key", dest="api_key", default="", help="ZHANGUI_API_KEY")

_GOLDEN_PATH = Path(__file__).resolve().parent.parent / "eval" / "golden_queries.jsonl"

_QUERIES: list = []
if _GOLDEN_PATH.exists():
    try:
        with open(_GOLDEN_PATH, "r", encoding="utf-8") as _f:
            _QUERIES = [
                json.loads(line)
                for line in _f
                if line.strip() and not line.strip().startswith("#")
            ]
    except Exception:  # noqa: BLE001 —— 样例加载失败退化为内置样例，不阻断压测入口
        _QUERIES = []

if not _QUERIES:
    # 仅链路冒烟用；真实压测请使用 eval/golden_queries.jsonl
    _QUERIES = [
        {"query": "HAK 180 烫金机怎么换烫印头", "item_name": "HAK 180 烫金机"},
        {"query": "烫金机额定电压是多少", "item_name": "HAK 180 烫金机"},
        {"query": "机器无法加热怎么排查", "item_name": "HAK 180 烫金机"},
    ]


class RagUser(HttpUser):
    """RAG 检索服务压测用户（§10.6 分档：/retrieve 纯检索 + /query 端到端）。"""

    wait_time = between(0.5, 2.0)

    def on_start(self) -> None:
        # M5 启用 API Key 后，压测请求需携带 X-API-Key（--api-key 传入）
        self.api_key = (getattr(self.environment.parsed_options, "api_key", None) or "").strip()

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        return headers

    @task(3)
    def retrieve_only(self) -> None:
        """只压检索链路（不含 LLM 生成）：衡量自有服务真实吞吐（/retrieve 档，QPS≥100 / P95<3s 目标）。"""
        q = random.choice(_QUERIES)
        self.client.post(
            "/api/v1/retrieve",
            json={"query": q.get("query", ""), "item_name": q.get("item_name", "")},
            headers=self._headers(),
            name="POST /api/v1/retrieve",
        )

    @task(1)
    def end_to_end(self) -> None:
        """端到端（含 LLM 生成）：受外部 API 限流约束，不承诺 100 QPS（/query 档，分 TTFT/total）。"""
        q = random.choice(_QUERIES)
        self.client.post(
            "/query",
            json={"query": q.get("query", ""), "session_id": f"bench-{random.randint(0, 10**6)}"},
            headers=self._headers(),
            name="POST /query",
        )
