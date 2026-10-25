"""别名精确匹配（P0-5 主路）：别名表命中优先于稠密向量。

判据（§5.1 四层降级 + §5.3 四层落位）：
- L1 别名词典是**主力**——"GMV→销售额"这类口语变体靠向量撞运气，
  命中率与可解释性都差；等值/别名最准最便宜；
- 匹配口径 = **别名在问题里原样出现**（大小写不敏感）：关键词精确相等，
  或作为子串出现在原始 query 中（query 是用户原话，未被分词切碎）；
- 词条 ≤2,000 时别建向量/倒排（§5.3）——本模块就是等值查找，不碰 ANN。
"""

from __future__ import annotations

from typing import Any


def match_aliases(
    query: str,
    keywords: list[str],
    aliases: list[dict[str, Any]],
    target_kind: str,
) -> list[str]:
    """返回命中的 target_name 列表（保序去重）。

    aliases 来自 `MetaRepository.list_aliases`（只含 source='human' 的
    已确认条目——机提未确认前不参与召回，§5.14-R1）。
    """
    lowered_query = (query or "").lower()
    keyword_set = {str(k).lower() for k in keywords or []}
    hits: list[str] = []
    for row in aliases or []:
        if row.get("target_kind") != target_kind:
            continue
        # 机提未确认不参与召回（§5.14-R1）：SQL 侧 list_aliases 已只出
        # human，这里再判一次——不依赖调用方记得过滤。
        if row.get("source", "human") != "human":
            continue
        alias = str(row.get("alias", "")).strip().lower()
        if not alias:
            continue
        # 关键词精确相等，或别名原样出现在问题里（长度 ≥2 防单字误伤）
        if alias in keyword_set or (len(alias) >= 2 and alias in lowered_query):
            name = row.get("target_name", "")
            if name and name not in hits:
                hits.append(name)
    return hits
