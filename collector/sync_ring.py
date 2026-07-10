#!/usr/bin/env python3
"""
Collector for Colmi R09 ring.
Uses colmi_r02_client library + bleak for async BLE.
Syncs ring data to local Postgres.
"""
import os
import sys
import asyncio
import logging
import struct
from datetime import datetime, timezone, timedelta, date
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from pathlib import Path

# Allow running sync_ring.py directly: add the project root to sys.path
# so `from collector import ...` works.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import psycopg2
from psycopg2.extras import RealDictCursor
from bleak import BleakScanner, BleakError
from colmi_r02_client import hr as hr_mod
from colmi_r02_client import steps as steps_mod
from colmi_r02_client import packet
from collector.ring_client import Client  # robust wrapper with timeout
from dotenv import load_dotenv

load_dotenv()

LOG_DIR = Path(__file__).resolve().parent
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "collector.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://smart_ring:changeme@localhost:5432/smart_ring")
RING_NAME_FILTER = os.getenv("RING_NAME_FILTER", "R09")  # BLE name filter

UART_SERVICE_UUID = "6E40FFF0-B5A3-F393-E0A9-E50E24DCCA9E"


@dataclass
class SyncResult:
    records_synced: int = 0
    battery_pct: Optional[int] = None
    fw_version: Optional[str] = None
    error: Optional[str] = None


def get_db():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def log_sync_start() -> int:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO sync_log (started_at, status) VALUES (NOW(), 'running') RETURNING id")
            return cur.fetchone()["id"]


def log_sync_complete(sync_id: int, result: SyncResult):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE sync_log SET completed_at = NOW(), records_synced = %s,
                    battery_pct = %s, status = %s, error = %s
                WHERE id = %s
            """, (result.records_synced, result.battery_pct,
                  "completed" if not result.error else "error", result.error, sync_id))


def log_ring_status(battery_pct: Optional[int], fw_version: Optional[str]):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO ring_status (ts, battery_pct, firmware_version)
                VALUES (NOW(), %s, %s)
            """, (battery_pct, fw_version))


def make_packet(command_id: int, subdata: bytes = b"") -> bytearray:
    """Build a 16-byte BLE packet with CRC."""
    assert len(subdata) <= 14
    data = bytearray(16)
    data[0] = command_id
    data[1:1 + len(subdata)] = subdata
    checksum = (command_id + sum(subdata)) & 0xFF
    data[-1] = checksum
    return data


async def scan_ring(name_filter: str = "") -> Optional[str]:
    """Scan for ring and return BLE address."""
    log.info(f"Scanning for ring (filter: '{name_filter}')...")
    devices = await BleakScanner.discover(timeout=10.0, return_adv=True)

    for addr, (device, adv) in devices.items():
        name = device.name or adv.local_name or ""
        if name_filter.lower() in name.lower():
            log.info(f"Found ring: {name} ({addr})")
            return addr

    if devices and not name_filter:
        for addr, (device, adv) in devices.items():
            name = device.name or adv.local_name or ""
            if name:
                log.info(f"Device: {name} ({addr})")

    return None


