"""只读控制台路由与页面约束（演示版 A.1 #3，第 3–4 天）。

钉三件容易在后续改动里悄悄破掉的事：
1. `/console.html` 只发页面壳，**不返业务数据**（页面内容一律来自正式接口）；
2. 页面只调只读接口，**不得出现任何写入口**（1.2 基线 6）；
3. 页面不为控制台新开接口（恒等性约束：只加返壳的路由）。
"""

from __future__ import annotations

import re
from pathlib import Path

from agent_server.api import console_router
from agent_server.main import app
from fastapi.testclient import TestClient

# 允许的目标：三个正式只读取数接口
_ALLOWED_TARGETS = {"query", "history", "health"}
# 明确禁止出现在页面上的写操作入口（运维动作只走命令行/正式接口）。
# 只列路径形态：裸词 "import"/"revert" 会误伤 JS 关键字与中文文案。
_FORBIDDEN_ENDPOINTS = ("/import", "/sql/train", "/session/revert", "import.html")


def _script_of(html: str) -> str:
    m = re.search(r"<script>(.*?)</script>", html, re.S)
    assert m, "页面无 script 块"
    return m.group(1)


def _code_of(html: str) -> str:
    """去掉注释后的脚本正文。

    禁词断言必须只看代码：注释里写「绝不拼 innerHTML」「不落 localStorage」是解释意图，
    若把它当违规，等于用测试逼注释改写措辞，而不是守住真实约束。
    """
    script = _script_of(html)
    script = re.sub(r"/\*.*?\*/", "", script, flags=re.S)
    script = re.sub(r"//[^\n]*", "", script)
    return script


def _fetch_targets(html: str) -> set[str]:
    """抽出所有 fetch("xxx" 的第一参数字面量（模板串/变量拼出来的会命中不了 ⇒ 一并断言不存在）。"""
    script = _script_of(html)
    targets = set(re.findall(r'fetch\(\s*"([^"]*)"', script))
    # 带查询串的归一为路径名
    return {t.split("?")[0] for t in targets}


class TestConsolePageShell:
    def test_returns_html_shell_without_business_data(self):
        with TestClient(app) as client:
            resp = client.get("/console.html")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/html")
        # 壳与磁盘上的文件逐字一致：路由不注入任何数据
        on_disk = (Path(console_router.__file__).resolve().parent.parent / "static" / "console.html").read_text(
            encoding="utf-8"
        )
        assert resp.text == on_disk

    def test_shell_is_reachable_without_api_key(self):
        """页壳免鉴权（与仓库既有静态页惯例一致），数据接口才要密钥。"""
        with TestClient(app) as client:
            assert client.get("/console.html", headers={}).status_code == 200

    def test_no_sample_answers_or_prefilled_data(self):
        """底线 1：页面不得写死回答/示例链路——页面里不该出现任何 answer 文本常量。"""
        html = TestClient(app).get("/console.html").text
        # answer 只能来自 payload.text
        assert 'payload.text' in html
        assert not re.search(r'\$\("answer"\)\.textContent\s*=\s*"[^"]', html), "answer 被写死"
        assert not re.search(r'append\(el\("div",\s*"ev \w+",\s*"[^"]', html), "时间线里有写死的行"


class TestReadOnlyConstraint:
    def test_page_calls_only_read_endpoints(self):
        html = TestClient(app).get("/console.html").text
        targets = _fetch_targets(html)
        assert targets, "页面没有任何 fetch 调用"
        unexpected = targets - _ALLOWED_TARGETS
        assert not unexpected, f"页面调了非只读接口：{unexpected}"

    def test_no_write_endpoints_referenced_anywhere_in_page(self):
        """含被注释掉/残留的写入口引用也算违规——运维动作不进浏览器。"""
        html = TestClient(app).get("/console.html").text
        script = _script_of(html).lower()
        for endpoint in _FORBIDDEN_ENDPOINTS:
            assert endpoint.lower() not in script, f"页面残留写入口引用：{endpoint}"

    def test_page_never_persists_the_api_key(self):
        """密钥只存内存：落 localStorage/sessionStorage 就等于把部署密钥写进浏览器存储。"""
        script = _code_of(TestClient(app).get("/console.html").text)
        for sink in ("localStorage", "sessionStorage", "indexedDB", "document.cookie"):
            assert sink not in script, f"页面把密钥/数据写入 {sink}"

    def test_no_dyn_html_sink_for_untrusted_text(self):
        """资料原文与模型回答都是不可信输入：渲染只能走 textContent，不得有 innerHTML。"""
        script = _code_of(TestClient(app).get("/console.html").text)
        assert "innerHTML" not in script
        assert "insertAdjacentHTML" not in script
        assert "document.write" not in script


class TestNoNewDataEndpoint:
    def test_console_router_exposes_only_the_shell_path(self):
        """控制台不许新开返业务数据的口（恒等性约束）。"""
        paths = {(r.path, tuple(sorted(r.methods))) for r in console_router.router.routes}
        assert paths == {("/console.html", ("GET",))}, paths

    def test_status_payload_has_no_money_field(self):
        """页面不留金额位：后端也不发金额字段（无定价表，报 0 会被读成算错了钱）。"""
        from agent_server.planners.deterministic import DeterministicPlanner

        payload = DeterministicPlanner._status_payload(_NullRuntime())
        assert "cost_used" not in payload and "cost" not in payload
        assert set(payload) == {"tokens_used", "steps"}


class _NullRuntime:
    context = None
