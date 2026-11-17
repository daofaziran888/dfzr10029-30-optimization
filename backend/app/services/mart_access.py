"""数据集市授权口径：解析用户组权限，按主题域与关联维度过滤集市数据。

这里把「主题域授权」和「关联维度过滤」放在同一处计算，避免只过滤表、不
过滤维度导致的明细泄露。集市授权过滤记录（mart_authorization）里处于有效
状态的版本也会参与权限解析，因此核对、回退后的记录可以直接影响读取结果。
"""
from __future__ import annotations

import re
from typing import Any, Iterable

from app.store import store

MART_MODULE = "data_mart"
GROUP_MODULE = "user_group"
DIMENSION_MODULE = "dimension"
AUTH_MODULE = "mart_authorization"

DOMAIN_MODE = "主题域"
DIMENSION_MODE = "关联维度"
DEFAULT_MODE = DOMAIN_MODE

ALL_TOKENS = {"全部", "所有", "*", "all", "ALL", "全量"}
ALL_MEASURE_TOKENS = {"公共", "公共度量", "公共指标"}
READONLY_ROLES = {
    "只读", "只读用户", "readonly", "read-only", "read_only", "viewer", "view", "guest",
}
ADMIN_ROLES = {"管理员", "admin", "owner", "超级管理员"}
DEFAULT_OPERATOR = "值班管理员"
DEFAULT_ROLE = "管理员"

_SPLIT_RE = re.compile(r"[,，、;；|/\s]+")
_EMPTY_TOKENS = {"-", "—", "无", "none", "null", "n/a", "na", "undefined"}
_PREFIXES = ("主题域:", "主题域：", "维度:", "维度：", "用户组:", "用户组：", "域:", "域：")


def normalize_tokens(value: Any) -> list[str]:
    """把字符串、列表统一拆成去空白的授权项，保留原始次序。"""
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        source: Iterable[Any] = value
        raw = [str(item) for item in source]
    else:
        raw = [str(value)]
    tokens: list[str] = []
    for item in raw:
        for token in _SPLIT_RE.split(item):
            token = token.strip()
            for prefix in _PREFIXES:
                if token.startswith(prefix):
                    token = token[len(prefix):].strip()
                    break
            if token and token.casefold() not in _EMPTY_TOKENS and token not in tokens:
                tokens.append(token)
    return tokens


