"""数据集市 DAG 图服务：生成节点、边示例结构与流转规则。

读取侧同时应用主题域授权与关联维度过滤：只要带上用户组，就按授权口径裁剪
节点与关联维度，避免「集市表可见但维度明细泄露」。不带用户组时保持既有
管理口径，便于维护全部集市表。
"""
from __future__ import annotations

from typing import Any

from app.services.mart_access import (
    DEFAULT_MODE,
    DIMENSION_MODE,
    filter_table_row,
    group_profile,
    normalize_tokens,
    permission_denial,
)
from app.store import store

MODULE = "data_mart"
REQUIRED_FIELDS = ["表编号", "表名称", "主题域"]
STATUS_ORDER = ["草稿", "已建模", "已发布", "已下线"]
ACTION_RULES = {"提交建模": "已建模", "发布集市": "已发布", "下线集市": "已下线"}
NEGATIVE_ACTIONS = ["下线集市"]


def csv_cell(value: Any) -> str:
    text = str(value) if value is not None else ""
    if text and text[0] in "=+-@":
        text = "'" + text
    return '"' + text.replace('"', '""') + '"'


def _filter_mode(mode: str | None) -> str:
    if mode in (DIMENSION_MODE, "dimension", "维度", "关联维度归属"):
        return DIMENSION_MODE
    return DEFAULT_MODE


class DataMartService:
    def _node(self, row: dict[str, Any], index: int) -> dict[str, Any]:
        return {
            "id": int(row.get("id", index + 1)),
            "name": str(row.get(list(row.keys())[1] if len(row) > 1 else "name", "")),
            "status": str(row.get("status", STATUS_ORDER[0])),
            **{k: row[k] for k in row if k not in ("id", "status", "pending", "abnormal")},
        }

    def get_graph(
        self,
        *,
        group: str | None = None,
        mode: str | None = None,
    ) -> dict[str, Any]:
        rows = store.rows(MODULE)
        authorization: dict[str, Any] | None = None
        if group:
            profile = group_profile(group)
            selected_mode = _filter_mode(mode)
            visible_rows: list[dict[str, Any]] = []
            for row in rows:
                # 清洗现有输入：没有主题域归属的集市表不参与授权读取。
                if not str(row.get("主题域") or "").strip():
                    continue
                visible, filtered = filter_table_row(row, profile, selected_mode)
                if not visible:
                    continue
                # 节点按既有字段次序输出，只把关联维度收敛为可读维度。
                merged = dict(row)
                merged["关联维度"] = filtered["关联维度"]
                merged["可读维度"] = filtered["可读维度"]
                merged["被过滤维度"] = filtered["被过滤维度"]
                merged["授权依据"] = filtered["授权依据"]
                merged["授权口径"] = filtered["授权口径"]
                merged["授权用户组"] = filtered["授权用户组"]
                visible_rows.append(merged)
            authorization = {
                "用户组": profile.get("code", ""),
                "组名称": profile.get("name", ""),
                "授权口径": selected_mode,
                "授权主题域": profile.get("domains", []),
                "授权维度": profile.get("dimensions", []),
                "维度授权已声明": profile.get("dimensions_declared", False),
                "可见表数": len(visible_rows),
                "总表数": len(rows),
            }
            rows = visible_rows

        nodes: list[dict] = []
        edges: list[dict] = []
        for i, row in enumerate(rows):
            nodes.append(self._node(row, i))
        for i in range(len(nodes) - 1):
            edges.append({"from": nodes[i]["id"], "to": nodes[i + 1]["id"], "label": "依赖"})
        graph: dict[str, Any] = {"nodes": nodes, "edges": edges}
        if authorization is not None:
            graph["authorization"] = authorization
        return graph

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def get_entry_for_group(
        self,
        entry_id: int,
        group: str | None,
        mode: str | None = None,
    ) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        if entry is None or not group:
            return entry
        visible, filtered = filter_table_row(entry, group_profile(group), _filter_mode(mode))
        if not visible:
            return None
        return filtered

    def visible_domains(self, group: str) -> list[str]:
        profile = group_profile(group)
        domains: list[str] = []
        for row in store.rows(MODULE):
            domain = str(row.get("主题域") or "")
            if domain in (profile.get("domains") or []) or profile.get("all_domains"):
                if domain and domain not in domains:
                    domains.append(domain)
        return domains

    def create_entry(
        self,
        values: dict[str, Any],
        *,
        actor: str = "",
        role: str = "",
    ) -> tuple[dict[str, Any] | None, list[str] | str]:
        denial = permission_denial(actor=actor, role=role)
        if denial:
            return None, denial
        missing = [f for f in REQUIRED_FIELDS if not str(values.get(f) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(r.get("id", 0)) for r in rows), default=0) + 1}
        entry.update({f: values.get(f) for f in REQUIRED_FIELDS})
        entry.update({
            "关联维度": ", ".join(normalize_tokens(values.get("关联维度"))),
            "度量字段": str(values.get("度量字段") or ""),
            "事实粒度": str(values.get("事实粒度") or ""),
            "刷新周期": str(values.get("刷新周期") or ""),
        })
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        entry["归属人"] = actor
        rows.append(entry)
        return entry, []

    def run_action(
        self,
        entry_id: int,
        action: str,
        *,
        actor: str = "",
        role: str = "",
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"集市表 {entry_id} 不存在或已归档"
        denial = permission_denial(
            actor=actor, role=role, owner=str(entry.get("归属人") or ""))
        if denial:
            return None, denial
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于数据集市可执行范围"
        target = ACTION_RULES[action]
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"集市表已{action}"

    def raw_data(
        self,
        *,
        group: str | None = None,
        mode: str | None = None,
    ) -> tuple[list[dict], list[dict]]:
        g = self.get_graph(group=group, mode=mode)
        return g["nodes"], g["edges"]
