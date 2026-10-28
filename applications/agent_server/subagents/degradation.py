# -*- coding: utf-8 -*-
"""子能力降级文案的单一来源：生产者（各 subagent）与判据（Planner 的空证据识别）共用一份常量。

依赖方向是单向的——本模块**不 import settings / 不发网络**，只放字符串常量与纯函数，
所以 `agent_server/agent/graph.py` 与 `agent_server/planners/deterministic.py` 都能引它。

为什么要有这个文件（2026-10-28 批次 5 踩到的真实缺陷）：问数子能力早已改口为
「问数服务未配置（NL2SQL_SERVICE_URL 为空）」，而两处空证据判据里还钉着退役前的
「SQL_DSN 未配置」⇒ 一条"根本没配服务"的提示被当成**真证据**送进合成步：反思重试不触发、
"证据不足"的诚实回答也不触发，表现是答得理直气壮而内容是空的。判据与文案分头写第二遍，
就是这类漂移的成因；收在这里后，改文案必须同时改常量，两处判据跟着一起变。

已登记、语义上同样"没拿到证据"但**未**列入判据的文案（不属本批范围，不静默改行为）：
`问数失败：{error}`、`问数服务错误：HTTP xxx`、`问数服务不可达（…）`、`联网搜索无结果`。
这些条目是"服务失败 / 查到零结果"，与上面四个常量（能力未装配）语义不同，
是否都算空证据需要产品口径。
复审触发条件：一旦出现"服务失败却被当成真证据合成答案"的实测案例（或口径要求失败态
也算空证据），就把它们补进 `EMPTY_EVIDENCE_MARKERS`，并同步
`applications/agent_server/tests/test_empty_evidence_markers.py` 的反证用例。
"""

from __future__ import annotations

# 前缀（不是整句）：整句还带"（XXX 为空）"这类 env 名，判据只认前缀，
# 这样文案后半段可以补细节而不动判据。
KNOWLEDGE_DISABLED = "知识库未启用"
KNOWLEDGE_NO_HIT = "知识库中未检索到"
SEARCH_UNCONFIGURED = "联网搜索未配置"
NL2SQL_UNCONFIGURED = "问数服务未配置"

#: 空证据前缀集合。evidence 里任何一条以这些开头，都不算"真证据"。
EMPTY_EVIDENCE_MARKERS: tuple[str, ...] = (
    KNOWLEDGE_DISABLED,
    KNOWLEDGE_NO_HIT,
    SEARCH_UNCONFIGURED,
    NL2SQL_UNCONFIGURED,
)


def has_real_evidence(evidence: list[str]) -> bool:
    """这批证据里是否有"真证据"（graph 反思与 deterministic 重试共用的同一判据）。"""
    return bool(evidence) and not any(e.startswith(EMPTY_EVIDENCE_MARKERS) for e in evidence)
