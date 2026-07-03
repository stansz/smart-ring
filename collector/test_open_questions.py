#!/usr/bin/env python3
"""
Test the three open questions against the actual ring.
Must have RING_ADDRESS set in .env or environment.
"""
import asyncio
import sys
from datetime import datetime, timezone
from colmi_r02_client.client import Client
from collector.sync_ring import (
    scan_ring, fetch_hrv_raw, fetch_sleep_data, listen_temperature,
    upsert_hrv, upsert_sleep, upsert_temperature
)


async def test_sync_behavior(client: Client):
    """Does syncing wipe data?"""
    print("=== TEST 1: Sync behavior ===")
    from collector.sync_ring import sync_ring
    result1 = await sync_ring(client.address)
    print(f"First sync: {result1.records_synced} records")
    result2 = await sync_ring(client.address)
    print(f"Second sync: {result2.records_synced} records")

    if result2.records_synced == 0:
        print("✓ Read-and-clear (data wiped after sync)")
    elif result2.records_synced == result1.records_synced:
        print("✓ Read-only (data persists)")
    else:
        print(f"? Mixed: {result2.records_synced} vs {result1.records_synced}")


async def test_hrv_format(client: Client):
    """RR intervals or composite score?"""
    print("\n=== TEST 2: HRV data format ===")
    records = await fetch_hrv_raw(client)
    print(f"Raw bytes returned, {len(records)} records parsed")
    for r in records[:3]:
        print(f"  {r['ts']}: value={r['hrv_value']}, type={r['hrv_type']}")
    print("Check: if hrv_value is ~20-100 (ms), it's RMSSD — RR intervals available")
    print("Check: if hrv_value is single-digit, it's a composite score")


async def test_temperature_sampling(client: Client):
    """How often does temp data arrive?"""
    print("\n=== TEST 3: Temperature sampling ===")
    temp_c = await listen_temperature(client, timeout=10.0)
    if temp_c:
        print(f"✓ Temperature: {temp_c:.1f}°C")
        print("Listen window was 10s — if data arrived, sampling is frequent")
    else:
        print("✗ No temperature data in 10s window")
        print("Sampling may be event-driven (e.g., on sync) or slower than expected")


async def main():
    import os
    address = os.environ.get("RING_ADDRESS")
    if not address:
        print("No RING_ADDRESS set, scanning...")
        address = await scan_ring()
        if not address:
            print("No ring found")
            return 1

    async with Client(address) as client:
        await test_sync_behavior(client)
        await test_hrv_format(client)
        await test_temperature_sampling(client)

    print("\n=== SUMMARY ===")
    print("Use results above to adjust:")
    print("- collector sync strategy (wipe vs persist)")
    print("- HRV computation approach (raw RR vs composite)")
    print("- temperature logging frequency")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))