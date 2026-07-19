"""HRV parser + upsert.

Fetches HRV history using cmd 0x39 (Gadgetbridge CMD_SYNC_HRV). Multi-packet
response, same layout as stress (cmd 0x37).
"""
from __future__ import annotations

import logging
import struct
from datetime import datetime, timedelta

from colmi_r02_client.client import Client as _Client

from ..db import make_packet, upsert_hrv, _read_multi_packet

log = logging.getLogger(__name__)


async def fetch_hrv_history(client: _Client) -> list[dict]:
    """Fetch HRV history using cmd 0x39 (Gadgetbridge CMD_SYNC_HRV).

    Protocol from Gadgetbridge YawellRingPacketHandler.historicalHRV:
      - Request: {0x39, daysAgo (LE uint32)} per day, loop daysAgo 0..6
      - Response: multi-packet, same layout as stress (cmd 0x37)
        - Packet sub_type 0: header, byte[2]=expected packet count
        - Packet sub_type 0xFF: empty (no data for this day)
        - Packets 1..4: data bytes at 30-min intervals (12 in pkt 1, 13 in pkts 2-4)
        - Each value is a single byte (0-255 ms). 0=no data.
    """
    records = []
    local_now = datetime.now()
    for days_ago in range(0, 7):
        local_midnight = (local_now.replace(hour=0, minute=0, second=0, microsecond=0)
                          - timedelta(days=days_ago)).astimezone()
        request = make_packet(0x39, struct.pack("<I", days_ago))
        log.info(f"HRV fetch: daysAgo={days_ago}, target={local_midnight.date()}")
        await client.send_packet(request)
        packets = await _read_multi_packet(client, 0x39, timeout=10.0)
        if not packets:
            continue

        thirty_min = timedelta(minutes=30)
        minutes_in_previous = 0
        day_records = 0

        for pkt in packets:
            sub_type = pkt[1]
            if sub_type == 0 or sub_type == 0xFF:
                continue
            start = 3 if sub_type == 1 else 2
            if sub_type > 1:
                minutes_in_previous = 12 * 30
                minutes_in_previous += (sub_type - 2) * 13 * 30
            for i in range(start, min(len(pkt) - 1, 15)):
                val = pkt[i] & 0xFF
                if val == 0:
                    continue
                minute_of_day = minutes_in_previous + (i - start) * 30
                ts = local_midnight + timedelta(minutes=minute_of_day)
                records.append({"ts": ts, "hrv_value": val})
                day_records += 1

        if day_records:
            log.info(f"  HRV {local_midnight.date()}: {day_records} records")

    return records
