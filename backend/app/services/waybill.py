"""运单管理业务规则：状态流转、字段校验与筛选口径都收在这里。

运单状态只允许按既定流向推进，终态不可再变：

    待装车 ──确认装车──▶ 运输中 ──签收运单──▶ 已签收（终态）
       │                    │
       └──────作废运单──────┴──────────────▶ 已作废（终态）
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.store import store

MODULE = "waybill"
REQUIRED_FIELDS = ["运单号", "关联订单", "承运车辆"]
STATUS_PENDING = "待装车"
STATUS_IN_TRANSIT = "运输中"
STATUS_SIGNED = "已签收"
STATUS_VOID = "已作废"
TERMINAL_STATUSES = [STATUS_SIGNED, STATUS_VOID]

# 动作 -> 唯一允许的源状态；不在表里的状态执行该动作一律拦下
ACTION_REQUIRED_STATUS = {
    "确认装车": STATUS_PENDING,
    "签收运单": STATUS_IN_TRANSIT,
    "作废运单": None,  # 待装车、运输中均可作废，终态除外，见 run_action
}
NEGATIVE_ACTIONS = ["作废运单"]


def _now() -> str:
    """动作发生时间：格式与示例数据保持一致，精确到秒。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


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
        entry["status"] = STATUS_PENDING
        entry["运单状态"] = STATUS_PENDING
        entry["装车时间"] = None
        entry["卸货时间"] = None
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"冷链运单 {entry_id} 不存在或已归档"
        if action not in ACTION_REQUIRED_STATUS:
            return None, f"动作「{action}」不属于运单管理可执行范围"

        current = str(entry.get("status") or "")
        if current in TERMINAL_STATUSES:
            return None, (
                f"运单当前为「{current}」，已结束流转，不能再执行「{action}」；"
                "已签收或已作废的运单不允许再次变更"
            )

        if action == "作废运单":
            target = STATUS_VOID
        else:
            required = ACTION_REQUIRED_STATUS[action]
            if current != required:
                reason = self._block_reason(action, current, required)
                return None, reason
            target = STATUS_SIGNED if action == "签收运单" else STATUS_IN_TRANSIT

        # 确认装车时补上装车时间；已有值不覆盖，避免重复推进时间戳
        if action == "确认装车" and not entry.get("装车时间"):
            entry["装车时间"] = _now()

        entry["status"] = target
        entry["运单状态"] = target
        entry["pending"] = target not in TERMINAL_STATUSES
        entry["abnormal"] = action in NEGATIVE_ACTIONS

        if action == "签收运单":
            self._sync_temperature(entry)

        return entry, f"冷链运单已{action}，当前状态「{target}」"

    @staticmethod
    def _block_reason(action: str, current: str, required: str) -> str:
        if action == "确认装车":
            return (
                f"只有「待装车」的运单能确认装车，当前运单为「{current}」，"
                f"不能重复装车或从「{current}」直接装车"
            )
        if action == "签收运单":
            return (
                f"只有「运输中」的运单能签收运单，当前运单为「{current}」，"
                f"请先完成确认装车（需要状态：{required}）"
            )
        return f"当前运单为「{current}」，不能执行「{action}」"

    @staticmethod
    def _sync_temperature(entry: dict[str, Any]) -> None:
        """签收后把同一张运单的温控记录同步为已签收，温控监控里能直接体现。"""
        waybill_no = str(entry.get("运单号") or "")
        if not waybill_no:
            return
        for record in store.rows("temperature"):
            if str(record.get("关联运单") or "") == waybill_no:
                record["运单状态"] = STATUS_SIGNED
