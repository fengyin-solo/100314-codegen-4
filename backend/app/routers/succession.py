"""采掘接续接口：一个工作面一条台账，计划调整走版本链，实际进度回写台账。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.succession import SuccessionService

router = APIRouter(prefix="/api/succession", tags=["采掘接续"])

service = SuccessionService()

STATUSES = ["未开工", "回采中", "已完工"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按工作面编号或名称检索"),
    status: str | None = Query(default=None, description="未开工、回采中、已完工"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """接续计划台账列表：计划类字段全部来自当前版本，各处读到的当前版本同源。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一个采煤工作面的接续计划，同时生成 V1 草稿版，批复后生效。"""
    entry, problems = service.create_entry(payload.values)
    if problems:
        return ActionResult(ok=False, message="；".join(problems))
    return ActionResult(ok=True, message="接续计划已登记，V1 草稿待批复", entry=entry)


@router.get("/caliber")
def get_caliber() -> dict[str, Any]:
    """读取当前接续口径：台账偏差与页面展示都以此为准。"""
    return service.caliber()


@router.post("/caliber", response_model=ActionResult)
def adjust_caliber(payload: EntryPayload) -> ActionResult:
    """调整接续口径并按新口径重算台账偏差；历史版本仍按当时的进度口径保留。"""
    result, message = service.adjust_caliber(payload.values)
    if result is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=result)


@router.post("/backfill", response_model=ActionResult)
def backfill_entries() -> ActionResult:
    """存量数据按接续月份回填：给没有版本链的台账行补首版。可重复执行，已回填的自动跳过。"""
    result = service.backfill()
    return ActionResult(ok=True, message=f"存量回填完成：回填 {result['回填条数']} 条", entry=result)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出接续计划台账：与列表同源的当前版本数据。"""
    items = service.export_entries()
    return {"module": "succession", "total": len(items), "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """单条台账明细：含当前版本与进度记录；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"接续计划 {entry_id} 不存在或已归档")
    return entry


@router.get("/{entry_id}/versions")
def list_versions(entry_id: int) -> dict[str, Any]:
    """版本链：新版在前；历史版本按当时的进度口径保留偏差。"""
    versions = service.versions_of(entry_id)
    if versions is None:
        raise HTTPException(status_code=404, detail=f"接续计划 {entry_id} 不存在或已归档")
    return {"total": len(versions), "items": versions}


@router.post("/{entry_id}/approve", response_model=ActionResult)
def approve_entry(entry_id: int, payload: EntryPayload) -> ActionResult:
    """批复当前版本；已批过的版本不能就地改，只能另出新版。"""
    entry, message = service.approve(entry_id, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/revise", response_model=ActionResult)
def revise_entry(entry_id: int, payload: EntryPayload) -> ActionResult:
    """计划调整：以当前版本为底另出新版，原版保留。"""
    entry, message = service.revise(entry_id, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/progress", response_model=ActionResult)
def register_progress(entry_id: int, payload: EntryPayload) -> ActionResult:
    """登记实际进度并回写台账；衔接关系与版本冲突时以版本里的先后为准。"""
    entry, message = service.register_progress(entry_id, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
