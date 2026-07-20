"""Heart rate parser + upsert.

Fetches HR history via cmd 21 (Gadgetbridge CMD_READ_HEART_RATE) and writes
to raw_heart_rate. The library's HeartRateLogParser is stateful and only
returns today's data, so we handle the multi-packet protocol ourselves.
"""
from __future__ import annotations

import asyncio
import logging
import struct
from datetime import datetime, timedelta

from colmi_r02_client import hr as hr_mod
from colmi_r02_client.client import Client as _Client

from ..db import make_packet, upsert_heart_rate

log = logging.getLogger(__name__)


async def fetch_hr_history(client: _Client) -> list[dict]:
    """Fetch heart rate history using the library's notification handler.
    The handler (HeartRateLogParser.parse) is stateful: it accumulates
    multi-packet responses and returns a HeartRateLog on completion.
    We give it a longer timeout (10s) and drain the queue between days
    in case the parser's state needs flushing."""
    records = []
    local_now = datetime.now()
    # range(7, -1, -1) = 7,6,5,4,3,2,1,0 — INCLUDES TODAY (was 7..1 before,
    # which silently skipped today's HR data even when present).
    for days_ago in range(7, -1, -1):
        local_midnight = (local_now.replace(hour=0, minute=0, second=0, microsecond=0)
                          - timedelta(days=days_ago)).astimezone()
        hr_request = make_packet(21, struct.pack("<L", int(local_midnight.timestamp())))
        log.info(f"HR fetch: days_ago={days_ago}, target={local_midnight.date()}, ts={int(local_midnight.timestamp())}")
        await client.send_packet(hr_request)

        # Read from the notification queue. The HR handler puts a
        # HeartRateLog in the queue when all packets for the day arrive,
        # or a NoData if the day has no data.
        try:
            result = await asyncio.wait_for(
                client.queues[21].get(),
                timeout=10.0,
            )
        except asyncio.TimeoutError:
            log.warning(f"HR timeout for {local_midnight.date()}")
            # Drain stale items that may arrive late
            while True:
                try:
                    stale = client.queues[21].get_nowait()
                    log.debug(f"  drained stale queue item: {type(stale).__name__}")
                except asyncio.QueueEmpty:
                    break
            continue

        log.info(f"HR got: {type(result).__name__} for {local_midnight.date()}")
        if isinstance(result, hr_mod.NoData):
            continue

        if isinstance(result, hr_mod.HeartRateLog):
            non_zero = sum(1 for h in result.heart_rates if h > 0)
            log.info(f"  HeartRateLog: {non_zero} non-zero entries out of {len(result.heart_rates)}")
            # The heartbeat_rates list has 288 elements (one per 5-min interval).
            # Each element is the BPM value or 0/-1 for no data.
            # Use local midnight as the base since the ring stores times in local time.
            day_count = 0
            ts = local_midnight
            five_min = timedelta(minutes=5)
            for hr_val in result.heart_rates:
                if hr_val > 0:
                    records.append({"ts": ts, "bpm": hr_val})
                    day_count += 1
                ts += five_min
            if day_count:
                log.info(f"  HR {local_midnight.date()}: {day_count} records")

    return records
