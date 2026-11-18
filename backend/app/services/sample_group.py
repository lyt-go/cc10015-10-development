"""样本分群业务规则：提供分群人员列表供AB分析消费。

成员明细按分群编号做确定性生成：同一分群多次读取得到同一份成员集合，
保证「实验归属过滤」与「差异计算」使用同一成员集合，重算中断恢复时
也不会用越权成员补齐。
"""
from __future__ import annotations

import hashlib
import time
from typing import Any

from app.store import store

MODULE = "sample_group"
LIST_FIELDS = ["分群编号", "分群名称", "筛选条件", "样本基数", "分群日期", "更新方式", "有效天数", "负责人"]
REQUIRED_FIELDS = ["分群编号", "分群名称", "筛选条件"]
STATUS_ORDER = ["草稿", "计算中", "已就绪", "已过期"]
ACTION_RULES = {"开始计算": "计算中", "确认就绪": "已就绪", "标记过期": "已过期"}
NEGATIVE_ACTIONS = []

# 跨实验共享成员：这些用户同时落在两个实验的分群里，用于版本冲突场景。
# key 为实验序号（按实验创建顺序，从 1 开始），value 为该实验分群固定带上的共享用户。
OVERLAP_USERS = ["OVERLAP-U001", "OVERLAP-U002", "OVERLAP-U003"]
# 每个实验分群额外混入的「越权成员」：归属范围与分群所属实验不一致。
UNAUTHORIZED_USERS = ["FOREIGN-U001", "FOREIGN-U002"]
# 演示用归属范围：实验按序号轮询落在两个业务范围上。
SCOPE_BY_EXPERIMENT = {1: "scope-a", 2: "scope-b"}
FOREIGN_SCOPE = "scope-foreign"


def seeded_rng(seed_text: str) -> Any:
    """以分群编号等稳定文本为种子生成随机源，保证重算结果一致。"""
    import random
    seed = int(hashlib.sha256(seed_text.encode("utf-8")).hexdigest(), 16) % (2**32)
    rng = random.Random(seed)
    return rng


class SampleGroupService:
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
            rows = [row for row in rows if keyword.casefold() in str(row.get("分群编号", "")).casefold()]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = (page - 1) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def get_group_members(self, group_id: int) -> list[dict[str, Any]]:
        """生成分群的确定性用户列表，供AB分析消费。"""
        sg = self.get_entry(group_id)
        if sg is None:
            return []
        return self.build_members(sg)

    def build_members(self, sg: dict[str, Any]) -> list[dict[str, Any]]:
        """按分群定义构建确定性成员明细，落库分群与AB对比临时分群共用此口径。

        每条成员带：
        - user_id / group_id / group_type / metric_value
        - experiment_id：成员归属实验
        - scope：成员归属范围，用于越权判定（越权成员 scope 与分群实验不一致）
        - is_overlap：是否为跨实验共享用户（版本冲突来源）
        """
        group_id = int(sg.get("id", 0))
        try:
            base = int(sg.get("样本基数", 1000))
        except Exception:
            base = 1000
        experiment_id = int(sg.get("experiment_id", 0) or 0)
        group_type = sg.get("group_type", "control")
        own_scope = sg.get("access_scope") or SCOPE_BY_EXPERIMENT.get(experiment_id, "scope-a")
        rng = seeded_rng(str(sg.get("分群编号", f"SG-{group_id}")))
        members: list[dict[str, Any]] = []
        # 固定重叠用户：同一用户会出现在两个实验的分群成员明细中。
        for overlap_user in OVERLAP_USERS:
            value = rng.gauss(mu=0.62 if group_type == "experiment" else 0.55, sigma=0.08)
            members.append({
                "user_id": overlap_user,
                "group_id": group_id,
                "group_type": group_type,
                "metric_value": round(max(0.0, min(1.0, value)), 4),
                "experiment_id": experiment_id,
                "scope": own_scope,
                "is_overlap": True,
            })
        # 固定越权成员：归属范围是外部范围，AB 对比时只能只读、不得进入正式差异。
        for foreign_user in UNAUTHORIZED_USERS:
            value = rng.gauss(mu=0.5, sigma=0.05)
            members.append({
                "user_id": f"{foreign_user}-G{group_id}",
                "group_id": group_id,
                "group_type": group_type,
                "metric_value": round(max(0.0, min(1.0, value)), 4),
                "experiment_id": -1,
                "scope": FOREIGN_SCOPE,
                "is_overlap": False,
            })
        for i in range(min(base, 500)):  # 上限500避免内存爆炸
            user_id = f"U{group_id}{i:04d}"
            # 实验组用户指标值偏高，对照组偏低，形成可检测差异
            if group_type == "experiment":
                value = rng.gauss(mu=0.62, sigma=0.08)
            else:
                value = rng.gauss(mu=0.55, sigma=0.08)
            members.append({
                "user_id": user_id,
                "group_id": group_id,
                "group_type": group_type,
                "metric_value": round(max(0.0, min(1.0, value)), 4),
                "experiment_id": experiment_id,
                "scope": own_scope,
                "is_overlap": False,
            })
        return members

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        entry = {"id": store.next_id(MODULE)}
        entry.update({field: values.get(field) for field in LIST_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        entry["created_at"] = time.time()
        store.rows(MODULE).append(entry)
        store.bump_version(MODULE)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"样本分群 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于样本分群可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        store.bump_version(MODULE)
        return entry, f"样本分群已{action}"
