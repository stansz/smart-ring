#!/usr/bin/env python3
"""
Collector for Colmi R09 ring.
Uses colmi_r02_client library + bleak for async BLE.
Syncs ring data to local Postgres.

Phase 3 split: this file is now a thin orchestrator. All BLE protocol
helpers, parsers, DB upserts, and the R09 time-sync (sacred) live in
collector/protocol/. This file only owns the orchestration of the 11
sync steps + argparse main().
"""
import os
import sys
import asyncio
import argparse
import logging
from datetime import datetime, timedelta

from dotenv import load_dotenv

from collector.ring_client import Client
from collector.protocol import (
    SyncResult,
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
from collector.protocol.connect import connect_with_retry
from collector.protocol.scanner import scan_ring
from collector.protocol.time_sync import sync_time_to_ring
from collector.protocol.parsers.goals import fetch_goals
from collector.protocol.parsers.hr import fetch_hr_history
from collector.protocol.parsers.hrv import fetch_hrv_history
from collector.protocol.parsers.sleep import fetch_sleep_history
from collector.protocol.parsers.spo2 import fetch_spo2_history
from collector.protocol.parsers.steps import fetch_steps
from collector.protocol.parsers.stress import fetch_stress_history
from collector.protocol.parsers.temp import (
    drain_live_temperature,
    fetch_temperature_history,
)

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger(__name__)

RING_NAME_FILTER = os.getenv("RING_NAME_FILTER", "R09")  # BLE name filter


async def _collect_data(client: Client, address: str, sync_id: int | None = None) -> SyncResult:
    """All sync work after the BLE link is up. Used by sync_ring() and tests."""
    result = SyncResult()
    total_records = 0

    try:
        log.info(f"Connected to {address}")
        update_progress(sync_id, "Connected")

        # 1. Device info + battery
        try:
            update_progress(sync_id, "Reading device info...")
            info = await client.get_device_info()
            result.fw_version = info.get("fw_version")
            log.info(f"FW: {result.fw_version}")
        except Exception as e:
            log.debug(f"Device info failed: {e}")

        try:
            update_progress(sync_id, "Reading battery...")
            battery = await client.get_battery()
            result.battery_pct = battery.battery_level
            log.info(f"Battery: {result.battery_pct}%")
        except Exception as e:
            log.warning(f"Battery read failed: {e}")

        # 2. Sync time (SACRED — see protocol/time_sync.py)
        try:
            update_progress(sync_id, "Syncing time...")
            await sync_time_to_ring(client, result)
        except Exception as e:
            log.warning(f"Time sync failed: {e}")

        # 3. Heart rate (last 7 days, multi-packet)
        log.info("Syncing heart rate history...")
        update_progress(sync_id, "Fetching heart rate...")
        try:
            hr_records = await fetch_hr_history(client, None, None)
            count = upsert_heart_rate(hr_records)
            total_records += count
            log.info(f"Heart rate: {count} new records ({len(hr_records)} total)")
        except Exception as e:
            log.error(f"Heart rate sync failed: {e}")

        # 4. Steps (15-min slots, 7 days)
        update_progress(sync_id, "Fetching steps...")
        try:
            step_records = await fetch_steps(client, days=7)
            count = upsert_steps(step_records)
            total_records += count
            log.info(f"Steps: {count} new records")
        except Exception as e:
            log.error(f"Steps sync failed: {e}")

        # 5. HRV (cmd 0x39)
        update_progress(sync_id, "Fetching HRV...")
        try:
            hrv_records = await fetch_hrv_history(client)
            count = upsert_hrv(hrv_records)
            total_records += count
            log.info(f"HRV: {count} new records")
        except Exception as e:
            log.warning(f"HRV sync failed: {e}")

        # 6. Sleep (cmd 0xBC + type 0x27)
        update_progress(sync_id, "Fetching sleep...")
        try:
            sleep_records = await fetch_sleep_history(client)
            count = upsert_sleep(sleep_records)
            total_records += count
            log.info(f"Sleep: {count} stage records")
        except Exception as e:
            log.warning(f"Sleep sync failed: {e}")

        # 7. SpO2 (cmd 0xBC + type 0x2A)
        update_progress(sync_id, "Fetching SpO2...")
        try:
            spo2_records = await fetch_spo2_history(client)
            count = upsert_spo2(spo2_records)
            total_records += count
            log.info(f"SpO2: {count} records")
        except Exception as e:
            log.warning(f"SpO2 sync failed: {e}")

        # 8. Temperature (cmd 0xBC + types 0x23-0x2B, skip 0x2A)
        update_progress(sync_id, "Fetching temperature...")
        try:
            temp_records = await fetch_temperature_history(client)
            count = upsert_temperature_list(temp_records)
            total_records += count
            log.info(f"Temperature: {count} new records inserted")
            today = datetime.now().date()
            yesterday = today - timedelta(days=1)
            has_yesterday = any(r["ts"].astimezone().date() == yesterday for r in temp_records)
            if not has_yesterday:
                # Real anomaly: yesterday's temp should have committed by now
                result.warnings = "temp: yesterday's data still missing — ring may not have published"
                log.warning("Temp anomaly: yesterday's block absent from ring buffer")
            # Normal case (today pending, yesterday present) → silent. No log, no warning.
        except Exception as e:
            log.warning(f"Temperature sync failed: {e}")

        # 8b. Live temperature drain (cmd 115 device-notify)
        try:
            total_records += await drain_live_temperature(client)
        except Exception as e:
            log.debug(f"Live temperature check: {e}")

        # 9. Stress (cmd 0x37, multi-packet)
        update_progress(sync_id, "Fetching stress...")
        try:
            stress_records = await fetch_stress_history(client)
            count = upsert_stress(stress_records)
            total_records += count
            log.info(f"Stress: {count} new records")
        except Exception as e:
            log.warning(f"Stress sync failed: {e}")

        # 10. Ring goals
        update_progress(sync_id, "Fetching goals...")
        try:
            goals = await fetch_goals(client)
            if goals:
                upsert_goals(goals)
                log.info(f"Goals: steps={goals['steps_goal']} cal={goals['calories_goal']} dist={goals['distance_m_goal']}m")
        except Exception as e:
            log.debug(f"Goals fetch failed: {e}")

    finally:
        result.records_synced = total_records
        log_ring_status(result.battery_pct, result.fw_version)
        log.info(f"Sync complete: {total_records} total new records")

    return result


async def sync_ring(
    address: str,
    *,
    attempts: int = 5,
    wake_ping: bool = True,
    forget_repair: bool = False,
    sync_id: int | None = None,
) -> SyncResult:
    """Main async sync routine with retry-on-sleep + R09 reconnect-bug workaround."""
    client = await connect_with_retry(
        address, attempts=attempts, wake_ping=wake_ping,
        forget_repair=forget_repair,
    )
    try:
        return await _collect_data(client, address, sync_id=sync_id)
    finally:
        try:
            await client.__aexit__(None, None, None)
        except Exception:
            pass
        # R09 reconnect bug: forget after disconnect so the next sync can connect
        if forget_repair:
            from collector.ring_client import forget_ring
            forget_ring(address)


async def main():
    parser = argparse.ArgumentParser(description="Sync Colmi R09 ring data to Postgres")
    parser.add_argument("command", nargs="?", default="sync", choices=["sync", "scan"],
                        help="sync (default) or scan")
    parser.add_argument("--no-retry", action="store_true",
                        help="fail fast on first connect failure (testing)")
    parser.add_argument("--attempts", type=int, default=5,
                        help="connect attempts (cron should use 12+)")
    parser.add_argument("--no-forget", action="store_true",
                        help="skip forget+re-pair before connecting (diagnostics only)")
    args = parser.parse_args()

    if args.command == "scan":
        address = await scan_ring(RING_NAME_FILTER)
        if address:
            print(f"Found ring: {address}")
            print(f"Set RING_ADDRESS={address} in .env")
        else:
            print("No ring found. Try without name filter or check BLE.")
        return

    # forget+repair is the reliable default for R09; --no-forget is opt-out
    do_forget = not args.no_forget

    address = os.environ.get("RING_ADDRESS")
    if not address:
        log.info("No RING_ADDRESS set. Scanning...")
        address = await scan_ring(RING_NAME_FILTER)
        if not address:
            log.error("No ring found. Run 'python -m collector.sync_ring scan' to find, then set RING_ADDRESS")
            sys.exit(1)

    sync_id = log_sync_start()
    try:
        if args.no_retry:
            log.info("--no-retry: skipping connect retry loop")
            client = Client(address, timeout=30.0)
            try:
                await client.__aenter__()
                result = await _collect_data(client, address)
            finally:
                try:
                    await client.__aexit__(None, None, None)
                except Exception:
                    pass
        else:
            result = await sync_ring(address, attempts=args.attempts, forget_repair=do_forget, sync_id=sync_id)

        log_sync_complete(sync_id, result)
        if result.error:
            sys.exit(1)
    except Exception as e:
        log.exception("Sync failed")
        log_sync_complete(sync_id, SyncResult(error=str(e)))
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
