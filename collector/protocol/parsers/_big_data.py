"""Big-data V2 protocol helpers (cmd 0xBC, NOTIFY_V2 characteristic).

Used by sleep, SpO2, and temperature parsers. They share a single
big_data_queue + _bd_buf on the Client, so we drain + reset before every
request to avoid cross-type packet contamination.
"""
from __future__ import annotations

import asyncio
import logging

from colmi_r02_client.client import Client as _Client

log = logging.getLogger(__name__)


async def big_data_request(client: _Client, data_type: int):
    """Send a CMD_BIG_DATA_V2 request and wait for the complete response.

    Drains the shared queue + resets the multi-packet accumulator before
    each request so stale responses from prior commands cannot poison
    the next read. This applies to sleep, SpO2, and temperature — they
    all share one big_data_queue and one _bd_buf.
    """
    if not client.has_v2:
        log.info("V2 not available, skipping big-data request")
        return None
    # Drain stale items from prior requests
    drained = 0
    while True:
        try:
            client.big_data_queue.get_nowait()
            drained += 1
        except asyncio.QueueEmpty:
            break
    if hasattr(client, '_bd_buf'):
        client._bd_buf = None
        client._bd_size = 0
    if drained:
        log.info(f"Big-data drain before 0x{data_type:02x}: flushed {drained} stale packet(s)")
    # Send request
    request = bytearray([0xBC, data_type, 0x01, 0x00, 0xFF, 0x00, 0xFF])
    await client.send_command(request)
    try:
        raw = bytes(await asyncio.wait_for(client.big_data_queue.get(), timeout=15.0))
        head = raw[:32].hex() if len(raw) > 0 else "<empty>"
        log.info(f"Big-data resp 0x{data_type:02x}: len={len(raw)} head={head}")
        return raw
    except asyncio.TimeoutError:
        log.warning(f"Big-data timeout for type 0x{data_type:02x} (no response in 15s)")
        return None
