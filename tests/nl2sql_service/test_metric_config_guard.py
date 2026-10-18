"""S-2 metric_config 入参守卫：表白名单 + 体量上限。"""

from __future__ import annotations

import pytest
from nl2sql_service.services.metric_config_guard import (
    MetricConfigRejected,
    check_metric_config,
)


def _recall(**over):
    base = {
        "tables": [{"table_name": "orders", "table_comment": ""}],
        "columns": [{"table_name": "orders", "column_name": "status", "column_comment": ""}],
        "metrics": [],
        "values": [],
        "relations": [],
        "aliases": [],
    }
    base.update(over)
    return base


class TestTableAllowlist:
    def test_empty_allowlist_skips_check(self):
        # 未配白名单 = 不校验（老部署逐字节一致）
        check_metric_config(_recall(), allowed_tables=[])

    def test_all_tables_allowed_ok(self):
        check_metric_config(_recall(), allowed_tables=["orders", "users"])

    def test_unauthorized_table_rejected(self):
        with pytest.raises(MetricConfigRejected) as ei:
            check_metric_config(_recall(), allowed_tables=["users"])
        assert "未授权表" in ei.value.message and "orders" in ei.value.message

    def test_relation_and_alias_tables_checked(self):
        recall = _recall(
            tables=[],
            relations=[{"left_table": "orders", "right_table": "secret_tbl", "left_column": "id", "right_column": "id"}],
        )
        with pytest.raises(MetricConfigRejected):
            check_metric_config(recall, allowed_tables=["orders"])

    def test_preview_capped_not_full_dump(self):
        recall = _recall(tables=[{"table_name": f"t{i}"} for i in range(8)])
        with pytest.raises(MetricConfigRejected) as ei:
            check_metric_config(recall, allowed_tables=["ok"])
        # 只预览前 5 个 + 省略号，不吐整份未授权清单
        assert "…" in ei.value.message


class TestSizeLimit:
    def test_over_limit_rejected(self):
        recall = _recall(columns=[{"table_name": "orders", "column_name": f"c{i}"} for i in range(50)])
        check_metric_config(recall, allowed_tables=["orders"], max_items=100)  # 2+50 = 52 ok
        with pytest.raises(MetricConfigRejected):
            check_metric_config(recall, allowed_tables=["orders"], max_items=10)

    def test_bad_shape_rejected(self):
        with pytest.raises(MetricConfigRejected):
            check_metric_config("not-a-dict", allowed_tables=["orders"])
