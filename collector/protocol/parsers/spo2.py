"""SpO2 parser + upsert.

Big-data type 0x2A. Per-day blocks with daysAgo byte + 24 hours ×
(min_byte, max_byte) pairs. Averaged to a single SpO2% per hour.
daysAgo == 0 means today (valid data), NOT a terminator.
"""
from __future__ import annotations

import logging
import struct
from datetime import datetime, timedelta

from colmi_r02_client.client import Client as _Client

from ._big_data import big_data_request

log = logging.getLogger(__name__)


def _parse_spo2_data(data: bytes) -> list[dict]:
    length = struct.unpack_from("<H", data, 2)[0]
    records: list[dict] = []
    idx = 6
    local_now = datetime.now()
    while idx + 49 <= 6 + length and idx + 49 <= len(data):
        days_ago = data[idx]; idx += 1
        target_date = (local_now - timedelta(days=days_ago)).date()
        for hour in range(24):
            spo2_min = data[idx]; idx += 1
            spo2_max = data[idx]; idx += 1
            if spo2_min > 0 and spo2_max > 0:
                ts = datetime.combine(target_date, datetime.min.time().replace(hour=hour)).astimezone()
                records.append({"ts": ts, "spo2_pct": round((spo2_min + spo2_max) / 2.0)})
    return records


async def fetch_spo2_history(client: _Client) -> list[dict]:
    """Fetch SpO2 data via CMD_BIG_DATA_V2 (type 0x2A)."""
    data = await big_data_request(client, 0x2A)
    if data is None:
        return []
    return _parse_spo2_data(data)
