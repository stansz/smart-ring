"""Steps parser + upsert.

The ring's SportDetail.time_index is a 15-MINUTE SLOT from local midnight
(NOT the hour of the day). So time_index=28 = 7:00 AM, time_index=68 = 5:00 PM,
etc. Each day has slots 0..95. The ring stores time in local time (we set
it with datetime.now() which is naive local). Build timestamps from local
midnight + time_index * 15 minutes, then convert to UTC.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from colmi_r02_client import steps as steps_mod
from colmi_r02_client.client import Client as _Client

log = logging.getLogger(__name__)


async def fetch_steps(client: _Client, days: int = 7) -> list[dict]:
    """Fetch last `days` days of 15-min step slots. Returns dicts ready to upsert."""
    step_records = []
    local_now = datetime.now()
    for d_offset in range(days):
        local_target = local_now.replace(
            hour=0, minute=0, second=0, microsecond=0
        ) - timedelta(days=d_offset)
        steps_data = await client.get_steps(local_target)
        if isinstance(steps_data, list):
            for s in steps_data:
                local_ts = local_target + timedelta(minutes=s.time_index * 15)
                ts = local_ts.astimezone()
                step_records.append({
                    "ts": ts, "steps": s.steps,
                    "calories": s.calories, "distance": s.distance,
                })
        elif isinstance(steps_data, steps_mod.SportDetail):
            local_ts = local_target + timedelta(minutes=steps_data.time_index * 15)
            ts = local_ts.astimezone()
            step_records.append({
                "ts": ts, "steps": steps_data.steps,
                "calories": steps_data.calories,
                "distance": steps_data.distance,
            })
    return step_records
