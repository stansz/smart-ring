"""DB primitives, sync state, packet framing, and upserts shared by all parsers.

Split out of sync_ring.py (Phase 3). The protocol code in this file is
byte-for-byte identical to the working implementation — no 'improvements'
against colmi_r02_client upstream.
"""
from __future__ import annotations

import asyncio
import logging
import os
import struct
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

import psycopg2
from psycopg2.extras import RealDictCursor

from colmi_r02_client.client import Client as _Client

log = logging.getLogger(__name__)

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://smart_ring:changeme@localhost:5432/smart_ring"
)


@dataclass
class SyncResult:
    records_synced: int = 0
    battery_pct: Optional[int] = None
    fw_version: Optional[str] = None
    error: Optional[str] = None
    warnings: Optional[str] = None
    time_sync_acked: Optional[bool] = None
    logger_stalled: bool = False
    logger_auto_recovery: bool = False


def get_db():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def log_sync_start() -> int:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO sync_log (started_at, status) VALUES (NOW(), 'running') RETURNING id"
            )
            return cur.fetchone()["id"]


def log_sync_complete(sync_id: int, result: SyncResult):
    # clock_drift_ms column repurposed: 1 = set_time acked by ring, 0 = no ack, NULL = unknown
    ack_flag = None
    if result.time_sync_acked is not None:
        ack_flag = 1 if result.time_sync_acked else 0
    status = "completed" if not result.error else "error"
    error_msg = result.error
    if result.warnings:
        error_msg = (result.error + "; " if result.error else "") + result.warnings
    if result.logger_auto_recovery:
        log.info("Logger auto-recovery: HR-log setting was toggled to restart ring logger")
    if result.logger_stalled and not result.logger_auto_recovery:
        log.warning("HR logger STALLED but auto-recovery was not attempted")
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE sync_log SET completed_at = NOW(), records_synced = %s,
                    battery_pct = %s, clock_drift_ms = %s, status = %s, error = %s
                WHERE id = %s
            """,
                (result.records_synced, result.battery_pct, ack_flag,
                 status, error_msg, sync_id),
            )


def update_progress(sync_id: Optional[int], step: str):
    if sync_id is None:
        return
    log.info(f"Progress: {step}")
    try:
        with get_db() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE sync_log SET current_step = %s WHERE id = %s",
                (step, sync_id),
            )
    except Exception:
        pass  # non-critical


def log_ring_status(battery_pct: Optional[int], fw_version: Optional[str]):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ring_status (ts, battery_pct, firmware_version)
                VALUES (NOW(), %s, %s)
            """,
                (battery_pct, fw_version),
            )


def make_packet(command_id: int, subdata: bytes = b"") -> bytearray:
    """Build a 16-byte BLE packet with CRC."""
    assert len(subdata) <= 14
    data = bytearray(16)
    data[0] = command_id
    data[1:1 + len(subdata)] = subdata
    checksum = (command_id + sum(subdata)) & 0xFF
    data[-1] = checksum
    return data


# ----------------------------------------------------------------
# Multi-packet reader (used by HRV, stress, and other historical
# commands that split responses across several notification packets).
# ----------------------------------------------------------------

async def _read_multi_packet(
    client: _Client, cmd: int, timeout: float = 10.0
) -> list[bytearray]:
    """Read all packets for a multi-packet ring response (stress, HRV, etc.).
    Each packet goes through the notification handler and ends up in
    client.queues[cmd]. We read until the expected last sub_type or timeout."""
    items: list[bytearray] = []
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            break
        try:
            item = await asyncio.wait_for(
                client.queues[cmd].get(),
                timeout=min(remaining, 2.0),
            )
        except asyncio.TimeoutError:
            break
        if not isinstance(item, (bytearray, bytes)):
            break
        items.append(bytearray(item))
        # Gadgetbridge stress: sub_type==4 is the last data packet
        if len(item) >= 2 and item[1] in (4, 0xFF):
            break
    return items


# ----------------------------------------------------------------
# Upserts — one per raw_* table. Each takes the parsed dict list from
# the parser and writes to Postgres. Returns the count of new rows.
# ----------------------------------------------------------------

