"""实验设计 时间线服务：实验创建后根据分流比例自动生成对照组和实验组的分群定义。"""
from __future__ import annotations

import time
from datetime import date, timedelta
from typing import Any

from app.store import store

MODULE = "experiment"
REQUIRED_FIELDS = ["方案编号", "实验名称", "对照组说明"]
STATUS_ORDER = ["草稿", "待审批", "运行中", "已结束"]
ACTION_RULES = {"提交审批": "待审批", "启动实验": "运行中", "终止实验": "已结束"}
NEGATIVE_ACTIONS = []

# 实验归属范围：按实验创建顺序轮询，AB对比时用于越权判定。
SCOPES = ["scope-a", "scope-b"]


class ExperimentService:
    def get_timeline(self) -> list[dict[str, Any]]:
        rows = store.rows(MODULE)
        today = date.today()
        items: list[dict] = []
        for i, row in enumerate(rows):
            start = (today - timedelta(days=7 - i * 2)).isoformat()
            end = (today + timedelta(days=3 - i)).isoformat()
            status = str(row.get("status", STATUS_ORDER[i % len(STATUS_ORDER)]))
            items.append({
                "id": int(row.get("id", i + 1)),
                "name": str(row.get("实验名称", "")),
                "start": start,
                "end": end,
                "status": status,
                "logs": f"[{start}] 作业启动\n[{start}] 正在处理...\n[{end}] 任务{'完成' if status == STATUS_ORDER[-1] else '进行中'}",
            })
        return items

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [f for f in REQUIRED_FIELDS if not str(values.get(f) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": store.next_id(MODULE)}
        for f in REQUIRED_FIELDS + ["实验组说明", "样本总量", "分流比例", "启动日期", "预期时长"]:
            entry[f] = values.get(f, "")
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        entry["created_at"] = time.time()
        rows.append(entry)
        store.bump_version(MODULE)
        # 自动根据分流比例生成分群定义
        self._auto_create_sample_groups(entry)
        return entry, []

    def _auto_create_sample_groups(self, experiment: dict[str, Any]) -> None:
        """实验创建后，根据分流比例自动生成对照组和实验组的分群定义。"""
        ratio_str = str(experiment.get("分流比例") or "5:5")
        try:
            parts = ratio_str.split(":")
            control_ratio = float(parts[0]) if len(parts) > 0 else 5.0
            exp_ratio = float(parts[1]) if len(parts) > 1 else 5.0
        except Exception:
            control_ratio, exp_ratio = 5.0, 5.0
        total = control_ratio + exp_ratio
        control_pct = control_ratio / total if total > 0 else 0.5
        exp_pct = exp_ratio / total if total > 0 else 0.5
        total_sample = experiment.get("样本总量") or "10000"
        try:
            total_n = int(total_sample)
        except Exception:
            total_n = 10000
        control_n = int(total_n * control_pct)
        exp_n = total_n - control_n
        exp_id = experiment["id"]
        exp_code = experiment.get("方案编号", f"EXPE-{exp_id:04d}")
        access_scope = experiment.get("access_scope") or SCOPES[(exp_id - 1) % len(SCOPES)]
        experiment["access_scope"] = access_scope
        # 创建对照组分群
        sg_rows = store.rows("sample_group")
        now_iso = date.today().isoformat()
        control_sg = {
            "id": store.next_id("sample_group"),
            "分群编号": f"SG-{exp_code}-CTRL",
            "分群名称": f"{experiment.get('实验名称','')} 对照组",
            "筛选条件": f"experiment_id={exp_id} AND group='control'",
            "样本基数": str(control_n),
            "分群日期": now_iso,
            "更新方式": "实验触发",
            "有效天数": experiment.get("预期时长", "14"),
            "负责人": experiment.get("负责人", "system"),
            "status": "已就绪",
            "pending": False,
            "abnormal": False,
            "experiment_id": exp_id,
            "group_type": "control",
            "access_scope": access_scope,
            "created_at": time.time(),
        }
        sg_rows.append(control_sg)
        store.bump_version("sample_group")
        # 创建实验组分群
        exp_sg = {
            "id": store.next_id("sample_group"),
            "分群编号": f"SG-{exp_code}-EXP",
            "分群名称": f"{experiment.get('实验名称','')} 实验组",
            "筛选条件": f"experiment_id={exp_id} AND group='experiment'",
            "样本基数": str(exp_n),
            "分群日期": now_iso,
            "更新方式": "实验触发",
            "有效天数": experiment.get("预期时长", "14"),
            "负责人": experiment.get("负责人", "system"),
            "status": "已就绪",
            "pending": False,
            "abnormal": False,
            "experiment_id": exp_id,
            "group_type": "experiment",
            "access_scope": access_scope,
            "created_at": time.time(),
        }
        sg_rows.append(exp_sg)
        store.bump_version("sample_group")

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"实验方案 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于实验设计可执行范围"
        target = ACTION_RULES[action]
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        store.bump_version(MODULE)
        return entry, f"实验方案已{action}"
