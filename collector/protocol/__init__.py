"""Protocol layer: BLE helpers, parsers, DB upserts, sync state.

Split from sync_ring.py in Phase 3. The orchestrator (sync_ring.py) only
imports from this package — protocol internals are an implementation detail.

SACRED: time_sync.set_time_local / queues[1] ack flow must never be
replaced with a 'cleaner' version against colmi_r02_client upstream.
"""
from .db import (
    SyncResult,
    get_db,
    log_ring_status,
    log_sync_complete,
    log_sync_start,
    update_progress,
    upsert_goals,
    upsert_heart_rate,
    upsert_hrv,
    upsert_sleep,
    upsert_spo2,
    upsert_steps,
    upsert_stress,
    upsert_temperature_list,
)
from .scanner import scan_ring
from .time_sync import sync_time_to_ring

__all__ = [
    "SyncResult",
    "get_db",
    "log_ring_status",
    "log_sync_complete",
    "log_sync_start",
    "scan_ring",
    "sync_time_to_ring",
    "update_progress",
    "upsert_goals",
    "upsert_heart_rate",
    "upsert_hrv",
    "upsert_sleep",
    "upsert_spo2",
    "upsert_steps",
    "upsert_stress",
    "upsert_temperature_list",
]
