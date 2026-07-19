"""BLE scan helper."""
from __future__ import annotations

import logging
from typing import Optional

from bleak import BleakScanner

log = logging.getLogger(__name__)


async def scan_ring(name_filter: str = "") -> Optional[str]:
    """Scan for ring and return BLE address."""
    log.info(f"Scanning for ring (filter: '{name_filter}')...")
    devices = await BleakScanner.discover(timeout=10.0, return_adv=True)

    for addr, (device, adv) in devices.items():
        name = device.name or adv.local_name or ""
        if name_filter.lower() in name.lower():
            log.info(f"Found ring: {name} ({addr})")
            return addr

    if devices and not name_filter:
        for addr, (device, adv) in devices.items():
            name = device.name or adv.local_name or ""
            if name:
                log.info(f"Device: {name} ({addr})")

    return None
