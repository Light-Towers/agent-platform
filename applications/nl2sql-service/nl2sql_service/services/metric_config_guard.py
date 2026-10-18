"""metric_config 入参守卫（S-2）：表白名单 + 体量上限。

**威胁**（S-2）：`metric_config` 由客户端任意注入且直进召回与 prompt——

- 可声明任意表/列/指标，把 LLM 诱导去查未授权表（同名表伪装：给真实敏感表
  配 benign 注释）；
- 注释是自由文本 = prompt 注入面（由 S-8 的 prompt_sanitizer 管清洗）；
- 入参无体量上限可把 prompt 撑爆（拒绝服务）。

**本层**：两道硬闸，都在**进 state/召回前**拦——

1. **表白名单**：`allowed_tables` 非空时，metric_config 里出现的每个表必须
   在清单内，否则 fail-fast（不猜、不静默丢弃——静默丢会让"我以为注入了"
   和"其实被丢了"无法区分）。空清单 = 不校验（老部署向后兼容）。
2. **体量上限**：表/列/指标/值/关系/别名总条目数超限即拒，防 prompt 被撑爆。

白名单与 S-8 清洗、guard 标识符白名单（P0-10）是三道各管一段的纵深：
本模块管"能声明哪些表 + 声明多少"，S-8 管"注释文本怎么洗"，guard 管
"最终 SQL 用了哪些标识符"。
"""

from __future__ import annotations

from typing import Any

#: 单次 metric_config 的元知识条目总上限（防 prompt 撑爆 / 拒绝服务）
DEFAULT_MAX_ITEMS = 200

#: metric_config 里承载"表名"的集合字段（用于表白名单校验）
_TABLE_COLLECTIONS = ("tables", "columns", "values", "relations", "aliases")
#: 这些集合里指明表名的字段（relations/aliases 用 *_table/target_name）
_TABLE_NAME_FIELDS = ("table_name", "left_table", "right_table")


class MetricConfigRejected(Exception):
    """metric_config 未过守卫。message 是对外可读原因（不含内部清单细节）。"""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _iter_table_names(recall: dict[str, Any]) -> set[str]:
    """从 to_recall_result 形状里抽出所有被声明的表名。"""
    names: set[str] = set()
    for coll in _TABLE_COLLECTIONS:
        for item in recall.get(coll, []) or []:
            if not isinstance(item, dict):
                continue
            for field in _TABLE_NAME_FIELDS:
                val = item.get(field)
                if val:
                    names.add(str(val))
    return names


def _total_items(recall: dict[str, Any]) -> int:
    return sum(len(recall.get(coll, []) or []) for coll in ("tables", "columns", "metrics", "values", "relations", "aliases"))


def check_metric_config(
    recall: dict[str, Any],
    allowed_tables: list[str] | None,
    max_items: int = DEFAULT_MAX_ITEMS,
) -> None:
    """校验 to_recall_result 形状的 metric_config；不合规抛 MetricConfigRejected。

    - `allowed_tables` 为空/None ⇒ 跳过表白名单（向后兼容）；
    - 体量上限恒生效（max_items <= 0 时用默认值）。
    """
    if not isinstance(recall, dict):
        raise MetricConfigRejected("metric_config 形状不正确")

    limit = max_items if max_items and max_items > 0 else DEFAULT_MAX_ITEMS
    total = _total_items(recall)
    if total > limit:
        raise MetricConfigRejected(f"metric_config 条目过多（{total} > {limit}）")

    allow = {t for t in (allowed_tables or []) if t}
    if not allow:
        return  # 未配白名单 = 不校验表（老部署逐字节一致）
    declared = _iter_table_names(recall)
    unauthorized = sorted(declared - allow)
    if unauthorized:
        # 只报数量与前几个，不吐整份清单（清单本身也是信息）
        preview = "、".join(unauthorized[:5]) + ("…" if len(unauthorized) > 5 else "")
        raise MetricConfigRejected(f"metric_config 含未授权表: {preview}")


__all__ = ["DEFAULT_MAX_ITEMS", "MetricConfigRejected", "check_metric_config"]
