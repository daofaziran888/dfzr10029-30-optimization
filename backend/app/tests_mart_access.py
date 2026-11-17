"""集市授权过滤记录与关联维度过滤的回归检查。

不依赖 pytest：直接以脚本运行即可（backend 目录下执行）：
    .venv/bin/python -m app.tests_mart_access
"""
from __future__ import annotations

import threading
from typing import Any

from app.seed import SEED_ROWS
from app.services import mart_authorization as auth_module
from app.services.mart_access import filter_rows, group_profile
from app.store import store


def reset() -> None:
    store._tables = {name: [dict(row) for row in rows] for name, rows in SEED_ROWS.items()}


def table_ids(items: list[dict[str, Any]]) -> list[str]:
    return [str(item.get("表编号")) for item in items]


def check_domain_mode() -> None:
    items, summary = filter_rows("USER-0001", "主题域")
    assert table_ids(items) == ["DATA-0001"], table_ids(items)
    row = items[0]
    assert row["关联维度"] == "DIME-0001"
    assert row["被过滤维度"] == "DIME-0002"
    assert "DIME-0002" in row["授权依据"]
    assert summary["未授权表数"] == 2


def check_dimension_mode_blocks_cross_domain_measures() -> None:
    items, _ = filter_rows("USER-0001", "关联维度")
    by_id = {item["表编号"]: item for item in items}
    assert set(by_id) == {"DATA-0001", "DATA-0003"}, by_id.keys()
    crossed = by_id["DATA-0003"]
    assert crossed["度量字段"] == ""
    assert crossed["被屏蔽度量"] == ["活跃会员数", "复购率"]
    assert crossed["关联维度"] == "DIME-0001"


def check_deleted_group_has_no_access() -> None:
    items, summary = filter_rows("USER-0003")
    assert items == []
    assert summary["未授权表数"] == 3


def check_single_effective_version_under_concurrency() -> None:
    service = auth_module.MartAuthorizationService()

    def publish(order: int) -> None:
        service.publish(
            {"用户组": "USER-0001", "主题域": "销售域", "处理次序": order},
            actor="值班管理员", role="管理员",
        )

    threads = [threading.Thread(target=publish, args=(order,)) for order in range(2, 8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    effective = [
        row for row in store.rows("mart_authorization")
        if row["来源段"] == "USER-0001:销售域" and row["版本状态"] == "有效"
    ]
    assert len(effective) == 1, effective
    assert effective[0]["处理次序"] == 7


def check_stale_order_conflicts_and_needs_reconcile() -> None:
    service = auth_module.MartAuthorizationService()
    record, _ = service.publish(
        {"用户组": "USER-0002", "主题域": "会员域", "处理次序": 0},
        actor="值班管理员", role="管理员",
    )
    assert record["核对状态"] == "冲突", record
    result, _ = service.reconcile(
        {"用户组": "USER-0002", "主版本边界": 1}, actor="值班管理员", role="管理员")
    assert record["记录编号"] in [item["记录编号"] for item in result["冲突待核对"]]


def check_rollback_keeps_same_source_trace() -> None:
    service = auth_module.MartAuthorizationService()
    record = service.find_by_code("AUTH-0002")
    service.run_action(record["id"], "回退版本", actor="值班管理员", role="管理员")
    trace = service.trace(record["id"])
    assert trace["当前有效版本"] == "AUTH-0001", trace["当前有效版本"]
    states = {item["记录编号"]: item["版本状态"] for item in trace["版本链"]}
    assert states == {"AUTH-0001": "有效", "AUTH-0002": "已回退"}, states


def check_readonly_cannot_write_but_can_list() -> None:
    service = auth_module.MartAuthorizationService()
    entry, message = service.publish(
        {"用户组": "USER-0001", "主题域": "销售域"}, actor="只读用户", role="只读")
    assert entry is None and "只读" in message, message
    records, total = service.list_records()
    assert total == 3 and len(records) == 3


def check_other_owner_blocked_for_editor() -> None:
    service = auth_module.MartAuthorizationService()
    entry, message = service.run_action(2, "提交核对", actor="张三", role="编辑")
    assert entry is None and "无权改动" in message, message


def check_disabled_dimension_is_cleaned() -> None:
    store.rows("dimension")[1]["维度状态"] = "已停用"
    store.rows("dimension")[1]["status"] = "已停用"
    profile = group_profile("USER-0002")
    assert "DIME-0002" not in profile["dimensions"], profile
    items, _ = filter_rows("USER-0002")
    assert all("DIME-0002" not in item["关联维度"] for item in items), items


def main() -> None:
    checks = [
        check_domain_mode,
        check_dimension_mode_blocks_cross_domain_measures,
        check_deleted_group_has_no_access,
        check_single_effective_version_under_concurrency,
        check_stale_order_conflicts_and_needs_reconcile,
        check_rollback_keeps_same_source_trace,
        check_readonly_cannot_write_but_can_list,
        check_other_owner_blocked_for_editor,
        check_disabled_dimension_is_cleaned,
    ]
    for check in checks:
        reset()
        check()
        print(f"ok  {check.__name__}")
    print(f"{len(checks)} 项检查全部通过")


if __name__ == "__main__":
    main()