async def connect_with_retry(
    address: str,
    *,
    attempts: int = 5,
    initial_backoff: float = 2.0,
    connect_timeout: float = 30.0,
    wake_ping: bool = False,
    forget_repair: bool = False,
) -> "Client":
    """Connect to the ring, retrying on failure.

    R09 firmware 3.10.21 has two known issues:
    1. **Aggressive sleep** — stops advertising ~30s after disconnect.
       Handled by retry + exponential backoff.
    2. **Reconnect bug** — after a disconnect, BlueZ holds stale GATT state
       that prevents new connections. Worked around by `bluetoothctl remove`
       + `bluetoothctl pair` (forget + re-pair).

    Parameters:
        forget_repair: If True, run forget+re-pair BEFORE the first connect
            attempt. Use this when the ring was previously connected and
            disconnected (the R09 reconnect bug will block normal connects).
            If the re-pair fails (ring not advertising), falls through to
            plain retry — the ring may wake up during the backoff window.

        wake_ping: If True, run a short BLE scan FIRST (before forget+repair)
            to nudge the ring's radio awake. Also runs a scan on the last
            retry attempt as a last-ditch wake-up.

    Returns a connected Client. Caller MUST call ``await client.__aexit__(...)``
    when done.
    """
    from collector.ring_client import forget_and_repair, forget_ring

    # Wake-ping FIRST: scan before anything else to nudge the ring awake.
    # The scan MUST happen before forget+repair because the ring needs to
    # be advertising for pair_ring to succeed.
    if wake_ping:
        log.info("Wake-ping: scanning to nudge ring awake...")
        await BleakScanner.discover(timeout=5.0, return_adv=True)

    # R09 reconnect-bug workaround: clear stale BlueZ state before connecting
    if forget_repair:
        log.info("Forget+repair: clearing stale BlueZ state...")
        paired = await forget_and_repair(address)
        if paired:
            log.info("Re-paired successfully, attempting connect...")
        else:
            log.warning("Re-pair failed (ring may be asleep), trying plain connect...")

    last_exc: Optional[BaseException] = None
    for i in range(attempts):
        if wake_ping and i == attempts - 1:
            # Last-ditch: run a scan loop to coax the radio awake.
            log.info("Final attempt: running wake-ping scan (10s)...")
            await BleakScanner.discover(timeout=10.0, return_adv=True)

        try:
            client = Client(address, timeout=connect_timeout)
            await client.__aenter__()
            return client
        except (BleakError, OSError, asyncio.TimeoutError, EOFError, ConnectionError) as e:
            last_exc = e
            if i < attempts - 1:
                wait = initial_backoff * (2 ** i)
                err_msg = str(e) or type(e).__name__
                log.info(
                    f"Connect attempt {i + 1}/{attempts} failed ({type(e).__name__}: "
                    f"{err_msg}). Retrying in {wait:.0f}s..."
                )
                await asyncio.sleep(wait)
            else:
                log.warning(f"Connect attempt {i + 1}/{attempts} failed: {e!r}")

    raise RuntimeError(
        f"Failed to connect to {address} after {attempts} attempts: {last_exc!r}"
    )


async def fetch_hrv_raw(client: Client) -> List[Dict[str, Any]]:
    """Fetch stored HRV data using cmd 57 (multi-packet)."""
    records = []
    try:
        index = 0
        total_size = None
        hrv_bytes = bytearray()

        while True:
            pkt = make_packet(57, struct.pack("<B", index))
            responses = await client.raw(57, pkt[1:15], replies=1)
            if not responses:
                break

            resp = responses[0]
            resp_index = resp[1]

            if resp_index == 0:
                total_size = resp[2]
                log.info(f"HRV: {total_size} records available")
            elif resp_index == 1:
                start_offset = resp[2]
                hrv_bytes.extend(resp[3:13])
            else:
                hrv_bytes.extend(resp[2:15])

            if total_size and resp_index >= total_size:
                break

            index += 1
            if index > 100:
                break

        if hrv_bytes:
            records = _parse_hrv_data(bytes(hrv_bytes))
            log.info(f"HRV: parsed {len(records)} records")

    except Exception as e:
        log.warning(f"HRV fetch failed: {e}")

    return records


def _parse_hrv_data(data: bytes) -> List[Dict[str, Any]]:
    """Parse raw HRV bytes.
    Format appears to be: each record is 6 bytes (4-byte timestamp + 2-byte HRV value).
    May vary by firmware version — test when ring arrives.
    """
    records = []
    record_size = 6
    for i in range(0, len(data) - record_size + 1, record_size):
        try:
            ts, hrv_val = struct.unpack_from("<IH", data, i)
            if ts > 0:
                records.append({
                    "ts": datetime.fromtimestamp(ts),
                    "hrv_value": hrv_val,
                    "hrv_type": "composite",
                })
        except struct.error:
            break
    return records


async def fetch_sleep_data(client: Client) -> List[Dict[str, Any]]:
    """Fetch stored sleep data using cmd 68."""
    records = []
    for day_offset in range(0, 7):  # Last 7 days
        try:
            subdata = struct.pack("<BBBB7x", day_offset, 15, 0, 95)
            pkt = make_packet(68, subdata)
            responses = await client.raw(68, pkt[1:15], replies=1)
            if not responses:
                continue

            resp = responses[0]
            year = resp[1] + 2000
            month = resp[2]
            day = resp[3]
            sleep_qualities = resp[5]

            sleep_stages = _decode_sleep_qualities(sleep_qualities)
            records.extend([{
                "day": date(year, month, day),
                "stage": stage,
                "sleep_qualities_byte": sleep_qualities,
            } for stage in sleep_stages])

        except Exception as e:
            log.debug(f"Sleep day {day_offset} failed: {e}")
            continue

    log.info(f"Sleep: {len(records)} stage records")
    return records


