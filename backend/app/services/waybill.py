"""运单管理业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.store import store

MODULE = "waybill"
REQUIRED_FIELDS = ["运单号", "关联订单", "承运车辆"]
STATUS_ORDER = ["待装车", "运输中", "已签收", "已作废"]
ACTION_RULES = {"确认装车": "运输中", "签收运单": "已签收", "作废运单": "已作废"}
ACTION_SOURCES = {"确认装车": ["待装车"], "签收运单": ["运输中"], "作废运单": ["待装车", "运输中"]}
TERMINAL_STATUSES = ["已签收", "已作废"]
NEGATIVE_ACTIONS = ["作废运单"]
TEMPERATURE_MODULE = "temperature"
TEMPERATURE_OFFLINE_STATUS = "已离线"


class WaybillService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("运单号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["运单状态"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"冷链运单 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于运单管理可执行范围"
        current = str(entry.get("status") or "")
        if current in TERMINAL_STATUSES:
            return None, f"冷链运单{current}，不允许再次变更"
        allowed = ACTION_SOURCES[action]
        if current not in allowed:
            return None, f"只有{'、'.join(allowed)}的运单能{action}，当前状态为「{current}」"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["运单状态"] = target
        entry["pending"] = target not in TERMINAL_STATUSES
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        message = f"冷链运单已{action}"
        if action == "确认装车":
            entry["装车时间"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if action == "签收运单":
            synced = self._sync_temperature_records(entry)
            if synced:
                message = f"{message}，{synced} 条温控记录已同步离线"
        return entry, message

    def _sync_temperature_records(self, entry: dict[str, Any]) -> int:
        """签收后同一张运单的温控记录同步离线，温控监控里能看到运输已结束。"""
        waybill_no = str(entry.get("运单号") or "").strip()
        if not waybill_no:
            return 0
        synced = 0
        for row in store.rows(TEMPERATURE_MODULE):
            if str(row.get("关联运单") or "").strip() != waybill_no:
                continue
            row["status"] = TEMPERATURE_OFFLINE_STATUS
            row["pending"] = False
            synced += 1
        return synced
