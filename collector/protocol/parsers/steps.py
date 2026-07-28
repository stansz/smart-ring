"""Steps parser + upsert.

The ring's SportDetail.time_index is a 15-MINUTE SLOT from local midnight
(NOT the hour of the day). So time_index=28 = 7:00 AM, time_index=68 = 5:00 PM,
etc. Each day has slots 0..95. The ring stores time in local time (we set
it with datetime.now() which is naive local). Build timestamps from local
midnight + time_index * 15 minutes, then convert to UTC.

The R09 steps response (cmd 0x43) is MULTI-PACKET: a header packet followed
by one packet per non-empty slot, terminated when packet[5] == packet[6] - 1.
The library's SportDetailParser is stateful — it accumulates packets and
returns the full list on the final one. We MUST drain the queue and reset
the parser before each per-day request, or stale items from a prior day/sync
get consumed by .get() and silently no-op the fetch. Same class of bug as
the V2 big-data path (see docs/RING_BEHAVIOR.md "Shared queue" note).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from colmi_r02_client import steps as steps_mod
from colmi_r02_client.client import Client as _Client, COMMAND_HANDLERS

log = logging.getLogger(__name__)


def _drain_steps_queue(client: _Client) -> int:
    """Drop stale packets sitting in the steps queue. Returns count drained."""
    drained = 0
    while True:
        try:
            client.queues[steps_mod.CMD_GET_STEP_SOMEDAY].get_nowait()
            drained += 1
        except asyncio.QueueEmpty:
            break
    return drained


def _reset_steps_parser() -> None:
    """Reset the shared SportDetailParser in case a prior sequence was truncated.

    COMMAND_HANDLERS[67] is a *bound method* on a singleton parser instance.
    If a prior day's response was interrupted (timeout / partial read), the
    parser stays mid-sequence and the next day's packets get appended to the
    stale `details` list. Calling reset() restores clean state.
    """
    handler = COMMAND_HANDLERS.get(steps_mod.CMD_GET_STEP_SOMEDAY)
    parser = getattr(handler, "__self__", None)
    if parser is not None and hasattr(parser, "reset"):
        parser.reset()


async def fetch_steps(client: _Client, days: int = 7) -> list[dict]:
    """Fetch last `days` days of 15-min step slots. Returns dicts ready to upsert."""
    step_records = []
    local_now = datetime.now()
    for d_offset in range(days):
        local_target = local_now.replace(
            hour=0, minute=0, second=0, microsecond=0
        ) - timedelta(days=d_offset)

        # Drain stale queue items + reset parser state before each per-day
        # request. Without this, a leftover NoData or stray slot from a
        # prior day poisons the .get() and silently no-ops the fetch.
        drained = _drain_steps_queue(client)
        if drained:
            log.info(f"  steps day=-{d_offset}: drained {drained} stale queue item(s)")
        _reset_steps_parser()

        steps_data = await client.get_steps(local_target)

        slots_for_day: list[dict] = []
        time_indexes: list[int] = []
        if isinstance(steps_data, list):
            for s in steps_data:
                local_ts = local_target + timedelta(minutes=s.time_index * 15)
                ts = local_ts.astimezone()
                slots_for_day.append({
                    "ts": ts, "steps": s.steps,
                    "calories": s.calories, "distance": s.distance,
                })
                time_indexes.append(s.time_index)
        elif isinstance(steps_data, steps_mod.SportDetail):
            local_ts = local_target + timedelta(minutes=steps_data.time_index * 15)
            ts = local_ts.astimezone()
            slots_for_day.append({
                "ts": ts, "steps": steps_data.steps,
                "calories": steps_data.calories,
                "distance": steps_data.distance,
            })
            time_indexes.append(steps_data.time_index)
        elif steps_data is not None:
            log.warning(
                f"  steps day=-{d_offset} ({local_target.date()}): "
                f"unexpected response type {type(steps_data).__name__} ({steps_data!r})"
            )

        if slots_for_day:
            log.info(
                f"  steps day=-{d_offset} ({local_target.date()}): "
                f"{len(slots_for_day)} slot(s), time_indexes={time_indexes}"
            )
        else:
            log.info(f"  steps day=-{d_offset} ({local_target.date()}): no slots")
        step_records.extend(slots_for_day)
    return step_records