def _decode_sleep_qualities(byte_val: int) -> List[str]:
    """Decode sleep quality byte into stages.
    Bit 0-1: light sleep, bit 2: deep, bit 3: REM, bit 4: awake.
    Exact mapping TBD when ring arrives."""
    stages = []
    if byte_val & 0x01:
        stages.append("light")
    if byte_val & 0x02:
        stages.append("light")
    if byte_val & 0x04:
        stages.append("deep")
    if byte_val & 0x08:
        stages.append("rem")
    if byte_val & 0x10:
        stages.append("wake")
    return stages if stages else ["unknown"]


async def fetch_spo2_data(client: Client) -> List[Dict[str, Any]]:
    """Fetch SpO2 data using Data Request (cmd 105, type=3)."""
    records = []
    try:
        # Start SpO2 measurement
        subdata = struct.pack("<BB", 3, 1)  # DataType=3 (BloodOxygen), Action=1 (Start)
        pkt = make_packet(105, subdata)
        responses = await client.raw(105, pkt[1:15], replies=1)

        if responses:
            resp = responses[0]
            if len(resp) >= 4:
                spo2 = resp[3] if resp[3] < 127 else None
                if spo2 is not None:
                    records.append({
                        "ts": datetime.now(tz=timezone.utc),
                        "spo2_pct": spo2,
                    })
                    log.info(f"SpO2: {spo2}%")
    except Exception as e:
        log.debug(f"SpO2 fetch failed: {e}")

    return records


async def listen_temperature(client: Client, timeout: float = 5.0) -> Optional[float]:
    """Listen for temperature notify (cmd 115, NotifyType=5).
    The ring pushes temperature periodically — we listen for a short window.
    """
    # Temperature is pushed by the ring via cmd 115 NotifyType=5.
    # We can't pull it — just listen briefly.
    try:
        # Try reading any pending notifications
        responses = await client.raw(115, b"\x00" * 14, replies=1)
        if responses:
            resp = responses[0]
            if resp[1] == 5:  # Temperature notify type
                temp_raw = struct.unpack_from("<H", resp, 2)[0]
                temp_c = temp_raw / 100.0 if temp_raw > 0 else None
                if temp_c and 30 < temp_c < 45:
                    log.info(f"Temperature: {temp_c:.1f}°C")
                    return temp_c
    except Exception as e:
        log.debug(f"Temperature listen failed: {e}")

    return None


def upsert_heart_rate(records: List[Dict]) -> int:
    if not records:
        return 0
    count = 0
    with get_db() as conn:
        with conn.cursor() as cur:
            for r in records:
                ts = r.get("ts")
                bpm = r.get("bpm")
                if ts and bpm and isinstance(bpm, int) and 30 < bpm < 250:
                    cur.execute("""
                        INSERT INTO raw_heart_rate (ts, bpm, source)
                        VALUES (%s, %s, 'ring')
                        ON CONFLICT (ts, source) DO NOTHING
                    """, (ts, bpm))
                    count += cur.rowcount
    return count


def upsert_hrv(records: List[Dict]) -> int:
    if not records:
        return 0
    count = 0
    with get_db() as conn:
        with conn.cursor() as cur:
            for r in records:
                cur.execute("""
                    INSERT INTO raw_hrv (ts, hrv_value, hrv_type, source)
                    VALUES (%s, %s, %s, 'ring')
                    ON CONFLICT (ts, hrv_type, source) DO NOTHING
                """, (r["ts"], r["hrv_value"], r.get("hrv_type", "composite")))
                count += cur.rowcount
    return count


def upsert_sleep(records: List[Dict]) -> int:
    if not records:
        return 0
    count = 0
    with get_db() as conn:
        with conn.cursor() as cur:
            for r in records:
                cur.execute("""
                    INSERT INTO raw_sleep (day, stage, source)
                    VALUES (%s, %s, 'ring')
                    ON CONFLICT (day, stage, source) DO NOTHING
                """, (r["day"], r["stage"]))
                count += cur.rowcount
    return count


