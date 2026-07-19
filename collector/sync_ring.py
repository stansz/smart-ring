#!/usr/bin/env python3
"""
Collector for Colmi R09 ring.
Uses colmi_r02_client library + bleak for async BLE.
Syncs ring data to local Postgres.
"""
import os
import sys
import asyncio
import argparse
import logging
import struct
from datetime import datetime, timezone, timedelta, date
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

import psycopg2
from psycopg2.extras import RealDictCursor
from bleak import BleakScanner, BleakError
from colmi_r02_client import hr as hr_mod
from colmi_r02_client import steps as steps_mod
from colmi_r02_client import packet
from collector.ring_client import Client  # robust wrapper with timeout
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler()],
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
    warnings: Optional[str] = None
    time_sync_acked: Optional[bool] = None
    logger_stalled: bool = False
    logger_auto_recovery: bool = False


def get_db():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def log_sync_start() -> int:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO sync_log (started_at, status) VALUES (NOW(), 'running') RETURNING id")
            return cur.fetchone()["id"]


def log_sync_complete(sync_id: int, result: SyncResult):
    # clock_drift_ms column repurposed: 1 = set_time acked by ring, 0 = no ack, NULL = unknown
    ack_flag = None
    if result.time_sync_acked is not None:
        ack_flag = 1 if result.time_sync_acked else 0
    status = "completed" if not result.error else "error"
    error_msg = result.error
    if result.warnings:
        error_msg = (result.error + "; " if result.error else "") + result.warnings
    if result.logger_auto_recovery:
        log.info("Logger auto-recovery: HR-log setting was toggled to restart ring logger")
    if result.logger_stalled and not result.logger_auto_recovery:
        log.warning("HR logger STALLED but auto-recovery was not attempted")
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE sync_log SET completed_at = NOW(), records_synced = %s,
                    battery_pct = %s, clock_drift_ms = %s, status = %s, error = %s
                WHERE id = %s
            """, (result.records_synced, result.battery_pct, ack_flag,
                  status, error_msg, sync_id))


def update_progress(sync_id: Optional[int], step: str):
    if sync_id is None:
        return
    log.info(f"Progress: {step}")
    try:
        with get_db() as conn, conn.cursor() as cur:
            cur.execute("UPDATE sync_log SET current_step = %s WHERE id = %s", (step, sync_id))
    except Exception:
        pass  # non-critical


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


async def fetch_hrv_history(client: Client) -> list[dict]:
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


# ----------------------------------------------------------------
# Big-data protocol helpers (cmd 0xBC, V2 characteristic)
#
# Sleep (type 0x27), SpO2 (type 0x2A), and temperature (types 0x23-0x2B,
# are fetched via the CMD_BIG_DATA_V2 command on the V2 characteristic.
# Responses arrive on NOTIFY_V2 and may span multiple BLE packets.
# The ring_client.Client handles concatenation; we read complete payloads
# from client.big_data_queue.
# ----------------------------------------------------------------


async def _big_data_request(client: Client, data_type: int) -> Optional[bytes]:
    """Send a CMD_BIG_DATA_V2 request and wait for the complete response.

    Drains the shared queue + resets the multi-packet accumulator before
    each request so stale responses from prior commands cannot poison
    the next read. This applies to sleep, SpO2, and temperature — they
    all share one big_data_queue and one _bd_buf.
    """
    if not client.has_v2:
        log.info("V2 not available, skipping big-data request")
        return None
    # Drain stale items from prior requests
    drained = 0
    while True:
        try:
            client.big_data_queue.get_nowait()
            drained += 1
        except asyncio.QueueEmpty:
            break
    if hasattr(client, '_bd_buf'):
        client._bd_buf = None
        client._bd_size = 0
    if drained:
        log.info(f"Big-data drain before 0x{data_type:02x}: flushed {drained} stale packet(s)")
    # Send request
    request = bytearray([0xBC, data_type, 0x01, 0x00, 0xFF, 0x00, 0xFF])
    await client.send_command(request)
    try:
        raw = bytes(await asyncio.wait_for(client.big_data_queue.get(), timeout=15.0))
        head = raw[:32].hex() if len(raw) > 0 else "<empty>"
        log.info(f"Big-data resp 0x{data_type:02x}: len={len(raw)} head={head}")
        return raw
    except asyncio.TimeoutError:
        log.warning(f"Big-data timeout for type 0x{data_type:02x} (no response in 15s)")
        return None


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
        days_ago = data[idx]; idx += 1
        day_bytes = data[idx]; idx += 1
        sleep_start_min = struct.unpack_from("<H", data, idx)[0]; idx += 2
        sleep_end_min   = struct.unpack_from("<H", data, idx)[0]; idx += 2

        target_date = (local_now - timedelta(days=days_ago)).date()
        midnight = datetime.combine(target_date, datetime.min.time()).astimezone()
        if sleep_start_min > sleep_end_min:
            session_start = midnight + timedelta(minutes=sleep_start_min - 1440)
        else:
            session_start = midnight + timedelta(minutes=sleep_start_min)
        session_end = midnight + timedelta(minutes=sleep_end_min)

        stage_ts = session_start
        for _j in range(4, day_bytes, 2):
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

        log.info(f"  Sleep {target_date}: {len([r for r in records if r['day'] == target_date])} stages")

    return records


def _parse_spo2_data(data: bytes) -> list[dict]:
    """Parse CMD_BIG_DATA_V2 SpO2 response (type 0x2A).

    Gadgetbridge: per-day blocks with daysAgo byte + 24 hours ×
    (min_byte, max_byte) pairs. Averaged to a single SpO2% per hour.
    daysAgo == 0 means today (valid data), NOT a terminator — the loop
    ends naturally when we've read all bytes indicated by the length field.
    """
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


async def fetch_sleep_history(client: Client) -> list[dict]:
    """Fetch sleep data via CMD_BIG_DATA_V2 (type 0x27)."""
    data = await _big_data_request(client, 0x27)
    if data is None:
        return []
    return _parse_sleep_data(data)


async def fetch_spo2_history(client: Client) -> list[dict]:
    """Fetch SpO2 data via CMD_BIG_DATA_V2 (type 0x2A)."""
    data = await _big_data_request(client, 0x2A)
    if data is None:
        return []
    return _parse_spo2_data(data)


async def fetch_temperature_history(client: Client) -> list[dict]:
    """Fetch temperature data via CMD_BIG_DATA_V2.

    The R09 stores up to 8 days of skin temperature across big-data
    types 0x23-0x2B (skipping 0x2A = SpO2). The slot→day mapping
    rotates daily, so query 0x22-0x2C to catch border cases and
    parse only responses whose dataId byte is 0x25 (temperature).
    """
    records = []
    TEMP_ID = 0x25
    SPO2_TYPE = 0x2A
    for data_type in range(0x22, 0x2D):
        if data_type == SPO2_TYPE:
            continue
        data = await _big_data_request(client, data_type)
        if data is None:
            continue
        if len(data) < 6 or data[1] != TEMP_ID:
            continue
        parsed = _parse_temperature_data(data)
        records.extend(parsed)
        log.debug(f"  Temp type 0x{data_type:02x}: parsed {len(parsed)} records")
    return records





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
                    INSERT INTO raw_sleep (day, stage, start_ts, end_ts, duration_minutes, source)
                    VALUES (%s, %s, %s, %s, %s, 'ring')
                    ON CONFLICT (start_ts, stage, source) DO UPDATE SET
                        end_ts = EXCLUDED.end_ts,
                        duration_minutes = EXCLUDED.duration_minutes
                """, (r["day"], r["stage"], r.get("start_ts"), r.get("end_ts"),
                      r.get("duration_minutes")))
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
                """, (r.get("ts", datetime.now()),
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


def upsert_temperature_list(records: list[dict]) -> int:
    if not records:
        return 0
    count = 0
    with get_db() as conn:
        with conn.cursor() as cur:
            for r in records:
                cur.execute("""
                    INSERT INTO raw_temperature (ts, temp_c, source)
                    VALUES (%s, %s, 'ring')
                    ON CONFLICT (ts, source) DO NOTHING
                """, (r["ts"], r["temp_c"]))
                count += cur.rowcount
    return count


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


async def _collect_data(client: Client, address: str, sync_id: Optional[int] = None) -> SyncResult:
    """All sync work after the BLE link is up. Used by sync_ring() and tests."""
    result = SyncResult()
    total_records = 0

    try:
        log.info(f"Connected to {address}")
        update_progress(sync_id, "Connected")

        # 1. Device info + battery
        try:
            update_progress(sync_id, "Reading device info...")
            info = await client.get_device_info()
            result.fw_version = info.get("fw_version")
            log.info(f"FW: {result.fw_version}")
        except Exception as e:
            log.debug(f"Device info failed: {e}")

        try:
            update_progress(sync_id, "Reading battery...")
            battery = await client.get_battery()
            result.battery_pct = battery.battery_level
            log.info(f"Battery: {result.battery_pct}%")
        except Exception as e:
            log.warning(f"Battery read failed: {e}")

        # 2. Sync time — Gadgetbridge-compatible: 2s delay + local BCD
        try:
            update_progress(sync_id, "Syncing time...")
            await asyncio.sleep(2)
            now = datetime.now()
            await client.set_time_local(now)
            log.info(f"Time synced (local BCD): {now.strftime('%Y-%m-%d %H:%M:%S')}")
            # Wait for ring to acknowledge the set_time command (cmd 0x01).
            # The ring responds with a capability packet — its arrival confirms
            # the command was received and processed. This is a direct
            # verification, unlike the old drift metric which conflated
            # sampling lag with clock error.
            try:
                await asyncio.wait_for(client.queues[1].get(), timeout=3.0)
                result.time_sync_acked = True
                log.info("Time sync acknowledged by ring")
            except asyncio.TimeoutError:
                result.time_sync_acked = False
                log.warning("Time sync: no ack from ring (3s timeout) — time may not be set")
        except Exception as e:
            log.warning(f"Time sync failed: {e}")

        # 3. Sync heart rate (last 7 days) — direct protocol handler
        # The colmi_r02_client library's HeartRateLogParser is stateful and
        # only returns results for today's data. We handle the multi-packet
        # protocol ourselves, following Gadgetbridge's ColmiR0xDeviceSupport.
        hr_records = []
        log.info("Syncing heart rate history...")
        update_progress(sync_id, "Fetching heart rate...")
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
        update_progress(sync_id, "Fetching steps...")
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

        # 5. Sync HRV (cmd 0x39, Gadgetbridge CMD_SYNC_HRV)
        hrv_records = []
        update_progress(sync_id, "Fetching HRV...")
        try:
            hrv_records = await fetch_hrv_history(client)
            count = upsert_hrv(hrv_records)
            total_records += count
            log.info(f"HRV: {count} new records")
        except Exception as e:
            log.warning(f"HRV sync failed: {e}")

        # 6. Sync sleep (cmd 0xBC + type 0x27, Gadgetbridge big-data)
        update_progress(sync_id, "Fetching sleep...")
        try:
            sleep_records = await fetch_sleep_history(client)
            count = upsert_sleep(sleep_records)
            total_records += count
            log.info(f"Sleep: {count} stage records")
        except Exception as e:
            log.warning(f"Sleep sync failed: {e}")

        # 7. SpO2 (cmd 0xBC + type 0x2A, Gadgetbridge big-data)
        update_progress(sync_id, "Fetching SpO2...")
        try:
            spo2_records = await fetch_spo2_history(client)
            count = upsert_spo2(spo2_records)
            total_records += count
            log.info(f"SpO2: {count} records")
        except Exception as e:
            log.warning(f"SpO2 sync failed: {e}")

        # 8. Temperature (cmd 0xBC + types 0x23-0x2B, skip 0x2A, Gadgetbridge big-data)
        update_progress(sync_id, "Fetching temperature...")
        try:
            temp_records = await fetch_temperature_history(client)
            count = upsert_temperature_list(temp_records)
            total_records += count
            log.info(f"Temperature: {count} new records inserted")
            today = datetime.now().date()
            yesterday = today - timedelta(days=1)
            has_today = any(r["ts"].astimezone().date() == today for r in temp_records)
            has_yesterday = any(r["ts"].astimezone().date() == yesterday for r in temp_records)
            if not has_yesterday:
                # Real anomaly: yesterday's temp should have committed by now
                result.warnings = "temp: yesterday's data still missing — ring may not have published"
                log.warning("Temp anomaly: yesterday's block absent from ring buffer")
            # Normal case (today pending, yesterday present) → silent. No log, no warning.
        except Exception as e:
            log.warning(f"Temperature sync failed: {e}")

        # 8b. Live temperature check — the ring pushes unsolicited cmd 115
        #     device-notify packets (type 5 = temperature) during active
        #     connection. Drain any that accumulated in queue[115] and save
        #     the latest fresh reading. Fills the gap while the big-data
        #     buffer recovers from a logger stall.
        # 8b. Live temperature check — the ring pushes unsolicited cmd 115
        #     device-notify packets (type 5 = temperature) during sustained
        #     connections (Gadgetbridge). During brief sync windows the queue
        #     is usually empty, but check anyway — costs nothing and captures
        #     data when the ring happens to push during our connection window.
        try:
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
                total_records += 1
                log.info(f"Temperature (live): {live_temp:.1f}C")
        except Exception as e:
            log.debug(f"Live temperature check: {e}")

        # 9. Stress history (cmd 0x37, multi-packet, 30-min intervals)
        update_progress(sync_id, "Fetching stress...")
        try:
            stress_records = await fetch_stress_history(client)
            count = upsert_stress(stress_records)
            total_records += count
            log.info(f"Stress: {count} new records")
        except Exception as e:
            log.warning(f"Stress sync failed: {e}")

        # 10. Ring goals (steps, calories, distance targets)
        update_progress(sync_id, "Fetching goals...")
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
    sync_id: Optional[int] = None,
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
        return await _collect_data(client, address, sync_id=sync_id)
    finally:
        try:
            await client.__aexit__(None, None, None)
        except Exception:
            pass
        # R09 reconnect bug: forget after disconnect so the next sync can connect
        if forget_repair:
            from collector.ring_client import forget_ring
            forget_ring(address)


async def main():
    parser = argparse.ArgumentParser(description="Sync Colmi R09 ring data to Postgres")
    parser.add_argument("command", nargs="?", default="sync", choices=["sync", "scan"],
                        help="sync (default) or scan")
    parser.add_argument("--no-retry", action="store_true",
                        help="fail fast on first connect failure (testing)")
    parser.add_argument("--attempts", type=int, default=5,
                        help="connect attempts (cron should use 12+)")
    parser.add_argument("--no-forget", action="store_true",
                        help="skip forget+re-pair before connecting (diagnostics only)")
    args = parser.parse_args()

    if args.command == "scan":
        address = await scan_ring(RING_NAME_FILTER)
        if address:
            print(f"Found ring: {address}")
            print(f"Set RING_ADDRESS={address} in .env")
        else:
            print("No ring found. Try without name filter or check BLE.")
        return

    # forget+repair is the reliable default for R09; --no-forget is opt-out
    do_forget = not args.no_forget

    address = os.environ.get("RING_ADDRESS")
    if not address:
        log.info("No RING_ADDRESS set. Scanning...")
        address = await scan_ring(RING_NAME_FILTER)
        if not address:
            log.error("No ring found. Run 'python -m collector.sync_ring scan' to find, then set RING_ADDRESS")
            sys.exit(1)

    sync_id = log_sync_start()
    try:
        if args.no_retry:
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
            result = await sync_ring(address, attempts=args.attempts, forget_repair=do_forget, sync_id=sync_id)

        log_sync_complete(sync_id, result)
        if result.error:
            sys.exit(1)
    except Exception as e:
        log.exception("Sync failed")
        log_sync_complete(sync_id, SyncResult(error=str(e)))
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())