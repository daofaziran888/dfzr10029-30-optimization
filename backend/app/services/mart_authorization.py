"""集市授权过滤记录服务：版本生成、核对、回退与来源追溯。

授权过滤记录是「主题域授权 + 关联维度过滤」落库后的版本对象：
- 同一段来源（来源段）下保留历史版本，回退后仍能追溯同一段来源；
- 处理次序兼容既有数据，乱序到达的记录进入冲突等待核对；
- 写操作加锁串行，最终同一段来源只保留一个有效版本；
- 核对接口消费记录并核对主版本边界，把结果持久化回记录本身。
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any

from app.services.mart_access import (
    DIMENSION_MODE,
    DOMAIN_MODE,
    known_domains,
    normalize_tokens,
    permission_denial,
    resolve_group,
    group_profile,
)
from app.store import store

MODULE = "mart_authorization"
LIST_FIELDS = [
    "记录编号", "用户组", "主题域", "授权维度", "授权依据", "来源段",
    "版本号", "主版本号", "主版本边界", "处理次序",
    "版本状态", "核对状态", "操作人", "归属人", "记录状态",
]
REQUIRED_FIELDS = ["用户组", "主题域"]
STATUS_ORDER = ["草稿", "待核对", "已生效", "已替换", "冲突", "已回退", "已归档"]
ACTION_RULES = {
    "提交核对": "待核对",
    "核对通过": "已生效",
    "标记冲突": "冲突",
    "回退版本": "已回退",
    "归档记录": "已归档",
}
NEGATIVE_ACTIONS = ["标记冲突", "回退版本"]

_LOCK = threading.RLock()
_ACTIVE_VERSION = "有效"
_ROLLED_BACK = "已回退"
_REPLACED = "已替换"


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _seq(value: Any) -> int | None:
    """处理次序/版本号允许从 0 开始编号，需要区分「未提供」与「0」。"""
    if value is None or str(value).strip() == "":
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _key(record: dict[str, Any]) -> tuple[str, str, str]:
    return (
        _text(record.get("用户组")),
        _text(record.get("主题域")),
        _text(record.get("来源段")) or "默认来源段",
    )


def _record_key(values: dict[str, Any]) -> tuple[str, str, str]:
    return (
        _text(values.get("用户组")),
        _text(values.get("主题域")),
        _text(values.get("来源段")) or "默认来源段",
    )


def _is_effective(record: dict[str, Any]) -> bool:
    return (
        _text(record.get("版本状态")) == _ACTIVE_VERSION
        and _text(record.get("核对状态")) != "冲突"
        and _text(record.get("记录状态")) not in {"已回退", "已归档"}
    )


def _order(record: dict[str, Any]) -> int:
    return _as_int(record.get("处理次序"))


def _version(record: dict[str, Any]) -> int:
    return _as_int(record.get("版本号"), 1)


_HISTORY_STATES = {_ROLLED_BACK, "已归档", _REPLACED}


def _is_history(record: dict[str, Any]) -> bool:
    """回退、替换、归档的记录只是同一来源段的历史，不参与次序与版本比较。"""
    return _text(record.get("版本状态")) in _HISTORY_STATES or _text(record.get("记录状态")) in _HISTORY_STATES


def _live(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [record for record in records if not _is_history(record)]


class MartAuthorizationService:
    # ---------- 查询 ----------

    def list_records(
        self,
        *,
        filters: dict[str, str] | None = None,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = list(store.rows(MODULE))
        for field, expected in (filters or {}).items():
            rows = [
                row for row in rows
                if expected.casefold() in str(row.get(field, "")).casefold()
            ]
        if keyword:
            rows = [
                row for row in rows
                if keyword.casefold() in str(row.get("记录编号", "")).casefold()
            ]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        rows = sorted(rows, key=lambda row: (_order(row), _version(row), _as_int(row.get("id"))))
        total = len(rows)
        start = (page - 1) * size
        return rows[start:start + size], total

    def get_record(self, record_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, record_id)

    def find_by_code(self, code: str) -> dict[str, Any] | None:
        for row in store.rows(MODULE):
            if _text(row.get("记录编号")) == _text(code):
                return row
        return None

    def summary(self) -> dict[str, Any]:
        rows = store.rows(MODULE)
        return {
            "记录总数": len(rows),
            "有效版本": sum(1 for row in rows if _is_effective(row)),
            "冲突待核对": sum(1 for row in rows if _text(row.get("核对状态")) == "冲突"),
            "已回退版本": sum(1 for row in rows if _text(row.get("版本状态")) == _ROLLED_BACK),
        }

    def records_for_group(self, group_code: str) -> list[dict[str, Any]]:
        return [
            row for row in store.rows(MODULE)
            if _text(row.get("用户组")) == _text(group_code)
        ]

    def records_for_dimension(self, dimension_code: str) -> list[dict[str, Any]]:
        return [
            row for row in store.rows(MODULE)
            if _text(dimension_code) in normalize_tokens(row.get("授权维度"))
        ]

    # ---------- 内部 ----------

    def _next_code(self) -> str:
        numbers = [
            _as_int(_text(row.get("记录编号")).removeprefix("AUTH-"))
            for row in store.rows(MODULE)
        ]
        return f"AUTH-{max(numbers, default=0) + 1:04d}"

    def _records_for_key(self, key: tuple[str, str, str]) -> list[dict[str, Any]]:
        return [row for row in store.rows(MODULE) if _key(row) == key]

    def _ensure_single_effective(self, key: tuple[str, str, str]) -> dict[str, Any] | None:
        """同一段来源最终只保留一个有效版本。"""
        candidates = [
            row for row in self._records_for_key(key)
            if _text(row.get("记录状态")) not in {"已回退", "已归档", "已替换", "冲突"}
            and _text(row.get("核对状态")) != "冲突"
        ]
        if not candidates:
            return None
        winner = max(candidates, key=lambda row: (_order(row), _version(row), _as_int(row.get("id"))))
        for row in self._records_for_key(key):
            if row is winner:
                row["版本状态"] = _ACTIVE_VERSION
                if _text(row.get("记录状态")) == _REPLACED:
                    row.update({"记录状态": "已生效", "status": "已生效"})
                continue
            if (
                _text(row.get("版本状态")) == _ACTIVE_VERSION
                and _text(row.get("核对状态")) != "冲突"
            ):
                row.update({
                    "版本状态": _REPLACED,
                    "记录状态": _REPLACED,
                    "status": _REPLACED,
                    "pending": False,
                })
        return winner

    def _append_trace(self, record: dict[str, Any], action: str, actor: str, note: str = "") -> None:
        trail = record.setdefault("变更轨迹", [])
        if not isinstance(trail, list):
            trail = []
            record["变更轨迹"] = trail
        trail.append({
            "时间": _now(),
            "动作": action,
            "操作人": actor,
            "记录状态": record.get("记录状态", ""),
            "版本状态": record.get("版本状态", ""),
            "核对状态": record.get("核对状态", ""),
            "说明": note,
        })

    def _validate(self, values: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
        cleaned: dict[str, Any] = {}
        for field in LIST_FIELDS:
            if field in values and values.get(field) is not None:
                cleaned[field] = _text(values.get(field))
        for field in ("用户组", "主题域", "授权维度", "授权依据", "来源段"):
            if field in values:
                cleaned[field] = ", ".join(normalize_tokens(values.get(field))) if field == "授权维度" else _text(values.get(field))

        group_ref = cleaned.get("用户组") or values.get("用户组")
        group = resolve_group(group_ref)
        if group is None:
            return cleaned, f"用户组「{group_ref}」不存在，无法生成集市授权过滤记录"
        cleaned["用户组"] = _text(group.get("组编号")) or _text(group.get("id"))
        if str(group.get("组状态") or group.get("status") or "") == "已删除":
            return cleaned, f"用户组「{cleaned['用户组']}」已删除，不再生成集市授权过滤记录"
        # 清洗现有输入：授权维度只保留维度版本数据里存在且未停用的维度。
        requested_dims = normalize_tokens(cleaned.get("授权维度"))
        if requested_dims:
            from app.services.mart_access import disabled_dimensions

            disabled = disabled_dimensions()
            invalid = [dim for dim in requested_dims if dim in disabled]
            if invalid:
                cleaned["核减维度"] = invalid
                requested_dims = [dim for dim in requested_dims if dim not in disabled]
            cleaned["授权维度"] = ", ".join(requested_dims)
        if not cleaned.get("主题域"):
            return cleaned, "缺少必填字段：主题域"
        if not cleaned.get("来源段"):
            cleaned["来源段"] = f"{cleaned['用户组']}:{cleaned['主题域']}"
        return cleaned, None

    # ---------- 发布（版本输入） ----------

    def publish(
        self,
        values: dict[str, Any],
        *,
        actor: str,
        role: str,
    ) -> tuple[dict[str, Any] | None, str]:
        denial = permission_denial(actor=actor, role=role)
        if denial:
            return None, denial
        cleaned, error = self._validate(values)
        if error:
            return None, error

        key = _record_key(cleaned)
        with _LOCK:
            request_code = _text(values.get("请求编号"))
            if request_code:
                for row in store.rows(MODULE):
                    if _text(row.get("请求编号")) == request_code:
                        return row, f"请求 {request_code} 已处理，幂等返回 {row.get('记录编号')}"

            existing = self._records_for_key(key)
            live = _live(existing)
            max_order = max((_order(row) for row in live), default=0)
            max_version = max((_version(row) for row in live), default=0)
            requested_order = _seq(values.get("处理次序"))
            requested_order = max_order + 1 if requested_order is None else requested_order
            requested_version = _seq(values.get("版本号"))
            requested_version = max_version + 1 if requested_version is None else requested_version
            requested_main = _seq(values.get("主版本号"))
            requested_main = requested_version if requested_main is None else requested_main
            boundary = _seq(values.get("主版本边界"))
            boundary = requested_main if boundary is None else boundary

            stale = bool(existing) and requested_order < max_order
            behind_boundary = requested_main > boundary

            if not stale and not behind_boundary:
                # 内容完全相同的重复提交按幂等处理，并发时不会落第二个有效版本。
                for row in existing:
                    if (
                        _order(row) == requested_order
                        and _text(row.get("授权维度")) == cleaned.get("授权维度", "")
                        and _text(row.get("主题域")) == cleaned.get("主题域", "")
                    ):
                        return row, f"同一处理次序 {requested_order} 已存在，返回 {row.get('记录编号')}"

            record: dict[str, Any] = {
                "id": max((_as_int(row.get("id")) for row in store.rows(MODULE)), default=0) + 1,
                "记录编号": self._next_code(),
                "用户组": cleaned["用户组"],
                "主题域": cleaned.get("主题域", ""),
                "授权维度": cleaned.get("授权维度", ""),
                "授权依据": cleaned.get("授权依据") or f"主题域授权：{cleaned.get('主题域', '')}；用户组：{cleaned['用户组']}",
                "来源段": cleaned.get("来源段", ""),
                "版本号": requested_version,
                "主版本号": requested_main,
                "主版本边界": boundary,
                "处理次序": requested_order,
                "版本状态": "待核对",
                "核对状态": "待核对",
                "记录状态": "待核对",
                "status": "待核对",
                "操作人": actor,
                "归属人": _text(values.get("归属人")) or actor,
                "请求编号": request_code,
                "核对说明": "",
                "核对时间": "",
                "pending": True,
                "abnormal": False,
            }

            if stale:
                record.update({
                    "版本状态": "待核对",
                    "核对状态": "冲突",
                    "记录状态": "冲突",
                    "status": "冲突",
                    "pending": True,
                    "abnormal": True,
                    "核对说明": f"处理次序 {requested_order} 落后于既有 {max_order}，冲突结果等待核对",
                })
            elif behind_boundary:
                record.update({
                    "核对状态": "冲突",
                    "记录状态": "冲突",
                    "status": "冲突",
                    "pending": True,
                    "abnormal": True,
                    "核对说明": f"主版本号 {requested_main} 超出主版本边界 {boundary}，等待核对",
                })
            else:
                record.update({
                    "版本状态": _ACTIVE_VERSION,
                    "核对状态": "待核对",
                    "记录状态": "已生效",
                    "status": "已生效",
                    "pending": True,
                })
                for row in existing:
                    if _text(row.get("版本状态")) == _ACTIVE_VERSION:
                        row.update({
                            "版本状态": _REPLACED,
                            "记录状态": _REPLACED,
                            "status": _REPLACED,
                            "pending": False,
                        })

            self._append_trace(record, "发布授权过滤记录", actor, record["核对说明"])
            store.rows(MODULE).append(record)
            self._ensure_single_effective(key)
            return record, (
                f"集市授权过滤记录 {record['记录编号']} 已生成"
                + ("，冲突结果等待核对" if record["记录状态"] == "冲突" else f"，当前有效版本 v{record['版本号']}")
            )

    # ---------- 动作 ----------

    def run_action(
        self,
        record_id: int,
        action: str,
        *,
        actor: str,
        role: str,
    ) -> tuple[dict[str, Any] | None, str]:
        record = store.find(MODULE, record_id)
        if record is None:
            return None, f"集市授权过滤记录 {record_id} 不存在或已归档"
        denial = permission_denial(actor=actor, role=role, owner=_text(record.get("归属人")))
        if denial:
            return None, denial
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于集市授权过滤记录可执行范围"

        key = _key(record)
        with _LOCK:
            if action == "提交核对":
                record.update({
                    "版本状态": "待核对", "核对状态": "待核对", "记录状态": "待核对",
                    "status": "待核对", "pending": True, "abnormal": False,
                })
            elif action == "核对通过":
                latest = [
                    row for row in self._records_for_key(key)
                    if row is not record and not _is_history(row)
                ]
                blocker = None
                for row in latest:
                    if _text(row.get("核对状态")) == "冲突" or _order(row) > _order(record):
                        blocker = row
                        break
                boundary = _as_int(record.get("主版本边界"), 0)
                if boundary and _as_int(record.get("主版本号"), 1) > boundary:
                    blocker = record
                    record["核对说明"] = (
                        f"主版本号 v{record.get('主版本号')} 超出主版本边界 {boundary}，冲突结果等待核对"
                    )
                if blocker is not None:
                    record.update({
                        "版本状态": "待核对", "核对状态": "冲突", "记录状态": "冲突",
                        "status": "冲突", "pending": True, "abnormal": True,
                        "核对说明": _text(record.get("核对说明"))
                        or f"与 {blocker.get('记录编号')} 的处理次序/版本冲突，等待核对",
                    })
                else:
                    record.update({
                        "版本状态": _ACTIVE_VERSION, "核对状态": "已核对", "记录状态": "已生效",
                        "status": "已生效", "pending": False, "abnormal": False,
                        "核对说明": "核对通过", "核对时间": _now(),
                    })
                    for row in self._records_for_key(key):
                        if row is not record and _text(row.get("版本状态")) == _ACTIVE_VERSION:
                            row.update({
                                "版本状态": _REPLACED,
                                "记录状态": _REPLACED,
                                "status": _REPLACED,
                                "pending": False,
                            })
            elif action == "标记冲突":
                record.update({
                    "版本状态": "待核对", "核对状态": "冲突", "记录状态": "冲突",
                    "status": "冲突", "pending": True, "abnormal": True,
                    "核对说明": "冲突结果等待核对",
                })
            elif action == "回退版本":
                previous = [
                    row for row in self._records_for_key(key)
                    if row is not record
                    and _version(row) < _version(record)
                    and _text(row.get("记录状态")) != "已归档"
                ]
                record.update({
                    "版本状态": _ROLLED_BACK, "核对状态": "待核对", "记录状态": "已回退",
                    "status": "已回退", "pending": True, "abnormal": True,
                    "核对说明": "版本已回退，同一来源段保留追溯",
                })
                target = max(previous, key=lambda row: (_version(row), _order(row), _as_int(row.get("id"))), default=None)
                if target is not None:
                    target.update({
                        "版本状态": _ACTIVE_VERSION, "核对状态": "已核对", "记录状态": "已生效",
                        "status": "已生效", "pending": False, "abnormal": False,
                        "核对说明": f"由 {record.get('记录编号')} 回退恢复",
                    })
                    record["回退目标"] = target.get("记录编号")
                else:
                    record["回退目标"] = ""
            elif action == "归档记录":
                record.update({
                    "版本状态": "已归档", "核对状态": "待核对", "记录状态": "已归档",
                    "status": "已归档", "pending": False, "abnormal": False,
                })
            self._append_trace(record, action, actor, _text(record.get("核对说明")))
            self._ensure_single_effective(key)
        return record, f"集市授权过滤记录已{action}"

    # ---------- 核对 ----------

    def reconcile(
        self,
        payload: dict[str, Any],
        *,
        actor: str,
        role: str,
    ) -> tuple[dict[str, Any] | None, str]:
        denial = permission_denial(actor=actor, role=role)
        if denial:
            return None, denial

        codes: list[str] = []
        raw_codes = payload.get("记录编号")
        if isinstance(raw_codes, (list, tuple)):
            codes = [_text(item) for item in raw_codes if _text(item)]
        elif raw_codes:
            codes = normalize_tokens(raw_codes)
        group_code = _text(payload.get("用户组"))

        with _LOCK:
            rows = list(store.rows(MODULE))
            if codes:
                rows = [row for row in rows if _text(row.get("记录编号")) in codes]
            if group_code:
                rows = [row for row in rows if _text(row.get("用户组")) == group_code]
            if not codes and not group_code:
                rows = [row for row in rows if _text(row.get("记录状态")) != "已归档"]

            boundary = _as_int(payload.get("主版本边界"), 0)
            if boundary <= 0:
                boundary = max((_as_int(row.get("主版本号"), 1) for row in rows), default=1)
            boundary = max(boundary, 1)

            effective: list[str] = []
            conflicts: list[dict[str, Any]] = []
            history: list[str] = []
            for row in rows:
                row["主版本边界"] = boundary
                if _is_history(row):
                    # 历史版本不参与主版本核对，回退后仍保留在同一来源段。
                    history.append(_text(row.get("记录编号")))
                    self._append_trace(row, "核对主版本边界", actor, "历史版本保留，不参与主版本核对")
                    continue
                key = _key(row)
                live = _live(self._records_for_key(key))
                max_order = max((_order(item) for item in live), default=0)
                max_version = max((_version(item) for item in live), default=0)
                if (
                    _as_int(row.get("主版本号"), 1) > boundary
                    or _version(row) > max_version
                    or _order(row) < max_order
                    or _text(row.get("核对状态")) == "冲突"
                ):
                    row.update({
                        "版本状态": "待核对", "核对状态": "冲突", "记录状态": "冲突",
                        "status": "冲突", "pending": True, "abnormal": True,
                        "核对说明": (
                            f"主版本边界 {boundary} 内无法确认版本 "
                            f"v{row.get('版本号')}（主版本 v{row.get('主版本号')}），冲突结果等待核对"
                        ),
                        "核对时间": _now(),
                        "主版本边界": boundary,
                    })
                    conflicts.append(row)
                else:
                    row.update({
                        "版本状态": _ACTIVE_VERSION, "核对状态": "已核对", "记录状态": "已生效",
                        "status": "已生效", "pending": False, "abnormal": False,
                        "核对说明": f"主版本边界 {boundary} 内核对通过",
                        "核对时间": _now(),
                        "主版本边界": boundary,
                    })
                    effective.append(_text(row.get("记录编号")))
                self._append_trace(row, "核对主版本边界", actor, _text(row.get("核对说明")))

            keys = {_key(row) for row in rows}
            for key in keys:
                self._ensure_single_effective(key)

            result = {
                "主版本边界": boundary,
                "消费记录数": len(rows),
                "有效版本": effective,
                "历史版本": history,
                "冲突待核对": [
                    {
                        "记录编号": row.get("记录编号"),
                        "用户组": row.get("用户组"),
                        "主题域": row.get("主题域"),
                        "版本号": row.get("版本号"),
                        "主版本号": row.get("主版本号"),
                        "核对说明": row.get("核对说明"),
                    }
                    for row in conflicts
                ],
                "摘要": self.summary(),
            }
        message = (
            f"已消费 {len(rows)} 条集市授权过滤记录，主版本边界 {boundary}，"
            f"有效 {len(effective)} 条，冲突 {len(conflicts)} 条等待核对"
        )
        return result, message

    # ---------- 追溯 ----------

    def trace(self, record_id: int) -> dict[str, Any] | None:
        record = store.find(MODULE, record_id)
        if record is None:
            return None
        source = _text(record.get("来源段"))
        rows = [
            row for row in store.rows(MODULE)
            if (_text(row.get("来源段")) == source) or (
                _text(row.get("用户组")) == _text(record.get("用户组"))
                and _text(row.get("主题域")) == _text(record.get("主题域"))
            )
        ]
        chain = sorted(rows, key=lambda row: (_version(row), _order(row), _as_int(row.get("id"))))
        current = next((row for row in reversed(chain) if _is_effective(row)), None)
        profile = group_profile(record.get("用户组"))

        mart_rows = [
            row for row in store.rows("data_mart")
            if _text(row.get("主题域")) == _text(record.get("主题域"))
        ]
        data_flow = []
        for row in mart_rows:
            data_flow.append({
                "表编号": row.get("表编号"),
                "表名称": row.get("表名称"),
                "主题域": row.get("主题域"),
                "关联维度": row.get("关联维度"),
                "度量字段": row.get("度量字段"),
                "表状态": row.get("status"),
            })

        return {
            "记录编号": record.get("记录编号"),
            "来源段": source,
            "用户组": record.get("用户组"),
            "组名称": profile.get("name", ""),
            "授权主题域": profile.get("domains", []),
            "授权维度": profile.get("dimensions", []),
            "当前有效版本": current.get("记录编号") if current else "",
            "版本链": [
                {
                    "记录编号": row.get("记录编号"),
                    "版本号": row.get("版本号"),
                    "主版本号": row.get("主版本号"),
                    "主版本边界": row.get("主版本边界"),
                    "处理次序": row.get("处理次序"),
                    "版本状态": row.get("版本状态"),
                    "核对状态": row.get("核对状态"),
                    "记录状态": row.get("记录状态"),
                    "操作人": row.get("操作人"),
                    "核对说明": row.get("核对说明"),
                    "回退目标": row.get("回退目标", ""),
                }
                for row in chain
            ],
            "变更轨迹": record.get("变更轨迹", []),
            "结果数据流": data_flow,
            "授权口径": {
                "主题域": profile.get("domains", []),
                "维度": profile.get("dimensions", []),
                "维度授权已声明": profile.get("dimensions_declared", False),
                "可选口径": [DOMAIN_MODE, DIMENSION_MODE],
            },
        }


service = MartAuthorizationService()
