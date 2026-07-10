#!/usr/bin/env python3
"""
Test whether syncing data from the ring clears its buffer.

Uses a SINGLE BLE connection (avoids the R09 reconnect bug) and fetches
the same data twice within that connection, comparing results.

R09 firmware 3.10.21 has a known reconnect bug: after disconnect, it won't
accept new connections. This script works around it by:
  1. Forgetting the ring from BlueZ (bluetoothctl remove)
  2. Re-pairing (bluetoothctl pair)
  3. Connecting once and doing all work within that connection
  4. Forgetting again at the end (prep for next run)

Usage:
    python3 collector/test_sync_readonly.py
"""
import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collector.ring_client import (
    Client,
    forget_ring,
    pair_ring,
    scan_for_address,
)
from collector.sync_ring import connect_with_retry


def print_steps(label: str, steps_data) -> None:
    """Pretty-print step data from the ring."""
    if not steps_data:
        print(f"  {label}: 0 entries (empty)")
        return

    if not isinstance(steps_data, list):
        steps_data = [steps_data]

    total_steps = 0
    print(f"  {label}: {len(steps_data)} entries")
    for s in steps_data:
        total_steps += getattr(s, "steps", 0)
        print(f"    time_index={s.time_index}: "
              f"steps={s.steps}  calories={s.calories}  distance={s.distance}")
    print(f"  Total steps: {total_steps}")


def compare_and_print(steps_a, steps_b) -> None:
    """Compare two step fetches and print the read-only vs wipe verdict."""
    if not isinstance(steps_a, list):
        steps_a = [steps_a] if steps_a else []
    if not isinstance(steps_b, list):
        steps_b = [steps_b] if steps_b else []

    if not steps_a and not steps_b:
        print("? INCONCLUSIVE — both fetches returned 0 entries")
        print("  Wear the ring longer to accumulate step data, then retry.")
        return

    a_compact = [(s.time_index, s.steps) for s in steps_a]
    b_compact = [(s.time_index, s.steps) for s in steps_b]

    if a_compact == b_compact:
        print("=" * 50)
        print(" VERDICT: READ-ONLY")
        print("=" * 50)
        print("Data persists on the ring after being fetched.")
        print("Safe to sync from multiple devices (phone + collector).")
        print("Cron-driven syncs won't lose data.")
    elif len(steps_b) == 0:
        print("=" * 50)
        print(" VERDICT: READ-AND-CLEAR")
        print("=" * 50)
        print("Ring buffer was WIPED after the first fetch!")
        print("NEVER sync from phone AND collector simultaneously.")
        print("Cron must be the sole sync source.")
    elif len(steps_b) < len(steps_a):
        print("=" * 50)
        print(f" VERDICT: LIKELY READ-AND-CLEAR ({len(steps_a)} -> {len(steps_b)} entries)")
        print("=" * 50)
        print("Some data was cleared after the first fetch.")
        print("Treat as read-and-clear: don't sync from multiple devices.")
    else:
        print("=" * 50)
        print(f" VERDICT: UNCLEAR ({len(steps_a)} vs {len(steps_b)} entries)")
        print("=" * 50)
        print("Ring may have accumulated new data between fetches.")
        print("Compare the time_index lists above manually.")
        # Check if all of A's entries also appear in B
        a_ids = set(a_compact)
        b_ids = set(b_compact)
        if a_ids.issubset(b_ids):
            missing = b_ids - a_ids
            print(f"B contains all of A's entries plus {len(missing)} new ones.")
            print("This suggests READ-ONLY (data persists + new data added).")


async def main() -> int:
    address = os.environ.get("RING_ADDRESS")
    if not address:
        print("No RING_ADDRESS set in .env")
        return 1

    print("=" * 50, flush=True)
    print(" Sync Behavior Test (read-only vs read-and-clear)", flush=True)
    print("=" * 50, flush=True)

    # ── Phase 1: Forget ring (clear stale BlueZ state) ──
    print("\nPhase 1: Forgetting ring from BlueZ...")
    forget_ring(address)
    await asyncio.sleep(1)

    # ── Phase 2: Scan to verify ring is advertising ──
    print("Phase 2: Scanning for ring (15s)...")
    found = await scan_for_address(address, timeout=15.0)
    if not found:
        print("\nRing not found. Wear/tap/charge the ring to wake it, then retry.")
        print("Run: python3 collector/test_sync_readonly.py")
        forget_ring(address)
        return 1

    # ── Phase 3: Pair ──
    print("Phase 3: Pairing ring...")
    paired = pair_ring(address, timeout=30.0)
    if paired:
        print("  Pairing successful")
    else:
        print("  WARNING: Pairing failed — trying to connect anyway...")

    # ── Phase 4: Connect + test ──
    print("Phase 4: Connecting (5 attempts, 15s timeout each)...")
    try:
        client = await connect_with_retry(
            address, attempts=5, connect_timeout=15.0,
            wake_ping=False, forget_repair=False,
        )
    except RuntimeError as e:
        print(f"\nFailed to connect: {e}")
        forget_ring(address)
        return 1

    try:
        print("  Connected! Settling 2s...")
        await asyncio.sleep(2)

        today = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

        # ── Fetch #1 ──
        print("\n--- Fetch #1 ---")
        try:
            steps_a = await client.get_steps(today)
            print_steps("Fetch #1", steps_a)
        except Exception as e:
            print(f"  Fetch #1 failed: {e}")
            steps_a = []

        await asyncio.sleep(3)

        # ── Fetch #2 ──
        print("\n--- Fetch #2 ---")
        try:
            steps_b = await client.get_steps(today)
            print_steps("Fetch #2", steps_b)
        except Exception as e:
            print(f"  Fetch #2 failed: {e}")
            steps_b = []

        # ── Verdict ──
        print()
        compare_and_print(steps_a, steps_b)

    finally:
        print("\nDisconnecting...", flush=True)
        try:
            await asyncio.wait_for(
                client.__aexit__(None, None, None),
                timeout=10.0,
            )
        except (asyncio.TimeoutError, Exception):
            print("  (disconnect timed out — non-fatal)", flush=True)

    # ── Phase 5: Forget ring (prep for next run) ──
    print("Phase 5: Forgetting ring (prep for next run)...")
    forget_ring(address)
    print("\nDone. The ring is now in a clean BLE state.")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
