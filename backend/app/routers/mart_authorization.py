"""集市授权过滤记录接口：版本输入、核对、回退与追溯。"""
from __future__ import annotations

import csv
import io
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.mart_access import identity
from app.services.mart_authorization import MartAuthorizationService

router = APIRouter(prefix="/api/mart_authorization", tags=["集市授权过滤记录"])

service = MartAuthorizationService()

LIST_FIELDS = [
    "记录编号", "用户组", "主题域", "授权维度", "授权依据", "来源段",
    "版本号", "主版本号", "主版本边界", "处理次序",
    "版本状态", "核对状态", "操作人", "归属人", "记录状态",
]
STATUSES = ["草稿", "待核对", "已生效", "已替换", "冲突", "已回退", "已归档"]


class AuthActionPayload(BaseModel):
    """集市授权过滤记录的动作载荷，允许携带操作人与角色用于归属校验。"""

    action: str
    remark: str | None = None
    operator: str | None = None
    role: str | None = None
    values: dict[str, Any] = Field(default_factory=dict)


def query_filters(request: Request) -> dict[str, str]:
    """只接受当前模块声明过的字段，忽略分页等保留参数。"""
    return {
        key: value.strip()
        for key, value in request.query_params.items()
        if key in LIST_FIELDS and value.strip()
    }


@router.get("")
def list_records(
    request: Request,
    keyword: str | None = Query(default=None, description="按记录编号检索"),
    status: str | None = Query(default=None, description="草稿、待核对、已生效、冲突、已回退、已归档"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=200),
) -> PageResult[dict]:
    """按页面字段、记录编号关键字与状态过滤集市授权过滤记录。"""
    items, total = service.list_records(
        filters=query_filters(request), keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/summary")
def get_summary() -> dict[str, Any]:
    """记录概况：总数、有效版本、冲突待核对与已回退版本。"""
    return service.summary()


@router.get("/export")
def export_records(
    request: Request,
    keyword: str | None = Query(default=None),
    status: str | None = Query(default=None),
    group: str | None = Query(default=None, description="按用户组导出，并列出被过滤维度与授权依据"),
) -> StreamingResponse:
    """下载 UTF-8 CSV；按用户组导出时同时列出被过滤维度与授权依据。"""
    if group:
        return _export_group(group, status)
    items, _ = service.list_records(
        filters=query_filters(request), keyword=keyword, status=status, page=1, size=1000000)
    output = io.StringIO()
    output.write("﻿")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["id", *LIST_FIELDS, "核对说明", "主版本边界", "status"])
    for item in items:
        _writer_row(writer, [
            item.get("id"),
            *(item.get(field, "") for field in LIST_FIELDS),
            item.get("核对说明", ""),
            item.get("主版本边界", ""),
            item.get("status", ""),
        ])
    return StreamingResponse(
        iter([output.getvalue()]), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="mart_authorization.csv"'})


def _export_group(group: str, status: str | None, mode: str = "主题域") -> StreamingResponse:
    """按用户组导出可读集市表，列出被过滤维度与授权依据。"""
    from app.services.mart_access import filter_rows

    items, summary = filter_rows(group, mode)
    output = io.StringIO()
    output.write("﻿")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow([
        "表编号", "表名称", "主题域", "事实粒度", "关联维度", "可读维度",
        "被过滤维度", "度量字段", "授权依据", "授权用户组", "授权口径",
    ])
    for item in items:
        _writer_row(writer, [
            item.get("表编号"), item.get("表名称"), item.get("主题域"), item.get("事实粒度"),
            item.get("关联维度"), item.get("可读维度"), item.get("被过滤维度"), item.get("度量字段"),
            item.get("授权依据"), item.get("授权用户组"), item.get("授权口径"),
        ])
    for denied in summary.get("未授权表", []):
        _writer_row(writer, [
            denied.get("表编号"), denied.get("表名称"), denied.get("主题域"), "", "", "",
            denied.get("被过滤维度"), "", denied.get("授权依据"),
            summary.get("用户组"), summary.get("授权口径"),
        ])
    return StreamingResponse(
        iter([output.getvalue()]), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="mart_authorization_group.csv"'})


@router.get("/{entry_id}")
def get_record(entry_id: int) -> dict:
    """读取单条集市授权过滤记录。"""
    entry = service.get_record(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"集市授权过滤记录 {entry_id} 不存在或已归档")
    return entry


@router.get("/{entry_id}/trace")
def trace_record(entry_id: int) -> dict:
    """追溯同一段来源：版本链、变更轨迹与结果数据流。"""
    payload = service.trace(entry_id)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"集市授权过滤记录 {entry_id} 不存在或已归档")
    return payload


@router.post("")
def publish_record(payload: EntryPayload, request: Request) -> ActionResult:
    """持久化一条集市授权过滤记录（版本输入）；同一来源段只保留一个有效版本。"""
    actor, role = identity(payload, request)
    entry, message = service.publish(payload.values, actor=actor, role=role)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/reconcile")
def reconcile_records(payload: EntryPayload, request: Request) -> ActionResult:
    """集市核对接口：消费并持久化记录，核对主版本边界。"""
    actor, role = identity(payload, request)
    result, message = service.reconcile(payload.values, actor=actor, role=role)
    if result is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=result)


@router.post("/{entry_id}/actions")
def run_action(entry_id: int, payload: AuthActionPayload, request: Request) -> ActionResult:
    """执行提交核对、核对通过、标记冲突、回退版本、归档记录。"""
    actor, role = identity(payload, request)
    entry, message = service.run_action(entry_id, payload.action.strip(), actor=actor, role=role)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


def _csv_cell(value: Any) -> str:
    text = str(value) if value is not None else ""
    if text.startswith(("=", "+", "-", "@")):
        text = "'" + text
    return text


def _writer_row(writer: csv.writer, values: list[Any]) -> None:
    writer.writerow([_csv_cell(value) for value in values])
