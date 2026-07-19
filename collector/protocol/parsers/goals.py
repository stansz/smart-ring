"""Goals parser + upsert.

CMD_GOALS (0x21) with PREF_READ (0x01). Gadgetbridge goalsSettings format:
  steps   = uint24(value[2], value[3], value[4])
  calories= uint24(value[5], value[6], value[7])
  distance= uint24(value[8], value[9], value[10])
  sport   = uint16(value[11], value[12])  — minutes
  sleep   = uint16(value[13], value[14])  — minutes
"""
from __future__ import annotations

import asyncio
import logging

from colmi_r02_client.client import Client as _Client

from ..db import make_packet

log = logging.getLogger(__name__)


async def fetch_goals(client: _Client) -> dict | None:
    pkt = make_packet(0x21, bytes([1]))  # PREF_READ
    await client.send_packet(pkt)
    try:
        result = await asyncio.wait_for(
            client.queues[0x21].get(), timeout=5.0,
        )
    except asyncio.TimeoutError:
        return None
    if not isinstance(result, (bytearray, bytes)) or len(result) < 15:
        return None
    steps = (result[4] << 16) | (result[3] << 8) | result[2]
    cal = (result[7] << 16) | (result[6] << 8) | result[5]
    dist = (result[10] << 16) | (result[9] << 8) | result[8]
    sport = (result[12] << 8) | result[11]
    sleep = (result[14] << 8) | result[13]
    return {
        "steps_goal": steps,
        "calories_goal": cal,
        "distance_m_goal": dist,
        "sport_min_goal": sport,
        "sleep_min_goal": sleep,
    }
