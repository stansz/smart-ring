#!/usr/bin/env python3
"""
Safe first-contact script for the Colmi R09 ring.
Connects, reads device info + battery, sets the clock, then disconnects.
NO data sync — this is a read-only diagnostic. Run this BEFORE any sync.

Usage:
    python3 collector/first_contact.py              # uses RING_ADDRESS from .env
    python3 collector/first_contact.py --scan       # scan for ring first
    python3 collector/first_contact.py --address XX:XX:XX:XX
"""
import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# Allow running first_contact.py directly: add the project root to sys.path
# so `from collector import ...` works.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from bleak import BleakScanner
from collector.sync_ring import connect_with_retry
from dotenv import load_dotenv

load_dotenv()

LOG_DIR = Path(__file__).resolve().parent
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "first_contact.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)


async def scan(name_filter: str = "R0") -> Optional[str]:
    log.info(f"Scanning for ring (filter='{name_filter}')...")
    devices = await BleakScanner.discover(timeout=10.0, return_adv=True)
    best = []
    for addr, (device, adv) in devices.items():
        name = device.name or adv.local_name or ""
        if name_filter.lower() in name.lower():
            best.append((addr, name))
    if not best and devices and not name_filter:
        for addr, (device, adv) in devices.items():
            name = device.name or adv.local_name or ""
            if name:
                best.append((addr, name))
    if best:
        addr, name = best[0]
        log.info(f"Found: {name} ({addr})")
        return addr
    return None


async def first_contact(address: str, *, attempts: int = 5, wake_ping: bool = True) -> int:
    """Connect (with retry), read info, set clock, disconnect. Returns exit code."""
    print("=" * 50)
    print(f" First Contact: {address}")
    print("=" * 50)

    # R09 ring sleeps within ~30s — use the shared retry helper so a manual
    # "First Contact" button click survives the ring napping in a drawer.
    battery_pct: Optional[int] = None
    client = await connect_with_retry(address, attempts=attempts, wake_ping=wake_ping)
    try:

        # --- Device info ---
        print("\n[1/3] Device info...")
        try:
            info = await client.get_device_info()
            for key in sorted(info or {}):
                print(f"  {key}: {info[key]}")
                if isinstance(info[key], dict):
                    for sk, sv in info[key].items():
                        print(f"    {sk}: {sv}")
            if info:
                fw = info.get("fw_version", "unknown")
                print(f"  → Firmware: {fw}")
        except Exception as e:
            print(f"  WARNING: device info failed: {e}")

        # --- Battery ---
        print("\n[2/3] Battery...")
        try:
            battery_info = await client.get_battery()
            battery_pct = battery_info.battery_level
            charging = getattr(battery_info, "charging", None)
            print(f"  Charge: {battery_pct}%")
            if charging is not None:
                print(f"  Charging: {'yes' if charging else 'no'}")
        except Exception as e:
            print(f"  WARNING: battery read failed: {e}")

        # --- Set clock ---
        print("\n[3/3] Setting clock...")
        try:
            now = datetime.now()
            await client.set_time(now)
            print(f"  Clock synced: {now.strftime('%Y-%m-%d %H:%M:%S')}")
        except Exception as e:
            print(f"  WARNING: clock sync failed: {e}")

    finally:
        try:
            await client.__aexit__(None, None, None)
        except Exception:
            pass

    print("\n" + "=" * 50)
    print(" First contact complete. Ring hardware confirmed.")
    print("=" * 50)

    # Print next steps
    if battery_pct is not None and battery_pct < 15:
        print("\n⚠️  Battery is low — charge the ring before proceeding.")
    else:
        print("\n✓ Ready for Step 4: run test_open_questions.py")
        print("  python3 collector/test_open_questions.py")

    return 0


async def main():
    parser = argparse.ArgumentParser(description="Safe first-contact ring diagnostic")
    parser.add_argument("--scan", action="store_true", help="Scan for ring")
    parser.add_argument("--address", help="BLE address (overrides .env)")
    args = parser.parse_args()

    address = args.address or os.environ.get("RING_ADDRESS")

    if args.scan or not address:
        address = await scan()
        if not address:
            print("No ring found. Set RING_ADDRESS in .env or pass --address.")
            sys.exit(1)

    sys.exit(await first_contact(address))


if __name__ == "__main__":
    asyncio.run(main())