def upsert_heart_rate(records: List[Dict]) -> int:
    if not records:
        return 0
    count = 0
    with get_db() as conn:
        with conn.cursor() as cur:
            for r in records:
                ts = r.get("ts")
                bpm = r.get("bpm")
                if ts and bpm and isinstance(bpm, int) and 30 < bpm < 250:
                    cur.execute("""
                        INSERT INTO raw_heart_rate (ts, bpm, source)
                        VALUES (%s, %s, 'ring')
                        ON CONFLICT (ts, source) DO NOTHING
                    """, (ts, bpm))
                    count += cur.rowcount
    return count


def upsert_hrv(records: List[Dict]) -> int:
    if not records:
        return 0
    count = 0
    with get_db() as conn:
        with conn.cursor() as cur:
            for r in records:
                cur.execute("""
                    INSERT INTO raw_hrv (ts, hrv_value, hrv_type, source)
                    VALUES (%s, %s, %s, 'ring')
                    ON CONFLICT (ts, hrv_type, source) DO NOTHING
                """, (r["ts"], r["hrv_value"], r.get("hrv_type", "composite")))
                count += cur.rowcount
    return count


def upsert_sleep(records: List[Dict]) -> int:
    if not records:
        return 0
    count = 0
    with get_db() as conn:
        with conn.cursor() as cur:
            for r in records:
                cur.execute("""
                    INSERT INTO raw_sleep (day, stage, start_ts, end_ts, duration_minutes, source)
                    VALUES (%s, %s, %s, %s, %s, 'ring')
                    ON CONFLICT (start_ts, stage, source) DO UPDATE SET
                        end_ts = EXCLUDED.end_ts,
                        duration_minutes = EXCLUDED.duration_minutes
                """, (r["day"], r["stage"], r.get("start_ts"), r.get("end_ts"),
                      r.get("duration_minutes")))
                count += cur.rowcount
    return count


def upsert_steps(records: List[Dict]) -> int:
    if not records:
        return 0
    count = 0
    with get_db() as conn:
        with conn.cursor() as cur:
            for r in records:
                cur.execute("""
                    INSERT INTO raw_steps (ts, steps, calories, distance, source)
                    VALUES (%s, %s, %s, %s, 'ring')
                    ON CONFLICT (ts, source) DO NOTHING
                """, (r.get("ts", datetime.now()),
                      r.get("steps", 0),
                      r.get("calories"),
                      r.get("distance")))
                count += cur.rowcount
    return count


def upsert_spo2(records: List[Dict]) -> int:
    if not records:
        return 0
    count = 0
    with get_db() as conn:
        with conn.cursor() as cur:
            for r in records:
                cur.execute("""
                    INSERT INTO raw_spo2 (ts, spo2_pct, source)
                    VALUES (%s, %s, 'ring')
                    ON CONFLICT (ts, source) DO NOTHING
                """, (r["ts"], r["spo2_pct"]))
                count += cur.rowcount
    return count


def upsert_temperature_list(records: list[dict]) -> int:
    if not records:
        return 0
    count = 0
    with get_db() as conn:
        with conn.cursor() as cur:
            for r in records:
                cur.execute("""
                    INSERT INTO raw_temperature (ts, temp_c, source)
                    VALUES (%s, %s, 'ring')
                    ON CONFLICT (ts, source) DO NOTHING
                """, (r["ts"], r["temp_c"]))
                count += cur.rowcount
    return count


def upsert_stress(records: list[dict]) -> int:
    if not records:
        return 0
    count = 0
    with get_db() as conn:
        with conn.cursor() as cur:
            for r in records:
                cur.execute("""
                    INSERT INTO raw_stress (ts, stress_value, source)
                    VALUES (%s, %s, 'ring')
                    ON CONFLICT (ts, source) DO NOTHING
                """, (r["ts"], r["stress_value"]))
                count += cur.rowcount
    return count


def upsert_goals(goals: dict) -> int:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO ring_goals (steps_goal, calories_goal, distance_m_goal,
                                        sport_min_goal, sleep_min_goal)
                VALUES (%s, %s, %s, %s, %s)
            """, (
                goals["steps_goal"], goals["calories_goal"],
                goals["distance_m_goal"], goals["sport_min_goal"],
                goals["sleep_min_goal"],
            ))
            return cur.rowcount