def upsert_steps(records: List[Dict]) -> int:
    if not records:
        return 0
    count = 0
    with get_db() as conn:
        with conn.cursor() as cur:
            for r in records:
                cur.execute("""
                    INSERT INTO raw_steps (ts, steps, calories, distance, source)
                    VALUES (%s, %s, %s, %s, 'ring')
                    ON CONFLICT (ts, source) DO NOTHING
                """, (r.get("ts", datetime.now(tz=timezone.utc)),
                      r.get("steps", 0),
                      r.get("calories"),
                      r.get("distance")))
                count += cur.rowcount
    return count


def upsert_spo2(records: List[Dict]) -> int:
    if not records:
        return 0
    count = 0
    with get_db() as conn:
        with conn.cursor() as cur:
            for r in records:
                cur.execute("""
                    INSERT INTO raw_spo2 (ts, spo2_pct, source)
                    VALUES (%s, %s, 'ring')
                    ON CONFLICT (ts, source) DO NOTHING
                """, (r["ts"], r["spo2_pct"]))
                count += cur.rowcount
    return count


def upsert_temperature(temp_c: float, ts: Optional[datetime] = None) -> int:
    if not temp_c:
        return 0
    ts = ts or datetime.now(tz=timezone.utc)
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO raw_temperature (ts, temp_c, source)
                VALUES (%s, %s, 'ring')
                ON CONFLICT (ts, source) DO NOTHING
            """, (ts, temp_c))
            return cur.rowcount


async def fetch_hr_history(
    client: Client, start: datetime, end: datetime
) -> list[dict]:
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
                          - timedelta(days=days_ago))
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
            ts = local_midnight
            five_min = timedelta(minutes=5)
            for hr_val in result.heart_rates:
                if hr_val > 0:
                    records.append({"ts": ts, "bpm": hr_val})
                ts += five_min

    return records


async def _read_multi_packet(
    client: Client, cmd: int, timeout: float = 10.0
) -> list[bytearray]:
    """Read all packets for a multi-packet ring response (stress, HRV, etc.).
    Each packet goes through the notification handler and ends up in
    client.queues[cmd]. We read until the expected last sub_type or timeout."""
    items: list[bytearray] = []
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            break
        try:
            item = await asyncio.wait_for(
                client.queues[cmd].get(),
                timeout=min(remaining, 2.0),
            )
        except asyncio.TimeoutError:
            break
        if not isinstance(item, (bytearray, bytes)):
            break
        items.append(bytearray(item))
        # Gadgetbridge stress: sub_type==4 is the last data packet
        if len(item) >= 2 and item[1] in (4, 0xFF):
            break
    return items


async def fetch_stress_history(client: Client) -> list[dict]:
    """Fetch stress history using cmd 0x37 (multi-packet, 30-min intervals).
    Protocol from Gadgetbridge ColmiR0xPacketHandler.historicalStress:
      - Packet sub_type 0: header, byte[2]=expected packet count
      - Packet 1: byte[2]=timestamp flag?, bytes[3-14]=12 stress values
      - Packets 2..4: bytes[2-14]=13 stress values each
      - Each value is 0-99. 0=no data. 1-29=relaxed, 30-59=normal,
        60-79=medium, 80-99=high.
    """
    await client.send_packet(make_packet(0x37, bytes(14)))
    packets = await _read_multi_packet(client, 0x37, timeout=10.0)
    if not packets:
        return []

    records = []
    local_now = datetime.now()
    local_midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
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


def upsert_stress(records: list[dict]) -> int:
    if not records:
        return 0
    count = 0
    with get_db() as conn:
        with conn.cursor() as cur:
            for r in records:
                cur.execute("""
                    INSERT INTO raw_stress (ts, stress_value, source)
                    VALUES (%s, %s, 'ring')
                    ON CONFLICT (ts, source) DO NOTHING
                """, (r["ts"], r["stress_value"]))
                count += cur.rowcount
    return count


async def fetch_goals(client: Client) -> dict | None:
    """Fetch the ring's daily goals (steps, calories, distance, sport, sleep).
    CMD_GOALS (0x21) with PREF_READ (0x01). Gadgetbridge goalsSettings format."""
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
    # Gadgetbridge layout:
    #  steps   = uint32(value[2], value[3], value[4], 0)
    #  calories= uint32(value[5], value[6], value[7], 0)
    #  distance= uint32(value[8], value[9], value[10], 0)
    #  sport   = uint16(value[11], value[12])  — minutes
    #  sleep   = uint16(value[13], value[14])  — minutes
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


def upsert_goals(goals: dict) -> int:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO ring_goals (steps_goal, calories_goal, distance_m_goal,
                                        sport_min_goal, sleep_min_goal)
                VALUES (%s, %s, %s, %s, %s)
            """, (
                goals["steps_goal"], goals["calories_goal"],
                goals["distance_m_goal"], goals["sport_min_goal"],
                goals["sleep_min_goal"],
            ))
            return cur.rowcount


