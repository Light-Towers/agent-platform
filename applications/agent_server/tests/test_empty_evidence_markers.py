# -*- coding: utf-8 -*-
"""空证据判据与降级文案「同源」的门禁（2026-10-28，批次 5）。

钉四件事：

1. **每个子能力的"未配置"文案都必须被判据认成非证据**。反例形状就是本用例建立当天
   查到的真实缺陷：问数子能力早在 A 方案 Stage ③ 就改口为「问数服务未配置
   （NL2SQL_SERVICE_URL 为空）」，而 graph 与 deterministic 两处判据里还钉着退役前的
   「SQL_DSN 未配置」⇒ 一条「根本没配服务」的提示被当成**真证据**送进合成步：反思重试不触发、
   「证据不足」的诚实回答也不触发。
2. **判据只有一份**：两处 Planner 都从 `subagents/degradation.py` 取，不许在本地再抄一遍
   元组（抄第二遍就是上一条漂移的成因）。
3. **真证据不被误判为空**：判据收得太紧会让每次都进重试、把有效证据丢掉。
4. **反证**：把判据换回退役前那份元组，未配置文案就必须被判成"真证据"——证明本文件的红
   是判据给的，不是断言写死的。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from agent_server.subagents import degradation
from agent_server.subagents.degradation import EMPTY_EVIDENCE_MARKERS, has_real_evidence

_SRC = Path(degradation.__file__).resolve().parent.parent  # applications/agent_server/

#: 退役前那一份判据（"SQL_DSN 未配置"）——只用于第 4 条反证，不是期望状态。
_LEGACY_MARKERS = ("知识库未启用", "知识库中未检索到", "联网搜索未配置", "SQL_DSN 未配置")


async def _unconfigured_messages() -> list[str]:
    """四个子能力在「未装配」状态下各自返回的那一条证据文本。"""
    out: list[str] = []

    with patch("agent_server.subagents.rag.get_pool", return_value=None):
        from agent_server.subagents.rag import rag_query

        out.extend(await rag_query("q"))

    with patch("agent_server.subagents.rag.get_pool", return_value=object()), \
         patch("agent_server.subagents.rag.retrieve_chunks", AsyncMock(return_value=[])):
        out.extend(await rag_query("q"))

    from agent_server.subagents.search import search_web
    from agent_server.subagents.sql_agent import sql_query

    with patch("agent_server.subagents.search.get_settings") as s:
        s.return_value.search_api_key = ""
        out.extend(await search_web("q"))

    with patch("agent_server.subagents.sql_agent.get_settings") as s:
        s.return_value.nl2sql_service_url = ""
        out.extend(await sql_query("q"))

    assert len(out) == 4, f"未配置分支取全了才有意义：{out}"
    return out


class TestDegradationMessagesAreCovered:
    async def test_every_unconfigured_message_counts_as_empty_evidence(self):
        for msg in await _unconfigured_messages():
            assert msg.startswith(EMPTY_EVIDENCE_MARKERS), (
                f"子能力返回了判据不认识的降级文案 {msg!r}：它会被当成真证据送进合成步，"
                "既不触发重试、也不产出「证据不足」的诚实回答（判据见 subagents/degradation.py）"
            )
            assert has_real_evidence([msg]) is False, f"{msg!r} 必须判为非证据"

    def test_legacy_sql_marker_is_gone_from_the_judgement(self):
        """退役文案不得继续住在判据里：留着它就等于承认平台还有一条 SQL_DSN 数据面。"""
        assert not any("SQL_DSN" in m for m in EMPTY_EVIDENCE_MARKERS), EMPTY_EVIDENCE_MARKERS


class TestSingleSource:
    """判据与降级文案都必须只有一个来源（抄第二遍就是漂移的成因）。"""

    @pytest.mark.parametrize("relpath", ["agent/graph.py", "planners/deterministic.py"])
    def test_planners_delegate_to_the_one_predicate(self, relpath: str):
        src = (_SRC / relpath).read_text(encoding="utf-8")
        assert "from agent_server.subagents.degradation import has_real_evidence" in src, (
            f"{relpath} 没有复用单一判据，去查它是不是又本地写了一遍元组"
        )
        for marker in ("知识库未启用", "联网搜索未配置", "SQL_DSN"):
            assert f'"{marker}"' not in src, f"{relpath} 里又出现字面量降级文案 {marker!r}"

    def test_degradation_module_stays_pure(self):
        """本模块不许 import settings / 发网络：两处 Planner 都要能无副作用地引它。"""
        src = Path(degradation.__file__).read_text(encoding="utf-8")
        assert "get_settings" not in src and "httpx" not in src


class TestRealEvidenceNotSwallowed:
    def test_normal_evidence_is_real(self):
        assert has_real_evidence(["[来源: 报表 / 销量] 3 月合计 1200"]) is True
        assert has_real_evidence(["执行的 SQL：SELECT 1\n答案：1"]) is True

    def test_empty_evidence_list_is_not_real(self):
        assert has_real_evidence([]) is False


class TestRefutation:
    """反证：本文件的红来自判据本身，不是断言写死。"""

    async def test_with_legacy_markers_the_bug_reappears(self, monkeypatch):
        """把判据换回退役前那份 ⇒ 「问数服务未配置」被判成真证据（就是 2026-10-28 修的缺陷）。"""
        monkeypatch.setattr(degradation, "EMPTY_EVIDENCE_MARKERS", _LEGACY_MARKERS)
        msg = "问数服务未配置（NL2SQL_SERVICE_URL 为空）"
        assert has_real_evidence([msg]) is True, (
            "反证失效：换成退役前的判据后仍未配置被判为空证据，说明上面那条用例并没有在验判据"
        )
