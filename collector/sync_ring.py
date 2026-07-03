#!/usr/bin/env python3
"""
Collector wrapper for Colmi R09 ring.
Runs on bare metal (Linux Mint host) with direct BlueZ/DBus access.
Syncs ring data to local Postgres.
"""
import os
import sys
import asyncio
import logging
import subprocess
import json
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from dataclasses import dataclass

import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler("/home/sz/Code/smart-ring/collector/collector.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://smart_ring:changeme@localhost:5432/smart_ring")
RING_ADDRESS = os.getenv("RING_ADDRESS", "")  # Set after first scan
COLMI_CLIENT = "colmi_r02_client"  # Assumes installed in venv


@dataclass
class SyncResult:
    records_synced: int = 0
    battery_pct: Optional[int] = None
    clock_drift_ms: Optional[int] = None
    error: Optional[str] = None


def get_db():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def log_sync_start() -> int:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO sync_log (started_at, status)
                VALUES (NOW(), 'running')
                RETURNING id
            """)
            return cur.fetchone()["id"]


def log_sync_complete(sync_id: int, result: SyncResult):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE sync_log
                SET completed_at = NOW(),
                    records_synced = %s,
                    battery_pct = %s,
                    clock_drift_ms = %s,
                    status = %s,
                    error = %s
                WHERE id = %s
            """, (
                result.records_synced,
                result.battery_pct,
                result.clock_drift_ms,
                "completed" if not result.error else "error",
                result.error,
                sync_id
            ))


def run_colmi_command(args: List[str], timeout: int = 60) -> tuple[int, str, str]:
    """Run colmi_r02_client command and return (exit_code, stdout, stderr)."""
    cmd = [COLMI_CLIENT]
    if RING_ADDRESS:
        cmd.extend(["--address", RING_ADDRESS])
    cmd.extend(args)
    log.debug(f"Running: {' '.join(cmd)}")
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "Command timed out"
    except FileNotFoundError:
        return -1, "", f"Command not found: {COLMI_CLIENT}"


def parse_heart_rate_output(output: str) -> List[Dict[str, Any]]:
    """Parse colmi_r02_client heart rate output."""
    records = []
    for line in output.strip().split("\n"):
        if not line or line.startswith("====") or "BPM" in line and "Time" in line:
            continue
        parts = line.split()
        if len(parts) >= 2:
            try:
                ts_str = f"{parts[0]} {parts[1]}"
                bpm = int(parts[2]) if len(parts) > 2 else int(parts[-1])
                records.append({"ts": ts_str, "bpm": bpm})
            except (ValueError, IndexError):
                pass
    return records


def parse_hrv_output(output: str) -> List[Dict[str, Any]]:
    """Parse colmi_r02_client HRV output."""
    records = []
    for line in output.strip().split("\n"):
        if not line or line.startswith("===="):
            continue
        parts = line.split()
        if len(parts) >= 3:
            try:
                ts_str = f"{parts[0]} {parts[1]}"
                hrv_val = float(parts[2])
                hrv_type = parts[3] if len(parts) > 3 else "unknown"
                rr_intervals = None
                if len(parts) > 4 and parts[4].startswith("["):
                    rr_intervals = json.loads(" ".join(parts[4:]))
                records.append({
                    "ts": ts_str,
                    "hrv_value": hrv_val,
                    "hrv_type": hrv_type,
                    "rr_intervals": rr_intervals
                })
            except (ValueError, IndexError, json.JSONDecodeError):
                pass
    return records


def parse_sleep_output(output: str) -> List[Dict[str, Any]]:
    """Parse colmi_r02_client sleep output."""
    records = []
    current_day = None
    for line in output.strip().split("\n"):
        if not line:
            continue
        if line.startswith("Day") or "date" in line.lower():
            continue
        parts = line.split()
        if len(parts) >= 4:
            try:
                records.append({
                    "day": parts[0],
                    "stage": parts[1],
                    "start_ts": f"{parts[0]} {parts[2]}",
                    "end_ts": f"{parts[0]} {parts[3]}"
                })
            except (ValueError, IndexError):
                pass
    return records


def parse_steps_output(output: str) -> List[Dict[str, Any]]:
    """Parse colmi_r02_client steps output."""
    records = []
    for line in output.strip().split("\n"):
        if not line or line.startswith("===="):
            continue
        parts = line.split()
        if len(parts) >= 2:
            try:
                ts_str = f"{parts[0]} {parts[1]}"
                steps = int(parts[2]) if len(parts) > 2 else int(parts[-1])
                records.append({"ts": ts_str, "steps": steps})
            except (ValueError, IndexError):
                pass
    return records


