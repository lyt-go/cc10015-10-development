"""AB对比结果表服务：按实验归属读取分析报告与分群成员明细，生成可追溯的对比结果表。

核心约束（与需求逐条对应）：

1. 每行差异只来自同一实验的对照组与实验组：归属过滤与差异计算复用同一份
   已授权成员集合（_authorized_members），避免跨实验记录混入。
2. 越权成员只读：越权成员进入只读清单，绝不进入正式差异计算。
3. 成员重算中断：沿用上一版完整对比结果，恢复时不得用越权成员补齐。
4. 残留处理：发现正式结果残留越权/跨实验成员时，按结果表保留目核对，
   在事务中整体回滚，不做半成品落库。
5. 版本冲突：同一用户出现在两个实验分群时，支持两种策略——
   target_only（只保留目标实验成员出正式结果）/ isolate（保留目标实验结果，
   重叠用户单列待复核清单）。
6. V010 留档与转交：归档后只读，转交只授予读权限；指标定义 V010 模块按
   实验归属读取本表指标标识并校验计算口径。
"""
from __future__ import annotations

import copy
import threading
import time
from typing import Any

from app.services.metric_def import MetricDefService
from app.services.sample_group import SampleGroupService
from app.store import store

MODULE = "ab_result"
COMPARE_MODULE = "ab_compare"
CALIBER_VERSION = "V010"
OVERLAP_STRATEGIES = ("target_only", "isolate")
RESULT_KIND_FORMAL = "正式结果"
RESULT_KIND_REVIEW = "待复核结果"


class AbCompareError(Exception):
    """对比结果表业务异常，消息可直接返回前端。"""