def _row_token(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row and row.get(key) not in (None, ""):
            return row.get(key)
    return None


def known_domains() -> list[str]:
    domains: list[str] = []
    for row in store.rows(MART_MODULE):
        domain = str(row.get("主题域") or "").strip()
        if domain and domain not in domains:
            domains.append(domain)
    return domains


def disabled_dimensions() -> set[str]:
    """维度版本数据里已停用的维度不再参与授权，属于清洗输入的一部分。"""
    disabled: set[str] = set()
    for row in store.rows(DIMENSION_MODULE):
        code = str(row.get("维度编号") or "").strip()
        state = str(row.get("维度状态") or row.get("status") or "").strip()
        if code and state == "已停用":
            disabled.add(code)
    return disabled


def resolve_group(group_ref: Any) -> dict[str, Any] | None:
    """支持用组编号、组名称或数字 id 指定用户组。"""
    if group_ref in (None, ""):
        return None
    text = str(group_ref).strip()
    groups = store.rows(GROUP_MODULE)
    for row in groups:
        if text == str(row.get("组编号", "")).strip() or text == str(row.get("组名称", "")).strip():
            return row
    for row in groups:
        if text.isdigit() and int(row.get("id", 0)) == int(text):
            return row
    return None


def _active_auth_records(group_code: str) -> list[dict[str, Any]]:
    records = [
        row for row in store.rows(AUTH_MODULE)
        if str(row.get("用户组", "")).strip() == group_code
        and str(row.get("版本状态") or row.get("status") or "").strip() == "有效"
        and str(row.get("核对状态") or "") != "冲突"
    ]
    return sorted(records, key=lambda row: (int(row.get("版本号") or 0), int(row.get("id") or 0)))


def group_profile(group_ref: Any) -> dict[str, Any]:
    """解析用户组的主题域授权与关联维度授权。

    - 主题域来源：用户组「数据可见性」+ 有效集市授权过滤记录的主题域。
    - 维度来源：用户组「授权维度/可读维度」+ 有效记录里的「授权维度」。
    - 未声明维度授权时视为该组在授权主题域内可读全部维度。
    """
    row = resolve_group(group_ref)
    if row is None:
        return {
            "found": False,
            "code": str(group_ref or ""),
            "name": "",
            "domains": [],
            "dimensions": [],
            "dimensions_declared": False,
            "all_dimensions": False,
            "all_domains": False,
            "status": "",
        }

    code = str(row.get("组编号") or row.get("id") or "").strip()
    status = str(row.get("组状态") or row.get("status") or "")
    domains = normalize_tokens(row.get("数据可见性"))
    dims = normalize_tokens(_row_token(row, "授权维度", "可读维度", "数据可见维度", "维度权限"))
    all_domains = any(token in ALL_TOKENS for token in domains)
    dims_all = any(token in ALL_TOKENS for token in dims)
    declared_dims = list(dims)

    records = _active_auth_records(code)
    for record in records:
        for domain in normalize_tokens(record.get("主题域")):
            if domain in ALL_TOKENS:
                all_domains = True
            elif domain not in domains:
                domains.append(domain)
        for dim in normalize_tokens(record.get("授权维度")):
            if dim in ALL_TOKENS:
                dims_all = True
            elif dim not in dims:
                dims.append(dim)

    known = known_domains()
    cleaned_domains: list[str] = []
    for domain in domains:
        if domain in known or domain.endswith("域"):
            if domain not in cleaned_domains:
                cleaned_domains.append(domain)
    if all_domains:
        cleaned_domains = list(known) + [domain for domain in cleaned_domains if domain not in known]
    domains = cleaned_domains

    # 已删除的组不保留任何数据权限；已停用组仅保留只读授权口径。
    if status == "已删除":
        domains = []
        dims = []
        dims_all = False
        dims_declared = False

    disabled = disabled_dimensions()
    if not dims_all:
        dims = [dim for dim in dims if dim not in disabled]
    # 声明过维度授权但全部被清洗掉时，不能退化成「全部维度」，否则会放行未授权维度。
    dims_declared = bool(dims) or dims_all or bool(declared_dims)

    return {
        "found": True,
        "id": int(row.get("id") or 0),
        "code": code,
        "name": str(row.get("组名称") or code),
        "status": status,
        "domains": domains,
        "dimensions": [] if dims_all else dims,
        "dimensions_declared": dims_declared,
        "all_dimensions": dims_all,
        "all_domains": all_domains,
    }


def _basis_for(profile: dict[str, Any], domain: str, removed: list[str]) -> tuple[str, dict[str, Any] | None]:
    record = None
    for item in reversed(_active_auth_records(profile["code"])):
        if domain in normalize_tokens(item.get("主题域")) or profile["all_domains"]:
            record = item
            break
    if record is not None:
        basis = str(record.get("授权依据") or f"主题域授权：{domain}")
        basis = f"{basis}（版本 v{record.get('版本号') or 1}，来源段 {record.get('来源段') or '—'}）"
    else:
        basis = f"主题域授权：{domain}；用户组：{profile['code']}"
    if removed:
        basis = f"{basis}；已过滤维度：{'、'.join(removed)}"
    return basis, record


def _allowed_dimensions(profile: dict[str, Any], table_dims: list[str]) -> list[str]:
    disabled = disabled_dimensions()
    if profile.get("all_dimensions"):
        return [dim for dim in table_dims if dim not in disabled]
    if not profile.get("dimensions_declared"):
        return [dim for dim in table_dims if dim not in disabled]
    allowed = set(profile.get("dimensions") or [])
    return [dim for dim in table_dims if dim in allowed and dim not in disabled]


def filter_table_row(
    row: dict[str, Any],
    profile: dict[str, Any],
    mode: str = DEFAULT_MODE,
) -> tuple[bool, dict[str, Any]]:
    """返回 (是否可读, 过滤后的集市表行)。主题域与关联维度同时生效。"""
    domain = str(row.get("主题域") or "").strip()
    table_dims = normalize_tokens(row.get("关联维度"))
    allowed_dims = _allowed_dimensions(profile, table_dims)
    removed = [dim for dim in table_dims if dim not in allowed_dims]
    domains = set(profile.get("domains") or [])
    domain_ok = domain in domains or bool(profile.get("all_domains"))

    if mode == DIMENSION_MODE and profile.get("dimensions_declared"):
        dimension_ok = bool(set(table_dims) & set(allowed_dims))
    else:
        dimension_ok = True

    if mode == DIMENSION_MODE:
        # 关联维度归属授权：授权主题域内的表直接可读；跨主题的表只有在命中
        # 已授权关联维度时才可打开，但必须屏蔽该主题域的度量，避免跨主题
        # 读取未授权度量。
        visible = domain_ok or (profile.get("dimensions_declared") and dimension_ok)
    else:
        visible = domain_ok

    filtered = dict(row)
    filtered["可读维度"] = ", ".join(allowed_dims)
    filtered["被过滤维度"] = ", ".join(removed)
    filtered["被过滤维度明细"] = removed
    filtered["关联维度"] = ", ".join(allowed_dims)
    filtered["授权口径"] = mode
    filtered["授权用户组"] = profile.get("code", "")
    measures = normalize_tokens(row.get("度量字段"))
    if domain_ok:
        filtered["可读度量"] = ", ".join(measures)
        filtered["被屏蔽度量"] = []
    else:
        fixed = [item for item in measures if item in ALL_MEASURE_TOKENS or item.startswith("公共")]
        filtered["可读度量"] = ", ".join(fixed)
        filtered["被屏蔽度量"] = [item for item in measures if item not in fixed]
        filtered["度量字段"] = ", ".join(fixed)
        filtered["跨主题屏蔽"] = True
    basis, record = _basis_for(profile, domain, removed)
    if filtered.get("被屏蔽度量"):
        basis = f"{basis}；跨主题度量已屏蔽：{'、'.join(filtered['被屏蔽度量'])}"
    filtered["授权依据"] = basis
    if record is not None:
        filtered["授权记录编号"] = record.get("记录编号")
        filtered["授权记录版本"] = record.get("版本号")
        filtered["授权来源段"] = record.get("来源段")
    if not visible:
        filtered["度量字段"] = ""
        filtered["可读度量"] = ""
    return visible, filtered


def filter_rows(
    group_ref: Any,
    mode: str = DEFAULT_MODE,
    domain: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """按用户组过滤集市表，返回可读行与本次授权摘要。"""
    profile = group_profile(group_ref)
    mode = DIMENSION_MODE if mode in {DIMENSION_MODE, "dimension", "维度", "关联维度归属"} else DOMAIN_MODE
    rows = store.rows(MART_MODULE)
    if domain:
        rows = [row for row in rows if str(row.get("主题域") or "") == domain]
    # 清洗现有输入：没有主题域归属的集市表无法做授权判定，按未授权处理。
    rows = [row for row in rows if str(row.get("主题域") or "").strip()]
    items: list[dict[str, Any]] = []
    denied: list[dict[str, Any]] = []
    for row in rows:
        visible, filtered = filter_table_row(row, profile, mode)
        if visible:
            items.append(filtered)
        else:
            denied.append({
                "表编号": row.get("表编号"),
                "表名称": row.get("表名称"),
                "主题域": row.get("主题域"),
                "授权依据": filtered.get("授权依据"),
                "被过滤维度": filtered.get("被过滤维度"),
            })
    summary = {
        "用户组": profile.get("code", ""),
        "组名称": profile.get("name", ""),
        "授权口径": mode,
        "授权主题域": profile.get("domains", []),
        "授权维度": profile.get("dimensions", []),
        "维度授权已声明": profile.get("dimensions_declared", False),
        "可读表数": len(items),
        "未授权表数": len(denied),
        "未授权表": denied,
    }
    return items, summary


def table_visible(row: dict[str, Any], group_ref: Any, mode: str = DEFAULT_MODE) -> tuple[bool, dict[str, Any]]:
    profile = group_profile(group_ref)
    return filter_table_row(row, profile, mode)


def _header_text(value: Any) -> str:
    """HTTP 头按 latin-1 解码，中文操作人需要按 UTF-8 还原一次。"""
    text = str(value).strip()
    try:
        return text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


def identity(payload: Any = None, request: Any = None) -> tuple[str, str]:
    """从请求头、查询参数或动作载荷里取操作人和角色。"""
    values: dict[str, Any] = {}
    if isinstance(payload, dict):
        values = payload
    elif payload is not None and hasattr(payload, "model_dump"):
        values = payload.model_dump()
    elif payload is not None and hasattr(payload, "__dict__"):
        values = dict(payload.__dict__)
    # 动作载荷里的操作人可能写在 values 里，拍平一层再取，兼容既有入参。
    nested = values.get("values")
    if isinstance(nested, dict):
        values = {**nested, **{k: v for k, v in values.items() if k != "values"}}

    def pick(*keys: str) -> Any:
        for key in keys:
            if key in values and values.get(key) not in (None, ""):
                return values.get(key)
        return None

    actor = None
    role = None
    if request is not None:
        headers = getattr(request, "headers", {})
        actor = headers.get("x-operator") or headers.get("x-user") or headers.get("x-actor")
        role = headers.get("x-operator-role") or headers.get("x-role")
        query = getattr(request, "query_params", {})
        actor = actor or query.get("operator") or query.get("操作人")
        role = role or query.get("role") or query.get("角色")
    actor = actor or pick("operator", "操作人", "归属人", "actor") or DEFAULT_OPERATOR
    role = role or pick("role", "角色") or DEFAULT_ROLE
    return _header_text(actor) or DEFAULT_OPERATOR, _header_text(role) or DEFAULT_ROLE


def is_readonly(role: str | None) -> bool:
    return str(role or "").strip().casefold() in {item.casefold() for item in READONLY_ROLES}


def is_admin(role: str | None) -> bool:
    return str(role or "").strip().casefold() in {item.casefold() for item in ADMIN_ROLES}


def permission_denial(
    *,
    actor: str,
    role: str,
    owner: str | None = None,
) -> str | None:
    """只读用户只允许查看；非管理员也不能改写他人归属的数据。"""
    if is_readonly(role):
        return "只读用户只能查看集市授权过滤记录，不能改动其他归属的数据"
    if owner and not is_admin(role) and str(owner).strip() not in ("", actor):
        return f"当前用户 {actor} 无权改动归属 {owner} 的集市数据"
    return None
