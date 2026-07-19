"""Time-sync helper — the working R09 time-sync flow.

SACRED CODE. Do NOT change any of this without confirming the new approach
against Gadgetbridge's ColmiR0xDeviceSupport.setDateTime() byte-for-byte.
The ring reads the BCD bytes as LOCAL wall-clock, not UTC — that's why we
bypass colmi_r02_client.set_time_packet() and encode directly via the
library's byte_to_bcd() + packet.make_packet() helpers.

The ack verification (await client.queues[1].get() with 3s timeout) is
also preserved — it's the only way to confirm the ring actually accepted
the new time.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import TYPE_CHECKING

from colmi_r02_client.client import Client as _Client

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .db import SyncResult


async def sync_time_to_ring(
    client: _Client, result: "SyncResult", settle_seconds: float = 2.0
) -> None:
    """Sync the ring's clock to host local time and wait for ack.

    Sets result.time_sync_acked = True/False/None on the SyncResult.
    None means the call raised before we could check the queue.
    """
    # Wait briefly so the ring's clock state is stable before we poke it.
    await asyncio.sleep(settle_seconds)
    now = datetime.now()
    await client.set_time_local(now)
    log.info(f"Time synced (local BCD): {now.strftime('%Y-%m-%d %H:%M:%S')}")
    # Wait for ring to acknowledge the set_time command (cmd 0x01).
    # The ring responds with a capability packet — its arrival confirms
    # the command was received and processed. This is a direct
    # verification, unlike the old drift metric which conflated
    # sampling lag with clock error.
    try:
        await asyncio.wait_for(client.queues[1].get(), timeout=3.0)
        result.time_sync_acked = True
        log.info("Time sync acknowledged by ring")
    except asyncio.TimeoutError:
        result.time_sync_acked = False
        log.warning("Time sync: no ack from ring (3s timeout) — time may not be set")
