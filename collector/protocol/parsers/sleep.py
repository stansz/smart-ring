"""Sleep parser + upsert.

Big-data type 0x27. Stages (light/deep/rem/awake) with start_ts/end_ts.
If sleepStart > sleepEnd the session started before midnight (previous day).
"""
from __future__ import annotations

import logging
import struct
from datetime import datetime, timedelta

from colmi_r02_client.client import Client as _Client

from ._big_data import big_data_request

log = logging.getLogger(__name__)

# Per-day body layout (after the daysAgo + dayBytes prefix bytes):
#   sleepStart (uint16 LE, minutes after midnight) +
#   sleepEnd   (uint16 LE, minutes after midnight)
# Then 2-byte stage pairs: (stageType, durationMinutes).
_MINUTES_PER_DAY = 1440
_DAY_BODY_OFFSET = 4   # bytes consumed by sleepStart+sleepEnd before stage pairs


def _parse_sleep_data(data: bytes) -> list[dict]:
    """Parse CMD_BIG_DATA_V2 sleep response (type 0x27).

    Gadgetbridge YawellRingPacketHandler.historicalSleep:
      - value[2:3] = uint16 LE packet length
      - value[6]   = daysInPacket count
      - Per day: daysAgo (1 byte), dayBytes (1 byte),
                  sleepStart (uint16 LE, minutes after midnight),
                  sleepEnd (uint16 LE, minutes after midnight),
                  then (dayBytes-4)/2 stage entries:
                    stageType (1 byte: 2=light,3=deep,4=rem,5=awake),
                    durationMinutes (1 byte)
      - If sleepStart > sleepEnd: start was previous day (before midnight).
    """
    stage_names: dict[int, str] = {2: "light", 3: "deep", 4: "rem", 5: "awake"}
    packet_length = struct.unpack_from("<H", data, 2)[0]
    if packet_length < 2:
        return []
    days_in_packet = data[6]
    records: list[dict] = []
    idx = 7
    local_now = datetime.now()
    for _ in range(days_in_packet):
        # Per-day header: daysAgo(1) + dayBytes(1) + sleepStart(2) + sleepEnd(2) = 6 bytes
        if idx + 6 > len(data):
            log.warning(f"Sleep parse truncated at idx={idx} (day body incomplete)")
            break

        days_ago = data[idx]
        idx += 1
        day_bytes = data[idx]
        idx += 1
        sleep_start_min = struct.unpack_from("<H", data, idx)[0]
        idx += 2
        sleep_end_min = struct.unpack_from("<H", data, idx)[0]
        idx += 2

        target_date = (local_now - timedelta(days=days_ago)).date()
        midnight = datetime.combine(target_date, datetime.min.time()).astimezone()
        if sleep_start_min > sleep_end_min:
            # Session started before midnight — roll start back to the previous day.
            session_start = midnight + timedelta(minutes=sleep_start_min - _MINUTES_PER_DAY)
        else:
            session_start = midnight + timedelta(minutes=sleep_start_min)
        session_end = midnight + timedelta(minutes=sleep_end_min)

        # Walk the stage pairs. `day_bytes - _DAY_BODY_OFFSET` is the bytes left
        # after sleepStart+sleepEnd; each stage pair is 2 bytes.
        num_stages = (day_bytes - _DAY_BODY_OFFSET) // 2
        # Stage records use the stage's own wall-clock date, NOT target_date:
        # for pre-midnight sessions the early stages correctly attribute to the
        # previous calendar day. Don't "fix" this to target_date.
        stage_ts = session_start
        day_count = 0
        for _ in range(num_stages):
            stage_type = data[idx]
            stage_minutes = data[idx + 1]
            idx += 2
            if stage_minutes == 0:
                continue
            stage_name = stage_names.get(stage_type, f"unknown_{stage_type}")
            stage_end = stage_ts + timedelta(minutes=stage_minutes)
            records.append({
                "day": stage_ts.date(),
                "stage": stage_name,
                "start_ts": stage_ts,
                "end_ts": stage_end,
                "duration_minutes": stage_minutes,
            })
            stage_ts = stage_end
            day_count += 1

        log.info(f"  Sleep {target_date}: {day_count} stages")

    return records


async def fetch_sleep_history(client: _Client) -> list[dict]:
    """Fetch sleep data via CMD_BIG_DATA_V2 (type 0x27)."""
    data = await big_data_request(client, 0x27)
    if data is None:
        return []
    return _parse_sleep_data(data)
