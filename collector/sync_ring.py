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

import psycopg2
from psycopg2.extras import RealDictCursor
from bleak import BleakScanner
from colmi_r02_client.client import Client
from colmi_r02_client import hr as hr_mod
from colmi_r02_client import steps as steps_mod
from colmi_r02_client import packet
from dotenv import load_dotenv

load_dotenv()

LOG_DIR = Path("/home/sz/Code/smart-ring/collector")
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
                    "ts": datetime.fromtimestamp(ts, tz=timezone.utc),
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
                        ON CONFLICT DO NOTHING
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
                    ON CONFLICT DO NOTHING
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
                    ON CONFLICT DO NOTHING
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
                    INSERT INTO raw_steps (ts, steps, source)
                    VALUES (%s, %s, 'ring')
                    ON CONFLICT DO NOTHING
                """, (r.get("ts", datetime.now(tz=timezone.utc)), r.get("steps", 0)))
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
                    ON CONFLICT DO NOTHING
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
                ON CONFLICT DO NOTHING
            """, (ts, temp_c))
            return cur.rowcount


async def sync_ring(address: str) -> SyncResult:
    """Main async sync routine."""
    result = SyncResult()
    total_records = 0

    async with Client(address) as client:
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
            result.battery_pct = battery.chargePercent
            log.info(f"Battery: {result.battery_pct}%")
        except Exception as e:
            log.warning(f"Battery read failed: {e}")

        # 2. Sync time
        try:
            await client.set_time(datetime.now(timezone.utc))
            log.info("Time synced")
        except Exception as e:
            log.warning(f"Time sync failed: {e}")

        # 3. Sync heart rate (last 7 days)
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=7)
        log.info(f"Syncing data {start.date()} → {end.date()}")

        try:
            full_data = await client.get_full_data(start, end)
            hr_records = []
            for day_log in full_data.heart_rates:
                if isinstance(day_log, hr_mod.HeartRateLog):
                    for entry in day_log.heart_rates:
                        hr_records.append({"ts": entry.timestamp, "bpm": entry.heart_rate})
            count = upsert_heart_rate(hr_records)
            total_records += count
            log.info(f"Heart rate: {count} new records ({len(hr_records)} total)")
        except Exception as e:
            log.error(f"Heart rate sync failed: {e}")

        # 4. Sync steps
        try:
            step_records = []
            current_day = datetime.now(timezone.utc)
            for d_offset in range(7):
                target = current_day - timedelta(days=d_offset)
                steps_data = await client.get_steps(target)
                if isinstance(steps_data, list):
                    for s in steps_data:
                        step_records.append({"ts": target, "steps": s.steps})
                elif isinstance(steps_data, steps_mod.SportDetail):
                    step_records.append({"ts": target, "steps": steps_data.steps})
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

    result.records_synced = total_records
    log_ring_status(result.battery_pct, result.fw_version)
    log.info(f"Sync complete: {total_records} total new records")
    return result


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

    address = os.environ.get("RING_ADDRESS")
    if not address:
        log.info("No RING_ADDRESS set. Scanning...")
        address = await scan_ring(RING_NAME_FILTER)
        if not address:
            log.error("No ring found. Run 'collector scan' to find, then set RING_ADDRESS")
            sys.exit(1)

    sync_id = log_sync_start()
    try:
        result = await sync_ring(address)
        log_sync_complete(sync_id, result)
        if result.error:
            sys.exit(1)
    except Exception as e:
        log.exception("Sync failed")
        log_sync_complete(sync_id, SyncResult(error=str(e)))
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())