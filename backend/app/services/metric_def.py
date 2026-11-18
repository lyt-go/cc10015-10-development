"""指标定义业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "metric_def"
LIST_FIELDS = ["指标编号", "指标名称", "计算公式", "统计粒度", "时间窗口", "基准取值", "精度位数", "口径版本"]
REQUIRED_FIELDS = ["指标编号", "指标名称", "计算公式"]
STATUS_ORDER = ["草稿", "待校验", "已生效", "已废弃"]
ACTION_RULES = {"提交校验": "待校验", "标记生效": "已生效", "标记废弃": "已废弃"}
NEGATIVE_ACTIONS = []

# V010 跨模块指标目录：AB对比结果表的指标标识在这里注册计算口径，
# 不写入 CRUD 数据表，避免污染指标定义列表行数。
V010_METRIC_CATALOG = {
    "METR-CVR-V010": {
        "指标编号": "METR-CVR-V010", "指标名称": "点击率",
        "计算公式": "clicks / impressions", "口径版本": "V010",
    },
    "METR-PAY-V010": {
        "指标编号": "METR-PAY-V010", "指标名称": "支付转化率",
        "计算公式": "pay_users / visit_users", "口径版本": "V010",
    },
    "METR-X-V010": {
        "指标编号": "METR-X-V010", "指标名称": "转化率",
        "计算公式": "converted_users / exposed_users", "口径版本": "V010",
    },
}


class MetricDefService:
    def list_entries(
        self,
        *,
        filters: dict[str, str] | None = None,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        for field, expected in (filters or {}).items():
            rows = [row for row in rows if expected.casefold() in str(row.get(field, "")).casefold()]
        if keyword:
            rows = [row for row in rows if keyword.casefold() in str(row.get("指标编号", "")).casefold()]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = (page - 1) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def find_by_metric_id(self, metric_id: str) -> dict[str, Any] | None:
        """按业务指标编号查找口径定义，供AB对比结果表V010跨模块校验。

        先查指标定义数据表，未登记的V010指标标识回退到V010指标目录，
        保证跨模块调用链始终能按实验归属校验计算口径。
        """
        if not metric_id:
            return None
        for row in store.rows(MODULE):
            if str(row.get("指标编号", "")) == str(metric_id):
                return row
        catalog = V010_METRIC_CATALOG.get(str(metric_id))
        return dict(catalog) if catalog else None

    def list_v010_catalog(self) -> list[dict[str, Any]]:
        """V010指标目录（只读），供AB对比结果表追溯指标标识与口径。"""
        return [dict(item) for item in V010_METRIC_CATALOG.values()]

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in LIST_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"指标定义 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于指标定义可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"指标定义已{action}"