def parse_spo2_output(output: str) -> List[Dict[str, Any]]:
    """Parse colmi_r02_client SpO2 output."""
    records = []
    for line in output.strip().split("\n"):
        if not line or line.startswith("===="):
            continue
        parts = line.split()
        if len(parts) >= 2:
            try:
                ts_str = f"{parts[0]} {parts[1]}"
                spo2 = int(parts[2]) if len(parts) > 2 else int(parts[-1])
                records.append({"ts": ts_str, "spo2_pct": spo2})
            except (ValueError, IndexError):
                pass
    return records


def parse_temperature_output(output: str) -> List[Dict[str, Any]]:
    """Parse colmi_r02_client temperature output."""
    records = []
    for line in output.strip().split("\n"):
        if not line or line.startswith("===="):
            continue
        parts = line.split()
        if len(parts) >= 2:
            try:
                ts_str = f"{parts[0]} {parts[1]}"
                temp = float(parts[2]) if len(parts) > 2 else float(parts[-1])
                records.append({"ts": ts_str, "temp_c": temp})
            except (ValueError, IndexError):
                pass
    return records


def parse_battery_output(output: str) -> Optional[int]:
    """Parse battery percentage from output."""
    for line in output.split("\n"):
        if "battery" in line.lower() or "%" in line:
            import re
            match = re.search(r"(\d+)%", line)
            if match:
                return int(match.group(1))
    return None


def parse_clock_drift(output: str) -> Optional[int]:
    """Parse clock drift in ms from output."""
    for line in output.split("\n"):
        if "drift" in line.lower() or "offset" in line.lower():
            import re
            match = re.search(r"([+-]?\d+) ?ms", line)
            if match:
                return int(match.group(1))
    return None


def upsert_heart_rate(records: List[Dict]) -> int:
    if not records:
        return 0
    with get_db() as conn:
        with conn.cursor() as cur:
            for r in records:
                cur.execute("""
                    INSERT INTO raw_heart_rate (ts, bpm, source)
                    VALUES (%s, %s, 'ring')
                    ON CONFLICT DO NOTHING
                """, (r["ts"], r["bpm"]))
            return cur.rowcount


def upsert_hrv(records: List[Dict]) -> int:
    if not records:
        return 0
    with get_db() as conn:
        with conn.cursor() as cur:
            for r in records:
                cur.execute("""
                    INSERT INTO raw_hrv (ts, hrv_value, hrv_type, rr_intervals, source)
                    VALUES (%s, %s, %s, %s, 'ring')
                    ON CONFLICT DO NOTHING
                """, (r["ts"], r["hrv_value"], r["hrv_type"], r["rr_intervals"]))
            return cur.rowcount


def upsert_sleep(records: List[Dict]) -> int:
    if not records:
        return 0
    with get_db() as conn:
        with conn.cursor() as cur:
            for r in records:
                cur.execute("""
                    INSERT INTO raw_sleep (day, stage, start_ts, end_ts, source)
                    VALUES (%s, %s, %s, %s, 'ring')
                    ON CONFLICT DO NOTHING
                """, (r["day"], r["stage"], r["start_ts"], r["end_ts"]))
            return cur.rowcount


def upsert_steps(records: List[Dict]) -> int:
    if not records:
        return 0
    with get_db() as conn:
        with conn.cursor() as cur:
            for r in records:
                cur.execute("""
                    INSERT INTO raw_steps (ts, steps, source)
                    VALUES (%s, %s, 'ring')
                    ON CONFLICT DO NOTHING
                """, (r["ts"], r["steps"]))
            return cur.rowcount


def upsert_spo2(records: List[Dict]) -> int:
    if not records:
        return 0
    with get_db() as conn:
        with conn.cursor() as cur:
            for r in records:
                cur.execute("""
                    INSERT INTO raw_spo2 (ts, spo2_pct, source)
                    VALUES (%s, %s, 'ring')
                    ON CONFLICT DO NOTHING
                """, (r["ts"], r["spo2_pct"]))
            return cur.rowcount


def upsert_temperature(records: List[Dict]) -> int:
    if not records:
        return 0
    with get_db() as conn:
        with conn.cursor() as cur:
            for r in records:
                cur.execute("""
                    INSERT INTO raw_temperature (ts, temp_c, source)
                    VALUES (%s, %s, 'ring')
                    ON CONFLICT DO NOTHING
                """, (r["ts"], r["temp_c"]))
            return cur.rowcount


