"""AB对比结果表：实验归属过滤、同一成员集合差异计算、越权只读、
版本冲突两种策略、重算中断沿用、残留事务回滚、V010留档与转交、跨模块口径校验。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.ab_compare import AbCompareError, AbCompareService
from app.services.experiment import ExperimentService
from app.store import store


def _clear_all():
    for key in list(store._tables.keys()):
        store._tables[key] = []


def _setup_two_experiments():
    """两个实验各自生成对照/实验分群，分群间存在共享用户与越权成员。"""
    es = ExperimentService()
    es.create_entry({
        "方案编号": "EXPE-201", "实验名称": "实验甲",
        "对照组说明": "对照", "实验组说明": "实验",
        "样本总量": "120", "分流比例": "5:5",
    })
    es.create_entry({
        "方案编号": "EXPE-202", "实验名称": "实验乙",
        "对照组说明": "对照", "实验组说明": "实验",
        "样本总量": "100", "分流比例": "5:5",
    })
    # 为两个实验补分析报告与V010指标
    store.rows("metric_def").append({
        "id": 1, "指标编号": "METR-X-V010", "指标名称": "转化率",
        "口径版本": "V010", "status": "已生效",
    })
    for exp_id in (1, 2):
        store.rows("ab_result").append({
            "id": exp_id, "报告编号": f"R-{exp_id}", "实验编号": f"EXPE-20{exp_id}",
            "分析指标": "METR-X-V010", "metric_id": "METR-X-V010",
            "experiment_id": exp_id, "status": "已完成",
        })


def test_same_member_set_for_filter_and_diff_and_deterministic():
    """归属过滤与差异计算使用同一成员集合；重算结果可复现。"""
    _clear_all()
    _setup_two_experiments()
    svc = AbCompareService()
    first = svc.generate(1, operator_scopes=None)
    second = svc.generate(1, operator_scopes=None)
    assert first["成员集合指纹"] == second["成员集合指纹"]
    row = first["指标结果"][0]
    # 样本量必须等于正式成员集合大小，证明差异计算与过滤是同一批成员
    assert row["对照组样本量"] == len(first["成员集合"]["对照组"])
    assert row["实验组样本量"] == len(first["成员集合"]["实验组"])
    assert row["实验组均值"] > row["对照组均值"]  # 实验组总体偏高


def test_unauthorized_members_never_enter_formal_diff():
    """越权成员只进只读清单，不进入正式差异。"""
    _clear_all()
    _setup_two_experiments()
    svc = AbCompareService()
    table = svc.generate(1, operator_scopes=None)
    assert table["越权成员数"] > 0
    formal = set(table["成员集合"]["对照组"]) | set(table["成员集合"]["实验组"])
    foreign = {m["user_id"] for m in table["越权只读清单"]}
    assert formal & foreign == set()
    assert all("越权原因" in m for m in table["越权只读清单"])


def test_diff_rows_stay_within_same_experiment():
    """每行差异只来自同一实验：两个实验的成员集合互不混入。"""
    _clear_all()
    _setup_two_experiments()
    svc = AbCompareService()
    t1 = svc.generate(1, operator_scopes=None)
    t2 = svc.generate(2, operator_scopes=None)
    users1 = set(t1["成员集合"]["对照组"]) | set(t1["成员集合"]["实验组"])
    users2 = set(t2["成员集合"]["对照组"]) | set(t2["成员集合"]["实验组"])
    # 普通成员以分群id为前缀，跨实验不应重合
    normal1 = {u for u in users1 if u.startswith("U")}
    normal2 = {u for u in users2 if u.startswith("U")}
    assert normal1 & normal2 == set()
    assert t1["实验编号"] != t2["实验编号"]


def test_cross_scope_write_blocked_but_read_allowed():
    """越权请求只读：跨范围写被拒，共享内容仍可只读查看。"""
    _clear_all()
    _setup_two_experiments()
    svc = AbCompareService()
    table = svc.generate(1, operator_scopes=["scope-a"])
    try:
        svc.generate(1, operator_scopes=["scope-b"])
        raise AssertionError("越权写入应被拒绝")
    except AbCompareError:
        pass
    # 列表对越权范围仍可见，但带只读标记
    visible = svc.list_tables(["scope-b"])
    assert len(visible) == 1
    assert visible[0]["只读"] is True
    # 详情同样可读且标记只读
    detail = svc.get_table(table["id"], ["scope-b"])
    assert detail["只读"] is True
    # 授权范围不是只读
    assert svc.get_table(table["id"], ["scope-a"])["只读"] is False
    # 管理员可看全部
    assert len(svc.list_tables(None)) == 1
    # 越权范围的归档/转交同样被拒
    try:
        svc.archive(table["id"], ["scope-b"])
        raise AssertionError("越权归档应被拒绝")
    except AbCompareError:
        pass


def test_overlap_target_only_strategy():
    """策略一：只保留目标实验成员，正式结果不含重叠用户。"""
    _clear_all()
    _setup_two_experiments()
    svc = AbCompareService()
    table = svc.generate(1, operator_scopes=None, overlap_strategy="target_only")
    formal = set(table["成员集合"]["对照组"]) | set(table["成员集合"]["实验组"])
    assert formal & set(table["重叠用户清单"]) == set()
    assert table["待复核清单"] == []
    assert table["结果类型"] == "正式结果"


def test_overlap_isolate_strategy():
    """策略二：保留目标实验结果，重叠用户单列待复核清单。"""
    _clear_all()
    _setup_two_experiments()
    svc = AbCompareService()
    table = svc.generate(1, operator_scopes=None, overlap_strategy="isolate")
    formal = set(table["成员集合"]["对照组"]) | set(table["成员集合"]["实验组"])
    assert formal & set(table["重叠用户清单"]) == set(table["重叠用户清单"])
    review_users = set()
    for item in table["待复核清单"]:
        review_users.update(item["重叠用户"])
    assert review_users == set(table["重叠用户清单"])
    assert table["待复核清单"][0]["结果类型"] == "待复核结果"


def test_interrupt_reuses_previous_complete_table():
    """成员重算中断：沿用上一版完整结果，不用越权成员补齐。"""
    _clear_all()
    _setup_two_experiments()
    svc = AbCompareService()
    previous = svc.generate(1, operator_scopes=None)
    try:
        svc.generate(1, operator_scopes=None, simulate_interrupt=True)
    except AbCompareError as exc:  # 无上一版时才会抛，这里已有上一版
        raise AssertionError(f"不应抛错: {exc}")
    interrupted = svc.generate(1, operator_scopes=None, simulate_interrupt=True)
    assert interrupted["status"] == "已中断"
    assert interrupted["成员集合指纹"] == previous["成员集合指纹"]
    formal = set(interrupted["成员集合"]["对照组"]) | set(interrupted["成员集合"]["实验组"])
    assert not any(u.startswith("FOREIGN") for u in formal)


def test_residue_triggers_full_rollback():
    """残留出现时按结果表保留目核对，事务整体回滚，旧版本保留。"""
    _clear_all()
    _setup_two_experiments()
    svc = AbCompareService()
    table = svc.generate(1, operator_scopes=None)
    snapshot_count = len(store.rows("ab_compare"))

    def force_residue(candidate, experiment_id, target_scope):
        raise AbCompareError("模拟残留")

    svc._verify_no_residue = force_residue
    try:
        svc.generate(1, operator_scopes=None)
        raise AssertionError("应因残留回滚")
    except AbCompareError:
        pass
    rows = store.rows("ab_compare")
    assert len(rows) == snapshot_count
    assert rows[-1]["id"] == table["id"]
    assert rows[-1]["status"] == "已完成"


def test_archive_handover_and_readonly():
    """V010留档核对后归档、转交，接收方只读。"""
    _clear_all()
    _setup_two_experiments()
    svc = AbCompareService()
    table = svc.generate(1, operator_scopes=["scope-a"])
    archived = svc.archive(table["id"], operator_scopes=["scope-a"])
    assert archived["status"] == "已归档"
    assert archived["留档版本"] == "V010"
    handed = svc.handover(table["id"], operator_scopes=["scope-a"])
    assert handed["status"] == "已转交"
    assert handed["接收方权限"] == "只读"
    # 非归档状态不能转交
    other = svc.generate(2, operator_scopes=["scope-b"])
    try:
        svc.handover(other["id"], operator_scopes=["scope-b"])
        raise AssertionError("未归档不应允许转交")
    except AbCompareError:
        pass


def test_cross_module_caliber_check_v010():
    """跨模块联动V010：指标定义按指标标识与实验归属校验口径。"""
    _clear_all()
    _setup_two_experiments()
    svc = AbCompareService()
    table = svc.generate(1, operator_scopes=None)
    result = svc.metric_caliber_check(table["id"], operator_scopes=None)
    assert result["ok"] is True
    assert result["checks"][0]["指标标识"] == "METR-X-V010"
    assert result["checks"][0]["结果表口径"] == "V010"
    # 口径被改动后校验失败
    metric = store.find("metric_def", 1)
    metric["口径版本"] = "V009"
    result = svc.metric_caliber_check(table["id"], operator_scopes=None)
    assert result["ok"] is False


def test_traceability_fields_link_each_other():
    """实验编号、成员集合、指标口径可相互追溯。"""
    _clear_all()
    _setup_two_experiments()
    svc = AbCompareService()
    table = svc.generate(1, operator_scopes=None)
    trace = table["可追溯字段"]
    assert trace["实验编号"] == table["实验编号"]
    assert trace["成员集合指纹"] == table["成员集合指纹"]
    assert trace["指标标识"] == [r["指标标识"] for r in table["指标结果"]]
    assert trace["口径版本"] == "V010"
