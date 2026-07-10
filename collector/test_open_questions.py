#!/usr/bin/env python3
"""
Test the three open questions against the actual ring.
Must have RING_ADDRESS set in .env or environment.

Uses a single Client connection to avoid the ring dropping between syncs.
For Test 1 (sync behavior), you'll need to run the test twice and compare counts
to confirm read-only vs read-and-clear.
"""
import asyncio
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collector.ring_client import Client
from collector.sync_ring import (
    scan_ring,
    fetch_hrv_history,
    fetch_sleep_data_legacy,
    listen_temperature_legacy,
    upsert_hrv,
    upsert_sleep,
    upsert_temperature_single,
)


async def test_hrv_format(client):
    """RR intervals or composite score?"""
    print("\n=== TEST 2: HRV data format ===")
    records = await fetch_hrv_history(client)
    # Persist whatever the ring returns so we can inspect later
    count = upsert_hrv(records)
    print(f"Parsed {len(records)} HRV records ({count} new in DB)")
    for r in records[:5]:
        print(f"  ts={r['ts']}  value={r.get('hrv_value')}  type={r.get('hrv_type')}")
    if not records:
        print("  (no HRV data on ring; the device may need to wear it longer first)")
    else:
        vals = [r.get("hrv_value") for r in records if r.get("hrv_value") is not None]
        if vals and all(v < 200 for v in vals):
            sample = vals[0]
            if 10 <= sample <= 100:
                print(f"  → looks like composite score (sample={sample})")
            else:
                print(f"  → unknown format (sample={sample})")
        print("  Look at the raw bytes for cmd 57 to confirm.")


async def test_sleep_data(client):
    """What does cmd 68 return?"""
    print("\n=== TEST 2b: Sleep data format (cmd 68) ===")
    records = await fetch_sleep_data_legacy(client)
    count = upsert_sleep(records)
    print(f"Parsed {len(records)} sleep stage entries ({count} new in DB)")
    by_day = {}
    for r in records:
        by_day.setdefault(r["day"], []).append(r["stage"])
    for day, stages in by_day.items():
        print(f"  {day}: {stages}")


async def test_temperature_sampling(client):
    """How often does temp data arrive?"""
    print("\n=== TEST 3: Temperature sampling ===")
    temp_c = await listen_temperature_legacy(client, timeout=10.0)
    if temp_c:
        print(f"  Temperature: {temp_c:.1f}°C")
        upsert_temperature_single(temp_c)
        print("  Sampling is frequent — ring pushed within 10s.")
    else:
        print("  No temperature push in 10s.")
        print("  Sampling may be event-driven (sweat/skin contact) or slower.")


async def test_step_format(client):
    """Get one day of steps to confirm the format."""
    print("\n=== TEST 2c: Step data format ===")
    target = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    steps_data = await client.get_steps(target)
    print(f"  Got: {steps_data!r}")


async def gather_heart_rate(client):
    """Get a 10-min real-time HR sample (shows the ring's HR API is alive)."""
    print("\n=== TEST 1b: Heart rate (real-time) ===")
    from colmi_r02_client import real_time
    readings = await client.get_realtime_reading(real_time.RealTimeReading.HEART_RATE)
    if readings:
        avg = sum(readings) / len(readings)
        print(f"  Got {len(readings)} readings, avg {avg:.0f} bpm (sample: {readings})")
    else:
        print("  No HR readings returned (ring must be worn properly)")


async def main():
    import os
    address = os.environ.get("RING_ADDRESS")
    if not address:
        print("No RING_ADDRESS set, scanning...")
        address = await scan_ring()
        if not address:
            print("No ring found")
            return 1
    print(f"Using ring at {address}")

    # One Client, one connection. We do everything inside.
    async with Client(address, timeout=60.0) as client:
        info = await client.get_device_info()
        print(f"Connected, fw_version={info.get('fw_version')} hw_version={info.get('hw_version')}")

        try:
            await gather_heart_rate(client)
        except Exception as e:
            print(f"  HR test failed: {e}")
        try:
            await test_hrv_format(client)
        except Exception as e:
            print(f"  HRV test failed: {e}")
        try:
            await test_sleep_data(client)
        except Exception as e:
            print(f"  Sleep test failed: {e}")
        try:
            await test_step_format(client)
        except Exception as e:
            print(f"  Steps test failed: {e}")
        try:
            await test_temperature_sampling(client)
        except Exception as e:
            print(f"  Temp test failed: {e}")

    print("\n=== For TEST 1 (sync behavior) ===")
    print("Run this script TWICE in a row and compare total records_synced.")
    print("Tip: count rows in raw_heart_rate + raw_steps + raw_hrv + raw_sleep + raw_spo2 + raw_temperature")
    print("before and after — if they don't shrink, the sync is read-only.")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