async def _collect_data(client: Client, address: str) -> SyncResult:
    """All sync work after the BLE link is up. Used by sync_ring() and tests."""
    result = SyncResult()
    total_records = 0

    try:
        log.info(f"Connected to {address}")

        # 1. Device info + battery
        try:
            info = await client.get_device_info()
            result.fw_version = info.get("fw_version")
            log.info(f"FW: {result.fw_version}")
        except Exception as e:
            log.debug(f"Device info failed: {e}")

        try:
            battery = await client.get_battery()
            result.battery_pct = battery.battery_level
            log.info(f"Battery: {result.battery_pct}%")
        except Exception as e:
            log.warning(f"Battery read failed: {e}")

        # 2. Sync time (use local time — the ring stores year/month/day/hour/minute/second with no timezone)
        try:
            await client.set_time(datetime.now())
            log.info("Time synced")
        except Exception as e:
            log.warning(f"Time sync failed: {e}")

        # 3. Sync heart rate (last 7 days) — direct protocol handler
        # The colmi_r02_client library's HeartRateLogParser is stateful and
        # only returns results for today's data. We handle the multi-packet
        # protocol ourselves, following Gadgetbridge's ColmiR0xDeviceSupport.
        log.info("Syncing heart rate history...")
        try:
            hr_records = await fetch_hr_history(client, None, None)
            count = upsert_heart_rate(hr_records)
            total_records += count
            log.info(f"Heart rate: {count} new records ({len(hr_records)} total)")
        except Exception as e:
            log.error(f"Heart rate sync failed: {e}")

        # 4. Sync steps
        # The ring's SportDetail.time_index is a 15-MINUTE SLOT from local
        # midnight (NOT the hour of the day). So time_index=28 = 7:00 AM,
        # time_index=68 = 5:00 PM, etc. Each day has slots 0..95.
        # The ring stores time in local time (we set it with datetime.now()
        # which is naive local). Build timestamps from local midnight +
        # time_index * 15 minutes, then convert to UTC.
        try:
            step_records = []
            local_now = datetime.now()
            for d_offset in range(7):
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
            count = upsert_steps(step_records)
            total_records += count
            log.info(f"Steps: {count} new records")
        except Exception as e:
            log.error(f"Steps sync failed: {e}")

        # 5. Sync HRV (raw protocol, cmd 57)
        try:
            hrv_records = await fetch_hrv_raw(client)
            count = upsert_hrv(hrv_records)
            total_records += count
            if hrv_records:
                log.info(f"✓ HRV data fetched ({count} records) — check format")
        except Exception as e:
            log.warning(f"HRV sync failed (may not be supported): {e}")

        # 6. Sync sleep (raw protocol, cmd 68)
        try:
            sleep_records = await fetch_sleep_data(client)
            count = upsert_sleep(sleep_records)
            total_records += count
            log.info(f"Sleep: {count} stage records")
        except Exception as e:
            log.warning(f"Sleep sync failed (may not be supported): {e}")

        # 7. SpO2 (raw protocol)
        try:
            spo2_records = await fetch_spo2_data(client)
            count = upsert_spo2(spo2_records)
            total_records += count
        except Exception as e:
            log.debug(f"SpO2 failed: {e}")

        # 8. Temperature (listen for notify)
        try:
            temp_c = await listen_temperature(client, timeout=5.0)
            if temp_c:
                count = upsert_temperature(temp_c)
                total_records += count
                log.info(f"✓ Temperature: {temp_c:.1f}°C")
            else:
                log.info("No temperature data (ring may not have pushed it)")
        except Exception as e:
            log.debug(f"Temperature listen failed: {e}")

        # 9. Stress history (cmd 0x37, multi-packet, 30-min intervals)
        try:
            stress_records = await fetch_stress_history(client)
            count = upsert_stress(stress_records)
            total_records += count
            log.info(f"Stress: {count} new records")
        except Exception as e:
            log.warning(f"Stress sync failed: {e}")

        # 10. Ring goals (steps, calories, distance targets)
        try:
            goals = await fetch_goals(client)
            if goals:
                upsert_goals(goals)
                log.info(f"Goals: steps={goals['steps_goal']} cal={goals['calories_goal']} dist={goals['distance_m_goal']}m")
        except Exception as e:
            log.debug(f"Goals fetch failed: {e}")

    finally:
        result.records_synced = total_records
        log_ring_status(result.battery_pct, result.fw_version)
        log.info(f"Sync complete: {total_records} total new records")

    return result


