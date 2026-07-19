"""Temperature parser + upsert.

Big-data response identifies as type 0x25 but the slot→day mapping rotates
across types 0x23–0x2B (skipping 0x2A = SpO2). We query the full range
0x22–0x2C, skip SpO2, and parse only responses whose dataId byte is 0x25.
"""
from __future__ import annotations

import asyncio
import logging
import struct
from datetime import datetime, timedelta, timezone

from colmi_r02_client.client import Client as _Client

from ..db import upsert_temperature_list
from ._big_data import big_data_request

log = logging.getLogger(__name__)

TEMP_ID = 0x25
SPO2_TYPE = 0x2A


def _parse_temperature_data(data: bytes) -> list[dict]:
    """Parse CMD_BIG_DATA_V2 temperature response (type 0x25).

    Gadgetbridge: per-day blocks with daysAgo byte + 0x1e skip byte +
    48 bytes (temp_00, temp_30 pairs for 24 hours).
    Each raw byte → °C = (raw / 10) + 20.
    daysAgo == 0 means today (valid data), NOT a terminator.
    Each day block is 50 bytes (1 daysAgo + 1 skip + 48 data).
    """
    length = struct.unpack_from("<H", data, 2)[0]
    if length < 50:
        return []
    records: list[dict] = []
    idx = 6
    local_now = datetime.now()
    while idx + 50 <= 6 + length and idx + 50 <= len(data):
        days_ago = data[idx]; idx += 1
        idx += 1  # skip extra byte (observed as 0x1e)
        target_date = (local_now - timedelta(days=days_ago)).date()
        block_start = idx
        for hour in range(24):
            t00 = data[idx] & 0xFF; idx += 1
            t30 = data[idx] & 0xFF; idx += 1
            if t00 > 0:
                temp_c = (t00 / 10.0) + 20
                ts = datetime.combine(target_date, datetime.min.time().replace(hour=hour, minute=0)).astimezone()
                records.append({"ts": ts, "temp_c": round(temp_c, 1)})
            if t30 > 0:
                temp_c = (t30 / 10.0) + 20
                ts = datetime.combine(target_date, datetime.min.time().replace(hour=hour, minute=30)).astimezone()
                records.append({"ts": ts, "temp_c": round(temp_c, 1)})
        non_zero = sum(1 for b in data[block_start:idx] if b > 0)
        log.info(f"  Temp block daysAgo={days_ago} date={target_date}: {non_zero}/48 non-zero bytes")
    return records


async def fetch_temperature_history(client: _Client) -> list[dict]:
    """Fetch temperature data via CMD_BIG_DATA_V2.

    The R09 stores up to 8 days of skin temperature across big-data
    types 0x23-0x2B (skipping 0x2A = SpO2). The slot→day mapping
    rotates daily, so query 0x22-0x2C to catch border cases and
    parse only responses whose dataId byte is 0x25 (temperature).
    """
    records = []
    for data_type in range(0x22, 0x2D):
        if data_type == SPO2_TYPE:
            continue
        data = await big_data_request(client, data_type)
        if data is None:
            continue
        if len(data) < 6 or data[1] != TEMP_ID:
            continue
        parsed = _parse_temperature_data(data)
        records.extend(parsed)
        log.debug(f"  Temp type 0x{data_type:02x}: parsed {len(parsed)} records")
    return records


async def drain_live_temperature(client: _Client) -> int:
    """Drain any cmd 115 device-notify packets (type 5 = temperature) that
    arrived during the sync. Saves the latest valid reading.

    The ring pushes unsolicited temperature notifications during sustained
    connections. During brief sync windows the queue is usually empty, but
    check anyway — costs nothing and captures data when the ring happens
    to push during our connection window.
    """
    live_temp = None
    queue_115 = client.queues.get(115)
    if queue_115:
        while not queue_115.empty():
            try:
                pkt = queue_115.get_nowait()
                if len(pkt) >= 4 and pkt[1] == 5:
                    temp_raw = struct.unpack_from("<H", pkt, 2)[0]
                    temp_c = temp_raw / 100.0 if temp_raw > 0 else None
                    if temp_c and 30 < temp_c < 45:
                        live_temp = temp_c
            except asyncio.QueueEmpty:
                break
    if live_temp:
        upsert_temperature_list([{"ts": datetime.now(tz=timezone.utc), "temp_c": live_temp}])
        log.info(f"Temperature (live): {live_temp:.1f}C")
        return 1
    return 0
