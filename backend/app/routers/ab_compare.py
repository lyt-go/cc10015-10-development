"""AB对比结果表接口：按实验归属生成、留档、转交与V010口径校验。

归属范围通过请求头 X-Operator-Scopes 传入（逗号分隔，可多个）；
不传时视为平台管理员。越权写入直接拒绝，越权读取仅在显式授权时放行只读。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, Query
from pydantic import BaseModel, Field

from app.services.ab_compare import (
    CALIBER_VERSION,
    OVERLAP_STRATEGIES,
    AbCompareError,
    AbCompareService,
)

router = APIRouter(prefix="/api/ab_result/compare", tags=["AB对比结果表"])
service = AbCompareService()


class CompareGeneratePayload(BaseModel):
    experiment_id: int
    overlap_strategy: str = Field(default="target_only")
    simulate_interrupt: bool = False


def parse_scopes(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    scopes = [item.strip() for item in raw.split(",") if item.strip()]
    return scopes or None


def _error(exc: AbCompareError) -> dict[str, Any]:
    return {"ok": False, "message": str(exc)}


@router.get("/scopes")
def scope_meta() -> dict[str, Any]:
    """归属范围与重叠策略元数据，供导航页与抽屉渲染同一套选项。"""
    return {
        "caliber_version": CALIBER_VERSION,
        "overlap_strategies": list(OVERLAP_STRATEGIES),
        "strategy_labels": {
            "target_only": "只保留目标实验成员（正式对比）",
            "isolate": "重叠用户隔离到待复核清单",
        },
    }


@router.get("/eligible_experiments")
def eligible_experiments() -> dict[str, Any]:
    """可生成对比结果表的实验（带可读分析报告与归属范围）。"""
    items = service.list_eligible_experiments()
    return {"items": items, "total": len(items)}


@router.get("")
def list_tables(x_operator_scopes: str | None = Header(default=None)) -> dict[str, Any]:
    """按当前归属范围列出AB对比结果表；无授权范围的表不会出现。"""
    scopes = parse_scopes(x_operator_scopes)
    items = service.list_tables(scopes)
    return {"items": items, "total": len(items), "caliber_version": CALIBER_VERSION}


@router.post("")
def generate_table(
    payload: CompareGeneratePayload,
    x_operator_scopes: str | None = Header(default=None),
) -> dict[str, Any]:
    """读取分析报告与分群成员明细，按实验归属生成AB对比结果表。"""
    scopes = parse_scopes(x_operator_scopes)
    try:
        table = service.generate(
            payload.experiment_id,
            operator_scopes=scopes,
            overlap_strategy=payload.overlap_strategy,
            simulate_interrupt=payload.simulate_interrupt,
        )
    except AbCompareError as exc:
        return _error(exc)
    return {"ok": True, "message": "AB对比结果表已生成", "entry": table}


@router.get("/{result_id}")
def get_table(
    result_id: int,
    x_operator_scopes: str | None = Header(default=None),
) -> dict[str, Any]:
    try:
        return service.get_table(result_id, parse_scopes(x_operator_scopes))
    except AbCompareError as exc:
        return _error(exc)


@router.get("/{result_id}/groups/{group_id}/members")
def get_result_group_members(
    result_id: int,
    group_id: int,
    x_operator_scopes: str | None = Header(default=None),
) -> dict[str, Any]:
    """读取结果表内某分群的成员明细（含临时分群），供抽屉核对同一成员集合。"""
    try:
        return service.get_result_group_members(
            result_id, group_id, parse_scopes(x_operator_scopes)
        )
    except AbCompareError as exc:
        return _error(exc)


@router.post("/{result_id}/archive")
def archive_table(
    result_id: int,
    x_operator_scopes: str | None = Header(default=None),
) -> dict[str, Any]:
    """按V010留档核对后归档；核对失败在事务中拒绝，不改原表。"""
    try:
        entry = service.archive(result_id, parse_scopes(x_operator_scopes))
    except AbCompareError as exc:
        return _error(exc)
    return {"ok": True, "message": "V010留档核对无误，结果表已归档", "entry": entry}


@router.post("/{result_id}/handover")
def handover_table(
    result_id: int,
    x_operator_scopes: str | None = Header(default=None),
) -> dict[str, Any]:
    """转交给接收方V010：接收方只读，共享内容不可改动。"""
    try:
        entry = service.handover(result_id, parse_scopes(x_operator_scopes))
    except AbCompareError as exc:
        return _error(exc)
    return {"ok": True, "message": "已转交接收方，权限为只读", "entry": entry}


@router.get("/{result_id}/caliber_check")
def caliber_check(
    result_id: int,
    x_operator_scopes: str | None = Header(default=None),
) -> dict[str, Any]:
    """跨模块联动（V010）：指标定义模块读取结果表指标标识并校验计算口径。"""
    try:
        return service.metric_caliber_check(result_id, parse_scopes(x_operator_scopes))
    except AbCompareError as exc:
        return _error(exc)