async def sync_ring(
    address: str,
    *,
    attempts: int = 5,
    wake_ping: bool = True,
    forget_repair: bool = False,
) -> SyncResult:
    """Main async sync routine with retry-on-sleep + R09 reconnect-bug workaround.

    Parameters:
        forget_repair: If True, run `bluetoothctl remove` + `bluetoothctl pair`
            before connecting. Use this for manual syncs where the ring was
            previously connected and disconnected (the R09 won't accept a new
            connection without forgetting first). For cron-driven syncs, set
            to False and let connect_with_retry handle it mid-retry if needed.
    """
    client = await connect_with_retry(
        address, attempts=attempts, wake_ping=wake_ping,
        forget_repair=forget_repair,
    )
    try:
        return await _collect_data(client, address)
    finally:
        try:
            await client.__aexit__(None, None, None)
        except Exception:
            pass
        # R09 reconnect bug: forget after disconnect so the next sync can connect
        if forget_repair:
            from collector.ring_client import forget_ring
            forget_ring(address)


async def test_sync_behavior(address: str):
    """Test if syncing wipes data from the ring."""
    log.info("=== TESTING SYNC BEHAVIOR ===")
    result1 = await sync_ring(address)
    log.info(f"First sync: {result1.records_synced} records")

    result2 = await sync_ring(address)
    log.info(f"Second sync: {result2.records_synced} records")

    if result2.records_synced == 0:
        log.info("✓ CONFIRMED: Sync is read-and-clear")
    elif result2.records_synced == result1.records_synced:
        log.info("✓ CONFIRMED: Sync is read-only")
    else:
        log.info(f"? PARTIAL: {result2.records_synced} vs {result1.records_synced}")


async def main():
    if len(sys.argv) > 1 and sys.argv[1] == "scan":
        address = await scan_ring(RING_NAME_FILTER)
        if address:
            print(f"Found ring: {address}")
            print(f"Set RING_ADDRESS={address} in .env")
        else:
            print("No ring found. Try without name filter or check BLE.")
        return

    if len(sys.argv) > 1 and sys.argv[1] == "test-sync":
        address = os.environ.get("RING_ADDRESS")
        if not address:
            log.error("Set RING_ADDRESS in .env or export it")
            sys.exit(1)
        await test_sync_behavior(address)
        return

    # CLI flags:
    #   --no-retry       fail fast on first connect failure (testing)
    #   --attempts N     override default 5 retries (cron should use 12+)
    #   --forget         forget+re-pair ring before connecting (R09 workaround)
    attempts = 5
    no_retry = "--no-retry" in sys.argv
    do_forget = "--forget" in sys.argv
    if "--attempts" in sys.argv:
        idx = sys.argv.index("--attempts")
        if idx + 1 < len(sys.argv):
            attempts = int(sys.argv[idx + 1])

    address = os.environ.get("RING_ADDRESS")
    if not address:
        log.info("No RING_ADDRESS set. Scanning...")
        address = await scan_ring(RING_NAME_FILTER)
        if not address:
            log.error("No ring found. Run 'collector scan' to find, then set RING_ADDRESS")
            sys.exit(1)

    sync_id = log_sync_start()
    try:
        if no_retry:
            log.info("--no-retry: skipping connect retry loop")
            client = Client(address, timeout=30.0)
            try:
                await client.__aenter__()
                result = await _collect_data(client, address)
            finally:
                try:
                    await client.__aexit__(None, None, None)
                except Exception:
                    pass
        else:
            result = await sync_ring(address, attempts=attempts, forget_repair=do_forget)

        log_sync_complete(sync_id, result)
        if result.error:
            sys.exit(1)
    except Exception as e:
        log.exception("Sync failed")
        log_sync_complete(sync_id, SyncResult(error=str(e)))
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())