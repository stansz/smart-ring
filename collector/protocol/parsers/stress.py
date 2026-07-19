"""Stress parser + upsert.

cmd 0x37, multi-packet, 30-min intervals. Protocol from Gadgetbridge
ColmiR0xPacketHandler.historicalStress:
  - Packet sub_type 0: header, byte[2]=expected packet count
  - Packet 1: byte[2]=timestamp flag?, bytes[3-14]=12 stress values
  - Packets 2..4: bytes[2-14]=13 stress values each
  - Each value is 0-99. 0=no data. 1-29=relaxed, 30-59=normal,
    60-79=medium, 80-99=high.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from colmi_r02_client.client import Client as _Client

from ..db import make_packet, _read_multi_packet

log = logging.getLogger(__name__)


async def fetch_stress_history(client: _Client) -> list[dict]:
    await client.send_packet(make_packet(0x37, bytes(14)))
    packets = await _read_multi_packet(client, 0x37, timeout=10.0)
    if not packets:
        return []

    records = []
    local_now = datetime.now()
    local_midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone()
    thirty_min = timedelta(minutes=30)
    minutes_in_previous = 0

    for pkt in packets:
        sub_type = pkt[1]
        if sub_type == 0 or sub_type == 0xFF:
            continue
        start = 3 if sub_type == 1 else 2  # packet 1: data starts at byte 3
        if sub_type > 1:
            minutes_in_previous = 12 * 30  # 12 values in packet 1
            minutes_in_previous += (sub_type - 2) * 13 * 30
        for i in range(start, min(len(pkt) - 1, 15)):
            val = pkt[i] & 0xFF
            if val == 0:
                continue
            minute_of_day = minutes_in_previous + (i - start) * 30
            ts = local_midnight + timedelta(minutes=minute_of_day)
            records.append({"ts": ts, "stress_value": val})

    return records
