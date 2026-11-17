"""数据集市 DAG 拓扑接口：返回节点、连线图结构。

所有读取接口都接受 group / auth_mode：带上用户组时按主题域授权 + 关联维度
过滤返回可读集市数据；不带时保持维护态的全量视图。
"""
from __future__ import annotations

import csv
import io
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.data_mart import DataMartService
from app.services.mart_access import (
    DEFAULT_MODE,
    DIMENSION_MODE,
    DOMAIN_MODE,
    filter_rows,
    identity,
)

router = APIRouter(prefix="/api/data_mart", tags=["数据集市"])
service = DataMartService()
LIST_FIELDS = ["表编号", "表名称", "主题域", "事实粒度", "关联维度", "度量字段", "刷新周期", "表状态"]
STATUSES = ["草稿", "已建模", "已发布", "已下线"]
AUTH_MODES = [DOMAIN_MODE, DIMENSION_MODE]


class MartActionPayload(BaseModel):
    """集市表动作载荷，允许携带操作人与角色用于归属校验。"""

    action: str
    remark: str | None = None
    operator: str | None = None
    role: str | None = None


def csv_cell(value: Any) -> str:
    text = str(value) if value is not None else ""
    if text and text[0] in "=+-@":
        text = "'" + text
    return '"' + text.replace('"', '""') + '"'


def _mode(value: str | None) -> str:
    return DIMENSION_MODE if value in (DIMENSION_MODE, "dimension", "维度", "关联维度归属") else DEFAULT_MODE


@router.get("")
def get_graph(
    group: str | None = Query(default=None, description="用户组编号或名称；带上后按授权过滤"),
    auth_mode: str | None = Query(default=None, description="主题域、关联维度"),
) -> dict[str, Any]:
    """返回节点与边组成的 DAG 图数据；带用户组时只返回授权主题域与可读维度。"""
    return service.get_graph(group=group, mode=auth_mode)


@router.get("/export")
def export_entries(
    group: str | None = Query(default=None, description="用户组编号或名称"),
    auth_mode: str | None = Query(default=None, description="主题域、关联维度"),
) -> StreamingResponse:
    """导出关系清单；带用户组时列出被过滤维度与授权依据。"""
    if group:
        items, summary = filter_rows(group, _mode(auth_mode))
        return _group_csv(items, summary)
    nodes, edges = service.raw_data()
    buf = io.StringIO(newline="")
    writer = csv.writer(buf)
    writer.writerow(["type", "id", "name", "from", "to", "label", "status"])
    for node in nodes:
        writer.writerow(["node", node.get("id",""), csv_cell(node.get("name","")), "", "", "", node.get("status","")])
    for edge in edges:
        writer.writerow(["edge", "", "", edge.get("from",""), edge.get("to",""), edge.get("label",""), ""])
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": "attachment; filename=data_mart.csv"})


@router.get("/domains")
def get_domains(group: str | None = Query(default=None, description="用户组编号或名称")) -> dict[str, Any]:
    """数据集市页的主题域选项：带上用户组时只返回该组可访问的主题域。"""
    return {"domains": service.visible_domains(group) if group else [], "group": group or ""}


@router.get("/access")
def get_access(
    group: str = Query(description="用户组编号或名称"),
    auth_mode: str | None = Query(default=None, description="主题域、关联维度"),
    domain: str | None = Query(default=None, description="只看某个主题域"),
) -> dict[str, Any]:
    """按用户组返回可读取的集市数据、被过滤维度与授权依据。"""
    items, summary = filter_rows(group, _mode(auth_mode), domain)
    return {"items": items, "summary": summary, "modes": AUTH_MODES}


@router.get("/{entry_id}/authorizations")
def get_entry_authorizations(entry_id: int) -> dict[str, Any]:
    """跨模块读取：沿着集市表的结果数据流定位其主题域的授权过滤记录变化。"""
    from app.services.mart_access import normalize_tokens
    from app.services.mart_authorization import service as auth_service

    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"集市表 {entry_id} 不存在或已归档")
    domain = str(entry.get("主题域") or "")
    records = [
        record for record in auth_service.list_records(size=100000)[0]
        if str(record.get("主题域") or "") == domain
    ]
    return {
        "表编号": entry.get("表编号"),
        "表名称": entry.get("表名称"),
        "主题域": domain,
        "关联维度": normalize_tokens(entry.get("关联维度")),
        "items": records,
        "total": len(records),
    }


@router.get("/{entry_id}")
def get_entry(
    entry_id: int,
    group: str | None = Query(default=None, description="用户组编号或名称"),
    auth_mode: str | None = Query(default=None, description="主题域、关联维度"),
) -> dict:
    entry = service.get_entry_for_group(entry_id, group, auth_mode)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"集市表 {entry_id} 不存在、已归档或当前用户组未授权")
    return entry


@router.post("")
def create_entry(payload: EntryPayload, request: Request) -> ActionResult:
    actor, role = identity(payload, request)
    entry_or_none, missing = service.create_entry(payload.values, actor=actor, role=role)
    if entry_or_none is None:
        if isinstance(missing, str):
            return ActionResult(ok=False, message=missing)
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="集市表已登记", entry=entry_or_none)


@router.post("/{entry_id}/actions")
def run_action(entry_id: int, payload: MartActionPayload, request: Request) -> ActionResult:
    actor, role = identity(payload, request)
    entry_or_none, message = service.run_action(entry_id, payload.action, actor=actor, role=role)
    if entry_or_none is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry_or_none)


def _group_csv(items: list[dict[str, Any]], summary: dict[str, Any]) -> StreamingResponse:
    buf = io.StringIO(newline="")
    writer = csv.writer(buf)
    writer.writerow([
        "表编号", "表名称", "主题域", "事实粒度", "关联维度", "可读维度",
        "被过滤维度", "度量字段", "授权依据", "授权用户组", "授权口径",
    ])

    def cell(value: Any) -> str:
        text = "" if value is None else str(value)
        return "'" + text if text.startswith(("=", "+", "-", "@")) else text

    for item in items:
        writer.writerow([cell(item.get(key)) for key in (
            "表编号", "表名称", "主题域", "事实粒度", "关联维度", "可读维度",
            "被过滤维度", "度量字段", "授权依据", "授权用户组", "授权口径",
        )])
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": "attachment; filename=data_mart.csv"})
