"""采掘接续接口：一个工作面一条台账，计划按版本管理，进度登记回写台账。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.succession import SuccessionService

router = APIRouter(prefix="/api/succession", tags=["采掘接续"])

service = SuccessionService()

LIST_FIELDS = ["工作面编号", "工作面名称", "所在采区", "当前版本", "接续方式", "计划开工月份", "计划完工月份", "实际开工月份", "实际完工月份", "偏差(月)", "衔接结论", "台账状态"]
STATUSES = ["接续正常", "衔接冲突", "已采完"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按工作面编号检索"),
    status: str | None = Query(default=None, description="接续正常、衔接冲突、已采完"),
    mode: str | None = Query(default=None, description="按当前版本的接续方式过滤"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按工作面编号、台账状态与接续方式过滤接续计划台账；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, mode=mode, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单个工作面的台账明细，含全部版本与进度登记；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"接续台账 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一个采煤工作面的接续计划：台账加 V1 草稿版，批准后成为当前版本。"""
    entry, message = service.create_entry(payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/versions", response_model=ActionResult)
def create_version(entry_id: int, payload: EntryPayload) -> ActionResult:
    """计划调整：从当前批准版另出一版草稿，已批准的版本不在原地改。"""
    version, message = service.create_version(entry_id, payload.values)
    if version is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=version)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单个工作面执行批准版本；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    if action != "批准版本":
        return ActionResult(ok=False, message=f"动作「{action}」不属于采掘接续可执行范围")
    entry, message = service.approve_version(entry_id)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/progress", response_model=ActionResult)
def register_progress(entry_id: int, payload: EntryPayload) -> ActionResult:
    """登记实际进度：回写台账，衔接冲突时以当前版本里的先后为准。"""
    entry, message = service.register_progress(entry_id, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出接续计划台账：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "succession", "total": total, "items": items}
