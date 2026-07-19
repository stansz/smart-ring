"""Connect to ring with retry + R09 reconnect-bug workaround.

R09 firmware 3.10.21 has two known issues:
1. Aggressive sleep — stops advertising ~30s after disconnect.
   Handled by retry + exponential backoff.
2. Reconnect bug — after a disconnect, BlueZ holds stale GATT state that
   prevents new connections. Worked around by bluetoothctl remove + pair
   (forget + re-pair).

Do NOT change the forget-repair flow or the wake-ping scan ordering — these
workarounds are what makes the R09 syncable from a Linux host.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from bleak import BleakError, BleakScanner

from colmi_r02_client.client import Client as _Client
from ..ring_client import forget_and_repair  # noqa: F401 (re-export for callers)

log = logging.getLogger(__name__)


async def connect_with_retry(
    address: str,
    *,
    attempts: int = 5,
    initial_backoff: float = 2.0,
    connect_timeout: float = 30.0,
    wake_ping: bool = False,
    forget_repair: bool = False,
) -> _Client:
    """Connect to the ring, retrying on failure.

    Parameters:
        forget_repair: If True, run forget+re-pair BEFORE the first connect
            attempt. Use this when the ring was previously connected and
            disconnected (the R09 reconnect bug will block normal connects).
            If the re-pair fails (ring not advertising), falls through to
            plain retry — the ring may wake up during the backoff window.

        wake_ping: If True, run a short BLE scan FIRST (before forget+repair)
            to nudge the ring's radio awake. Also runs a scan on the last
            retry attempt as a last-ditch wake-up.

    Returns a connected Client. Caller MUST call ``await client.__aexit__(...)``
    when done.
    """
    # Wake-ping FIRST: scan before anything else to nudge the ring awake.
    # The scan MUST happen before forget+repair because the ring needs to
    # be advertising for pair_ring to succeed.
    if wake_ping:
        log.info("Wake-ping: scanning to nudge ring awake...")
        await BleakScanner.discover(timeout=5.0, return_adv=True)

    # R09 reconnect-bug workaround: clear stale BlueZ state before connecting
    if forget_repair:
        log.info("Forget+repair: clearing stale BlueZ state...")
        paired = await forget_and_repair(address)
        if paired:
            log.info("Re-paired successfully, attempting connect...")
        else:
            log.warning("Re-pair failed (ring may be asleep), trying plain connect...")

    last_exc: Optional[BaseException] = None
    for i in range(attempts):
        if wake_ping and i == attempts - 1:
            # Last-ditch: run a scan loop to coax the radio awake.
            log.info("Final attempt: running wake-ping scan (10s)...")
            await BleakScanner.discover(timeout=10.0, return_adv=True)

        try:
            client = _Client(address, timeout=connect_timeout)
            await client.__aenter__()
            return client
        except (BleakError, OSError, asyncio.TimeoutError, EOFError, ConnectionError) as e:
            last_exc = e
            if i < attempts - 1:
                wait = initial_backoff * (2 ** i)
                err_msg = str(e) or type(e).__name__
                log.info(
                    f"Connect attempt {i + 1}/{attempts} failed ({type(e).__name__}: "
                    f"{err_msg}). Retrying in {wait:.0f}s..."
                )
                await asyncio.sleep(wait)
            else:
                log.warning(f"Connect attempt {i + 1}/{attempts} failed: {e!r}")

    raise RuntimeError(
        f"Failed to connect to {address} after {attempts} attempts: {last_exc!r}"
    )