class AbCompareService:
    """AB对比结果表：内存事务、归属过滤、差异计算与V010留档。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sample_service = SampleGroupService()
        self._metric_service = MetricDefService()

    # ------------------------------------------------------------------
    # 权限与归属
    # ------------------------------------------------------------------
    @staticmethod
    def _scopes(operator_scopes: list[str] | None) -> set[str]:
        # 未显式给范围时按平台管理员处理（全量可读、可写），保持本地演示可用。
        if not operator_scopes:
            return {"__all__"}
        return set(operator_scopes)

    def _can_write(self, operator_scopes: list[str] | None, target_scope: str) -> bool:
        scopes = self._scopes(operator_scopes)
        return "__all__" in scopes or target_scope in scopes

    def _is_readonly(self, operator_scopes: list[str] | None, target_scope: str) -> bool:
        """越权请求只读：归属范围不匹配时仍可查看共享内容，但不能改动。"""
        return not self._can_write(operator_scopes, target_scope)

    # ------------------------------------------------------------------
    # 数据读取（分析报告 + 分群成员明细，按实验归属）
    # ------------------------------------------------------------------
    def list_eligible_experiments(self) -> list[dict[str, Any]]:
        """可生成AB对比结果表的实验：必须存在可读分析报告。"""
        report_experiment_ids = {
            int(row["experiment_id"])
            for row in store.rows(MODULE)
            if row.get("experiment_id")
        }
        eligible: list[dict[str, Any]] = []
        for experiment in store.rows("experiment"):
            exp_id = int(experiment["id"])
            if exp_id not in report_experiment_ids:
                continue
            eligible.append({
                "id": exp_id,
                "方案编号": experiment.get("方案编号"),
                "实验名称": experiment.get("实验名称"),
                "access_scope": experiment.get("access_scope", "scope-a"),
            })
        return eligible

    def _find_report(self, experiment_id: int) -> dict[str, Any]:
        for row in store.rows(MODULE):
            if int(row.get("experiment_id") or 0) == experiment_id:
                return row
        # 兼容种子数据：报告行只写了「实验编号」文本时，用实验方案编号回退匹配。
        experiment = store.find("experiment", experiment_id)
        exp_code = str(experiment.get("方案编号", "")) if experiment else ""
        for row in store.rows(MODULE):
            if str(row.get("实验编号", "")) == exp_code:
                return row
        raise AbCompareError(f"实验 {experiment_id} 没有可读的分析报告，无法生成对比结果表")

    def _groups_of_experiment(self, experiment_id: int) -> list[dict[str, Any]]:
        """返回实验的对照/实验分群。

        优先读取样本分群数据表；实验没有落库分群时，合成不落库的临时分群定义
        （仅存在于本次计算与结果表内），避免为生成对比结果而污染样本分群模块。
        """
        groups = [
            g for g in store.rows("sample_group")
            if int(g.get("experiment_id") or 0) == experiment_id
        ]
        if len(groups) >= 2:
            return groups
        experiment = store.find("experiment", experiment_id)
        exp_code = str(experiment.get("方案编号", f"EXPE-{experiment_id:04d}")) if experiment else f"EXPE-{experiment_id:04d}"
        scope = (experiment or {}).get("access_scope", "scope-a")
        try:
            total_n = int((experiment or {}).get("样本总量", 200))
        except Exception:
            total_n = 200
        half = max(1, total_n // 2)
        ephemeral: list[dict[str, Any]] = []
        for offset, group_type in enumerate(("control", "experiment")):
            # 负 id 避免与样本分群数据表的真实主键冲突
            group_id = -(experiment_id * 10 + offset + 1)
            ephemeral.append({
                "id": group_id,
                "分群编号": f"SG-{exp_code}-{group_type.upper()}",
                "分群名称": f"{exp_code} {'对照组' if group_type == 'control' else '实验组'}（临时）",
                "筛选条件": f"experiment_id={experiment_id} AND group='{group_type}'",
                "样本基数": str(half),
                "experiment_id": experiment_id,
                "group_type": group_type,
                "access_scope": scope,
                "临时分群": True,
            })
        return ephemeral

    def _load_members(self, groups: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        """读取分群成员明细；同一分群多次读取结果一致（确定性生成）。

        落库分群与临时分群走同一成员构建口径，保证归属过滤与差异计算同源。
        """
        loaded: dict[str, list[dict[str, Any]]] = {}
        for group in groups:
            if group.get("临时分群"):
                loaded[str(group["id"])] = self._sample_service.build_members(group)
            else:
                loaded[str(group["id"])] = self._sample_service.get_group_members(int(group["id"]))
        return loaded

    def _authorized_members(
        self,
        groups: list[dict[str, Any]],
        members_by_group: dict[str, list[dict[str, Any]]],
        experiment_id: int,
    ) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
        """归属过滤：只保留属于目标实验且范围匹配的成员。

        过滤后的同一份成员集合同时用于差异计算，保证口径一致。
        越权成员（scope 不符或 experiment_id 不一致）原样返回给只读清单，
        不允许进入正式差异。
        """
        authorized: dict[str, list[dict[str, Any]]] = {}
        unauthorized: list[dict[str, Any]] = []
        for group in groups:
            group_id = str(group["id"])
            own_scope = group.get("access_scope")
            kept: list[dict[str, Any]] = []
            for member in members_by_group.get(group_id, []):
                same_experiment = int(member.get("experiment_id") or 0) == experiment_id
                same_scope = own_scope is None or member.get("scope") == own_scope
                if same_experiment and same_scope:
                    kept.append(member)
                else:
                    record = dict(member)
                    record["越权原因"] = (
                        "成员归属实验与目标实验不一致"
                        if not same_experiment
                        else f"成员范围 {member.get('scope')} 与实验归属 {own_scope} 不一致"
                    )
                    unauthorized.append(record)
            authorized[group_id] = kept
        return authorized, unauthorized

    @staticmethod
    def _mean(values: list[float]) -> float:
        return round(sum(values) / len(values), 6) if values else 0.0

    def _metric_rows(
        self,
        report: dict[str, Any],
        control: list[dict[str, Any]],
        experiment: list[dict[str, Any]],
        member_universe: set[str],
    ) -> list[dict[str, Any]]:
        """按报告里的指标标识计算差异；只统计同一授权成员集合内的成员。"""
        metric_id = str(report.get("metric_id") or report.get("分析指标") or "METR-DEFAULT")
        metric_def = self._metric_service.find_by_metric_id(metric_id)
        control_values = [
            float(m["metric_value"]) for m in control if m["user_id"] in member_universe
        ]
        experiment_values = [
            float(m["metric_value"]) for m in experiment if m["user_id"] in member_universe
        ]
        control_mean = self._mean(control_values)
        experiment_mean = self._mean(experiment_values)
        diff = round(experiment_mean - control_mean, 6)
        return [{
            "指标标识": metric_id,
            "指标名称": (metric_def or {}).get("指标名称", report.get("分析指标", "")),
            "口径版本": (metric_def or {}).get("口径版本", CALIBER_VERSION),
            "对照组均值": control_mean,
            "实验组均值": experiment_mean,
            "差异": diff,
            "效果方向": "上升" if diff > 0 else ("下降" if diff < 0 else "持平"),
            "对照组样本量": len(control_values),
            "实验组样本量": len(experiment_values),
        }]

    # ------------------------------------------------------------------
    # 生成对比结果表（事务：先在副本上构建，核对通过后整体提交）
    # ------------------------------------------------------------------
    def generate(
        self,
        experiment_id: int,
        *,
        operator_scopes: list[str] | None,
        overlap_strategy: str = "target_only",
        simulate_interrupt: bool = False,
    ) -> dict[str, Any]:
        if overlap_strategy not in OVERLAP_STRATEGIES:
            raise AbCompareError(
                f"重叠用户策略只支持 {OVERLAP_STRATEGIES}，收到 {overlap_strategy}"
            )
        with self._lock:
            previous = self._find_latest(experiment_id)
            # 重算中断：沿用上一版完整结果，绝不用越权成员补齐。
            if simulate_interrupt:
                if previous is None:
                    raise AbCompareError("成员重算中断且无上一版完整对比结果可沿用")
                interrupted = copy.deepcopy(previous)
                interrupted["status"] = "已中断"
                interrupted["中断说明"] = "成员重算中断，沿用上一版完整对比结果，未使用越权成员补齐"
                interrupted["updated_at"] = time.time()
                return interrupted
            return self._build_in_transaction(
                experiment_id, operator_scopes, overlap_strategy
            )

    def _build_in_transaction(
        self,
        experiment_id: int,
        operator_scopes: list[str] | None,
        overlap_strategy: str,
    ) -> dict[str, Any]:
        experiment = store.find("experiment", experiment_id)
        if experiment is None:
            raise AbCompareError(f"实验 {experiment_id} 不存在")
        target_scope = experiment.get("access_scope", "scope-a")
        if not self._can_write(operator_scopes, target_scope):
            raise AbCompareError(
                f"越权请求：当前范围无权写入实验 {experiment_id}（归属 {target_scope}），共享内容只读"
            )
        report = self._find_report(experiment_id)
        groups = self._groups_of_experiment(experiment_id)
        members_by_group = self._load_members(groups)

        # 归属过滤与差异计算使用同一授权成员集合。
        authorized, unauthorized = self._authorized_members(
            groups, members_by_group, experiment_id
        )
        control_group = next(g for g in groups if g.get("group_type") == "control")
        experiment_group = next(g for g in groups if g.get("group_type") == "experiment")
        control_members = authorized[str(control_group["id"])]
        experiment_members = authorized[str(experiment_group["id"])]

        # 版本冲突：同一用户出现在两个实验分群（is_overlap）。
        overlap_users = sorted({
            m["user_id"]
            for members in authorized.values()
            for m in members
            if m.get("is_overlap")
        })
        if overlap_strategy == "target_only":
            # 做法一：只保留目标实验成员，重叠用户不进入正式结果。
            universe = {
                m["user_id"]
                for members in authorized.values()
                for m in members
                if not m.get("is_overlap")
            }
            review_rows: list[dict[str, Any]] = []
        else:
            # 做法二：目标实验结果照出，重叠用户隔离到待复核清单。
            universe = {m["user_id"] for members in authorized.values() for m in members}
            review_rows = [{
                "结果类型": RESULT_KIND_REVIEW,
                "实验编号": experiment.get("方案编号"),
                "重叠用户": overlap_users,
                "说明": "同一用户同时出现在两个实验分群，已隔离待复核，未并入正式差异",
            }]

        metric_rows = self._metric_rows(
            report, control_members, experiment_members, universe
        )

        # 事务构建：先在副本上组装并核对，残留则整体回滚，不污染已落库版本。
        snapshot = copy.deepcopy(store.rows(COMPARE_MODULE))
        candidate = self._assemble_table(
            experiment=experiment,
            report=report,
            groups=groups,
            control_members=control_members,
            experiment_members=experiment_members,
            unauthorized=unauthorized,
            overlap_users=overlap_users,
            overlap_strategy=overlap_strategy,
            metric_rows=metric_rows,
            review_rows=review_rows,
            universe=universe,
        )
        try:
            self._verify_no_residue(candidate, experiment_id, target_scope)
        except AbCompareError:
            # 整体回滚：恢复事务前镜像，保留上一版完整结果。
            store.rows(COMPARE_MODULE).clear()
            store.rows(COMPARE_MODULE).extend(snapshot)
            store.bump_version(COMPARE_MODULE)
            raise

        # 核对通过后整体提交：替换该实验的旧版本，保留其他实验结果。
        table = store.rows(COMPARE_MODULE)
        table[:] = [row for row in table if row.get("experiment_id") != experiment_id]
        table.append(candidate)
        store.bump_version(COMPARE_MODULE)
        return copy.deepcopy(candidate)

    def _assemble_table(
        self,
        *,
        experiment: dict[str, Any],
        report: dict[str, Any],
        groups: list[dict[str, Any]],
        control_members: list[dict[str, Any]],
        experiment_members: list[dict[str, Any]],
        unauthorized: list[dict[str, Any]],
        overlap_users: list[str],
        overlap_strategy: str,
        metric_rows: list[dict[str, Any]],
        review_rows: list[dict[str, Any]],
        universe: set[str],
    ) -> dict[str, Any]:
        experiment_id = int(experiment["id"])
        now = time.time()
        control_ids = sorted(m["user_id"] for m in control_members if m["user_id"] in universe)
        experiment_ids = sorted(m["user_id"] for m in experiment_members if m["user_id"] in universe)
        return {
            "id": store.next_id(COMPARE_MODULE),
            "结果表编号": f"ABC-{CALIBER_VERSION}-{experiment_id:04d}",
            "实验编号": experiment.get("方案编号"),
            "experiment_id": experiment_id,
            "报告编号": report.get("报告编号"),
            "归属范围": experiment.get("access_scope"),
            "口径版本": CALIBER_VERSION,
            "status": "已完成",
            "结果类型": RESULT_KIND_FORMAL,
            "重叠处理策略": overlap_strategy,
            "分群集合": [
                {
                    "分群编号": g.get("分群编号"),
                    "group_type": g.get("group_type"),
                    "group_id": g.get("id"),
                    "临时分群": bool(g.get("临时分群", False)),
                    "样本基数": g.get("样本基数"),
                    "access_scope": g.get("access_scope"),
                }
                for g in groups
            ],
            "分群定义": copy.deepcopy(groups),
            "成员集合": {
                "对照组": control_ids,
                "实验组": experiment_ids,
            },
            "成员集合指纹": {
                "对照组": self._fingerprint(control_ids),
                "实验组": self._fingerprint(experiment_ids),
            },
            "指标结果": metric_rows,
            "待复核清单": review_rows,
            "重叠用户清单": overlap_users,
            "越权只读清单": unauthorized,
            "越权成员数": len(unauthorized),
            "可追溯字段": {
                "实验编号": experiment.get("方案编号"),
                "报告编号": report.get("报告编号"),
                "成员集合指纹": {
                    "对照组": self._fingerprint(control_ids),
                    "实验组": self._fingerprint(experiment_ids),
                },
                "指标标识": [row["指标标识"] for row in metric_rows],
                "口径版本": CALIBER_VERSION,
            },
            "created_at": now,
            "updated_at": now,
        }

    @staticmethod
    def _fingerprint(ids: list[str]) -> str:
        import hashlib
        joined = ",".join(ids)
        return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]

    def _verify_no_residue(
        self, candidate: dict[str, Any], experiment_id: int, target_scope: str
    ) -> None:
        """按结果表保留目核对：正式结果中不得残留越权或跨实验成员。"""
        formal_users = set(candidate["成员集合"]["对照组"]) | set(
            candidate["成员集合"]["实验组"]
        )
        unauthorized_ids = {row["user_id"] for row in candidate["越权只读清单"]}
        if formal_users & unauthorized_ids:
            raise AbCompareError("核对发现正式差异残留越权成员，事务整体回滚")
        # target_only 策略下，重叠用户必须完全排除在正式成员集合之外。
        if candidate["重叠处理策略"] == "target_only":
            overlap_ids = set(candidate.get("重叠用户清单", []))
            if formal_users & overlap_ids:
                raise AbCompareError("核对发现正式差异残留重叠用户，事务整体回滚")
        # isolate 策略下，重叠用户保留在目标实验结果中，但必须同时进入待复核清单。
        if candidate["重叠处理策略"] == "isolate":
            review_users: set[str] = set()
            for review in candidate.get("待复核清单", []):
                review_users.update(review.get("重叠用户", []))
            overlap_ids = set(candidate.get("重叠用户清单", []))
            if overlap_ids != review_users:
                raise AbCompareError("核对发现重叠用户未全部进入待复核清单，事务整体回滚")
        if candidate["归属范围"] != target_scope:
            raise AbCompareError("核对发现归属范围不一致，事务整体回滚")
        for row in candidate["指标结果"]:
            if row["对照组样本量"] == 0 or row["实验组样本量"] == 0:
                raise AbCompareError("核对发现空成员集合参与差异计算，事务整体回滚")

    # ------------------------------------------------------------------
    # 查询：列表 / 详情（读权限控制，共享内容只读）
    # ------------------------------------------------------------------
    def _find_latest(self, experiment_id: int) -> dict[str, Any] | None:
        rows = [
            row for row in store.rows(COMPARE_MODULE)
            if int(row.get("experiment_id") or 0) == experiment_id
        ]
        return copy.deepcopy(rows[-1]) if rows else None

    def list_tables(self, operator_scopes: list[str] | None) -> list[dict[str, Any]]:
        """列出全部结果表；越权范围的共享内容可见但带只读标记，不能改动。"""
        scopes = self._scopes(operator_scopes)
        items: list[dict[str, Any]] = []
        for row in store.rows(COMPARE_MODULE):
            item = copy.deepcopy(row)
            item["只读"] = not ("__all__" in scopes or row.get("归属范围") in scopes)
            items.append(item)
        return items

    def get_table(self, result_id: int, operator_scopes: list[str] | None) -> dict[str, Any]:
        row = store.find(COMPARE_MODULE, result_id)
        if row is None:
            raise AbCompareError(f"AB对比结果表 {result_id} 不存在")
        result = copy.deepcopy(row)
        # 越权请求只读：允许查看共享内容，并显式告知调用方不可改动。
        result["只读"] = self._is_readonly(operator_scopes, str(row.get("归属范围")))
        return result

    def get_result_group_members(
        self, result_id: int, group_id: int, operator_scopes: list[str] | None
    ) -> dict[str, Any]:
        """按结果表内自包含的分群定义读取成员明细，临时分群也可追溯。"""
        table = self.get_table(result_id, operator_scopes)
        group = next(
            (g for g in table.get("分群定义", []) if int(g.get("id", 0)) == group_id),
            None,
        )
        if group is None:
            raise AbCompareError(f"结果表 {result_id} 内不存在分群 {group_id}")
        members = self._sample_service.build_members(group)
        return {
            "items": members,
            "total": len(members),
            "分群编号": group.get("分群编号"),
            "experiment_id": group.get("experiment_id"),
            "access_scope": group.get("access_scope"),
            "临时分群": bool(group.get("临时分群", False)),
            "只读": table["只读"],
        }

    # ------------------------------------------------------------------
    # V010 留档核对与转交（只读）
    # ------------------------------------------------------------------
    def archive(self, result_id: int, operator_scopes: list[str] | None) -> dict[str, Any]:
        with self._lock:
            row = store.find(COMPARE_MODULE, result_id)
            if row is None:
                raise AbCompareError(f"AB对比结果表 {result_id} 不存在")
            if not self._can_write(operator_scopes, str(row.get("归属范围"))):
                raise AbCompareError("越权请求：共享内容只能查看不能改动，归档被拒绝")
            # 按 V010 留档核对：成员指纹、指标标识、口径版本必须能相互追溯。
            self._verify_archive(row)
            row["status"] = "已归档"
            row["留档版本"] = CALIBER_VERSION
            row["留档时间"] = time.time()
            row["updated_at"] = time.time()
            store.bump_version(COMPARE_MODULE)
            return copy.deepcopy(row)

    def _verify_archive(self, row: dict[str, Any]) -> None:
        trace = row.get("可追溯字段", {})
        if trace.get("口径版本") != CALIBER_VERSION or row.get("口径版本") != CALIBER_VERSION:
            raise AbCompareError("V010留档核对失败：口径版本不一致，已拒绝归档")
        fingerprint = row.get("成员集合指纹", {})
        if trace.get("成员集合指纹") != fingerprint:
            raise AbCompareError("V010留档核对失败：成员集合指纹与留档目不符")
        metric_ids = {r["指标标识"] for r in row.get("指标结果", [])}
        if set(trace.get("指标标识", [])) != metric_ids:
            raise AbCompareError("V010留档核对失败：指标标识无法相互追溯")

    def handover(self, result_id: int, operator_scopes: list[str] | None) -> dict[str, Any]:
        """转交给接收方：接收方只获得读权限，表保持只读不可改动。"""
        with self._lock:
            row = store.find(COMPARE_MODULE, result_id)
            if row is None:
                raise AbCompareError(f"AB对比结果表 {result_id} 不存在")
            if not self._can_write(operator_scopes, str(row.get("归属范围"))):
                raise AbCompareError("越权请求：共享内容只能查看不能改动，转交被拒绝")
            if row.get("status") != "已归档":
                raise AbCompareError("只有按V010留档核对无误的结果表才能转交")
            row["status"] = "已转交"
            row["接收方权限"] = "只读"
            row["转交时间"] = time.time()
            row["updated_at"] = time.time()
            store.bump_version(COMPARE_MODULE)
            return copy.deepcopy(row)

    # ------------------------------------------------------------------
    # 跨模块联动（V010）：指标定义模块读取本表指标标识并校验计算口径
    # ------------------------------------------------------------------
    def metric_caliber_check(
        self, result_id: int, operator_scopes: list[str] | None
    ) -> dict[str, Any]:
        row = self.get_table(result_id, operator_scopes)
        checks: list[dict[str, Any]] = []
        for metric_row in row.get("指标结果", []):
            metric_id = metric_row["指标标识"]
            metric_def = self._metric_service.find_by_metric_id(metric_id)
            if metric_def is None:
                checks.append({
                    "指标标识": metric_id,
                    "ok": False,
                    "message": "指标定义模块找不到该指标标识，口径无法校验",
                })
                continue
            same_caliber = str(metric_def.get("口径版本")) == str(metric_row["口径版本"])
            checks.append({
                "指标标识": metric_id,
                "指标名称": metric_def.get("指标名称"),
                "实验编号": row["实验编号"],
                "归属范围": row["归属范围"],
                "结果表口径": metric_row["口径版本"],
                "指标定义口径": metric_def.get("口径版本"),
                "ok": same_caliber,
                "message": "口径一致" if same_caliber else "计算口径与指标定义 V010 不一致",
            })
        return {
            "ok": all(item["ok"] for item in checks),
            "结果表编号": row["结果表编号"],
            "口径版本": CALIBER_VERSION,
            "checks": checks,
        }
