#!/usr/bin/env python3
"""
Test whether syncing data from the ring clears its buffer.

Runs TWO scenarios:
  1. WITHIN-CONNECTION:  fetch twice within same BLE link (disconnect = ack?)
  2. ACROSS-DISCONNECT:  fetch, disconnect, reconnect, fetch again

If Scenario 1 is read-only but Scenario 2 returns zero => data clears on
DISconnect, not on fetch. That means the ring buffers are wiped when the
BLE link is torn down.

If BOTH scenarios are read-only => data persists regardless.

Usage:
    python3 collector/test_sync_readonly.py   [--skip-within]
"""
import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collector.ring_client import (
    forget_ring,
    pair_ring,
    scan_for_address,
)
from collector.sync_ring import connect_with_retry


def print_steps(label: str, steps_data) -> None:
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


def compact(steps_data):
    if not steps_data:
        return []
    if not isinstance(steps_data, list):
        steps_data = [steps_data]
    return [(s.time_index, s.steps) for s in steps_data]


def verdict(a_compact, b_compact, context: str):
    if not a_compact and not b_compact:
        print("  ? INCONCLUSIVE — both empty")
        return
    if a_compact == b_compact:
        print(f"  READ-ONLY — {context}")
    elif len(b_compact) == 0:
        print(f"  READ-AND-CLEAR — {context}")
    elif len(b_compact) < len(a_compact):
        print(f"  LIKELY READ-AND-CLEAR ({len(a_compact)}→{len(b_compact)}) — {context}")
    else:
        a_set = set(a_compact)
        b_set = set(b_compact)
        if a_set.issubset(b_set):
            new = b_set - a_set
            print(f"  READ-ONLY (all old + {len(new)} new) — {context}")
        else:
            print(f"  UNCLEAR ({len(a_compact)}→{len(b_compact)}) — {context}")


async def connect_and_forget(address: str):
    """Forget, scan, pair, connect. Returns connected client."""
    print("  Forgetting...")
    forget_ring(address)
    await asyncio.sleep(1)

    print("  Scanning...")
    found = await scan_for_address(address, timeout=15.0)
    if not found:
        raise RuntimeError("Ring not advertising")

    print("  Pairing...")
    pair_ring(address, timeout=30.0)

    print("  Connecting...")
    client = await connect_with_retry(
        address, attempts=5, connect_timeout=15.0,
        wake_ping=False, forget_repair=False,
    )
    await asyncio.sleep(2)
    return client


async def disconnect_clean(client, address: str):
    try:
        await asyncio.wait_for(
            client.__aexit__(None, None, None),
            timeout=10.0,
        )
    except (asyncio.TimeoutError, Exception):
        print("  (disconnect timeout — non-fatal)")
    forget_ring(address)


async def main() -> int:
    address = os.environ.get("RING_ADDRESS")
    if not address:
        print("No RING_ADDRESS set in .env")
        return 1

    today = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    skip_within = "--skip-within" in sys.argv

    # ================================================================
    # SCENARIO 1: Two fetches within the SAME connection
    # ================================================================
    if not skip_within:
        print("=" * 60, flush=True)
        print(" SCENARIO 1: WITHIN-CONNECTION (2 fetches, no disconnect)", flush=True)
        print("=" * 60, flush=True)

        try:
            client = await connect_and_forget(address)
        except RuntimeError as e:
            print(f"Failed: {e}")
            return 1

        try:
            print("\n--- Fetch #1 ---")
            steps_a = await client.get_steps(today)
            print_steps("A", steps_a)
            await asyncio.sleep(2)

            print("\n--- Fetch #2 ---")
            steps_b = await client.get_steps(today)
            print_steps("B", steps_b)

            print()
            verdict(compact(steps_a), compact(steps_b),
                    "data persists within same connection")
        finally:
            print("\nDisconnecting...")
            await disconnect_clean(client, address)
            await asyncio.sleep(3)

    # ================================================================
    # SCENARIO 2: Fetch, disconnect, reconnect, fetch again
    # ================================================================
    print("=" * 60, flush=True)
    print(" SCENARIO 2: ACROSS-DISCONNECT (fetch, disconnect, reconnect, fetch)", flush=True)
    print("=" * 60, flush=True)

    try:
        client = await connect_and_forget(address)
    except RuntimeError as e:
        print(f"Failed to connect for Scenario 2: {e}")
        return 1

    try:
        print("\n--- Fetch #1 (before disconnect) ---")
        steps_a = await client.get_steps(today)
        print_steps("A", steps_a)
    finally:
        print("\nDisconnecting...")
        await disconnect_clean(client, address)

    # Wait for ring to settle after disconnect
    print("\nWaiting 10s for ring to settle after disconnect...")
    await asyncio.sleep(10)

    try:
        client = await connect_and_forget(address)
    except RuntimeError as e:
        print(f"Failed to reconnect: {e}")
        # Still show what we know
        verdict(compact(steps_a), [],
                "second fetch failed — inconclusive across disconnect")
        return 1

    try:
        print("\n--- Fetch #2 (after disconnect + reconnect) ---")
        steps_b = await client.get_steps(today)
        print_steps("B", steps_b)

        print()
        verdict(compact(steps_a), compact(steps_b),
                "across disconnect")
    finally:
        print("\nDisconnecting...")
        await disconnect_clean(client, address)

    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