def upsert_ring_status(battery_pct: Optional[int], clock_drift_ms: Optional[int]):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO ring_status (ts, battery_pct, clock_drift_ms)
                VALUES (NOW(), %s, %s)
            """, (battery_pct, clock_drift_ms))


def sync_ring() -> SyncResult:
    """Main sync routine. Returns SyncResult."""
    result = SyncResult()
    total_records = 0

    log.info("Starting ring sync...")

    # 1. Sync time first (corrects clock drift)
    log.info("Syncing ring time...")
    code, out, err = run_colmi_command(["set-time"])
    if code != 0:
        result.error = f"set-time failed: {err}"
        log.error(result.error)
        return result
    result.clock_drift_ms = parse_clock_drift(out)

    # 2. Get battery
    code, out, err = run_colmi_command(["get-battery"])
    if code == 0:
        result.battery_pct = parse_battery_output(out)
        log.info(f"Battery: {result.battery_pct}%")

    # 3. Sync heart rate
    log.info("Syncing heart rate...")
    code, out, err = run_colmi_command(["sync-heart-rate"])
    if code == 0:
        records = parse_heart_rate_output(out)
        count = upsert_heart_rate(records)
        total_records += count
        log.info(f"Heart rate: {count} new records")

    # 4. Sync HRV
    log.info("Syncing HRV...")
    code, out, err = run_colmi_command(["sync-hrv"])
    if code == 0:
        records = parse_hrv_output(out)
        count = upsert_hrv(records)
        total_records += count
        log.info(f"HRV: {count} new records")
        # Check if RR intervals are present (answers open question)
        if records and records[0].get("rr_intervals"):
            log.info("✓ HRV data includes RR intervals!")
        elif records:
            log.warning("✗ HRV data does NOT include RR intervals (composite only)")

    # 5. Sync sleep
    log.info("Syncing sleep...")
    code, out, err = run_colmi_command(["sync-sleep"])
    if code == 0:
        records = parse_sleep_output(out)
        count = upsert_sleep(records)
        total_records += count
        log.info(f"Sleep: {count} new records")

    # 6. Sync steps
    log.info("Syncing steps...")
    code, out, err = run_colmi_command(["sync-steps"])
    if code == 0:
        records = parse_steps_output(out)
        count = upsert_steps(records)
        total_records += count
        log.info(f"Steps: {count} new records")

    # 7. Sync SpO2
    log.info("Syncing SpO2...")
    code, out, err = run_colmi_command(["sync-spo2"])
    if code == 0:
        records = parse_spo2_output(out)
        count = upsert_spo2(records)
        total_records += count
        log.info(f"SpO2: {count} new records")

    # 8. Sync temperature (R09 exclusive)
    log.info("Syncing temperature...")
    code, out, err = run_colmi_command(["sync-temperature"])
    if code == 0:
        records = parse_temperature_output(out)
        count = upsert_temperature(records)
        total_records += count
        log.info(f"Temperature: {count} new records")
        if records:
            # Check sampling rate (answers open question)
            log.info(f"✓ Temperature sensor working, sample count: {len(records)}")

    result.records_synced = total_records
    upsert_ring_status(result.battery_pct, result.clock_drift_ms)
    log.info(f"Sync complete: {total_records} total new records")
    return result


def test_sync_behavior():
    """Test if syncing wipes data from ring (open question)."""
    log.info("=== TESTING SYNC BEHAVIOR ===")
    log.info("First sync...")
    result1 = sync_ring()
    log.info(f"First sync: {result1.records_synced} records")

    log.info("Immediate second sync...")
    result2 = sync_ring()
    log.info(f"Second sync: {result2.records_synced} records")

    if result2.records_synced == 0:
        log.info("✓ CONFIRMED: Sync is read-and-clear (data wiped after first sync)")
    elif result2.records_synced == result1.records_synced:
        log.info("✓ CONFIRMED: Sync is read-only (data persists on ring)")
    else:
        log.info(f"? PARTIAL: Second sync returned {result2.records_synced} vs {result1.records_synced}")


async def main():
    if len(sys.argv) > 1 and sys.argv[1] == "test-sync":
        sync_id = log_sync_start()
        try:
            test_sync_behavior()
        finally:
            log_sync_complete(sync_id, SyncResult(error="Test mode"))
        return

    if not RING_ADDRESS:
        log.warning("RING_ADDRESS not set. Run 'colmi_r02_util scan' first to find address.")
        log.info("Then set RING_ADDRESS in .env or export it.")
        sys.exit(1)

    sync_id = log_sync_start()
    try:
        result = sync_ring()
        log_sync_complete(sync_id, result)
        if result.error:
            sys.exit(1)
    except Exception as e:
        log.exception("Sync failed")
        log_sync_complete(sync_id, SyncResult(error=str(e)))
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())