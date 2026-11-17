"""会话标题生成单测（纯函数 + 假 LLM，不连网络/数据库）。

覆盖守门判据：
- 清洗：代码块围栏、引号、尾随标点、多行解释只取首行、截断长度；
- 回退：LLM 为 None / 抛异常 / 返回空 → 截断问题，绝不抛；
- 问题/回答含 % 不被 %-format 误解析。
"""

from __future__ import annotations

import asyncio

from agent_server.api.session_title import fallback_title, generate_title


class _FakeLLM:
    def __init__(self, reply: object, *, raises: bool = False):
        self.reply = reply
        self.raises = raises
        self.seen_prompt = ""

    async def ainvoke(self, prompt: str):
        self.seen_prompt = prompt
        if self.raises:
            raise RuntimeError("llm down")
        if isinstance(self.reply, str):
            return self.reply
        return type("Resp", (), {"content": self.reply})()


def test_fallback_title_first_line_and_truncate():
    assert fallback_title("怎么查展会数据\n第二行") == "怎么查展会数据"
    assert fallback_title("") == "新会话"
    assert len(fallback_title("x" * 100)) == 40


def test_clean_llm_title_strips_fence_quotes_and_punct():
    cases = {
        " 如何查询展会数据？ ": "如何查询展会数据",
        '"租户隔离怎么做"': "租户隔离怎么做",
        "```\n记忆分类有几种\n```": "记忆分类有几种",
        "标题第一行\n解释第二行": "标题第一行",
        "《展品浏览分析》。": "展品浏览分析",
    }
    for raw, expected in cases.items():
        llm = _FakeLLM(raw)
        assert asyncio.run(generate_title(llm, "q", "a")) == expected


def test_generate_title_falls_back_when_llm_missing_or_broken():
    assert asyncio.run(generate_title(None, "查询收藏量", "答案")) == "查询收藏量"
    assert asyncio.run(generate_title(_FakeLLM("", raises=False), "查询收藏量", "答案")) == "查询收藏量"
    assert asyncio.run(generate_title(_FakeLLM("", raises=True), "查询收藏量", "答案")) == "查询收藏量"
    assert asyncio.run(generate_title(_FakeLLM(123), "查询收藏量", "答案")) == "查询收藏量"


def test_percent_in_content_is_not_reparsed():
    llm = _FakeLLM("占比100%分析")
    title = asyncio.run(generate_title(llm, "增长率%怎么算", "结果是100%提升"))
    assert title == "占比100%分析"
    assert "增长率%怎么算" in llm.seen_prompt
