#!/usr/bin/env python3
"""
Robust wrapper around the colmi_r02_client library.

The upstream `colmi_r02_client.Client` does not pass a timeout to
`BleakClient`, so service discovery on flaky R09 rings can hang indefinitely.
This wrapper:

  - Passes an explicit timeout to `BleakClient`.
  - Tries ServiceChanged-aware service discovery (re-fetch on service change).
  - Exposes the same surface used by the collector (`send_packet`,
    `set_time`, `get_battery`, `get_device_info`, `raw`, `queues`)
    so it's a drop-in replacement.
"""
from __future__ import annotations

import asyncio
import logging
import struct
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from bleak import BleakClient, BleakScanner
from colmi_r02_client import (
    battery,
    blink_twice,
    date_utils,
    hr,
    hr_settings,
    packet,
    real_time,
    reboot,
    set_time,
    steps,
)
from colmi_r02_client.client import COMMAND_HANDLERS as _BASE_COMMAND_HANDLERS

logger = logging.getLogger(__name__)

UART_SERVICE_UUID = "6E40FFF0-B5A3-F393-E0A9-E50E24DCCA9E"
UART_RX_CHAR_UUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"
UART_TX_CHAR_UUID = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"

DEVICE_INFO_UUID = "0000180A-0000-1000-8000-00805F9B34FB"
DEVICE_HW_UUID = "00002A27-0000-1000-8000-00805F9B34FB"
DEVICE_FW_UUID = "00002A26-0000-1000-8000-00805F9B34FB"

# V2 big-data service (sleep, SpO2, temperature — Gadgetbridge YawellRingConstants)
BIG_DATA_SERVICE_UUID = "de5bf728-d711-4e47-af26-65e3012a5dc7"
COMMAND_CHAR_UUID   = "de5bf72a-d711-4e47-af26-65e3012a5dc7"
NOTIFY_V2_CHAR_UUID = "de5bf729-d711-4e47-af26-65e3012a5dc7"


def _empty_parse(_packet: bytearray) -> None:
    return None


def _pass_through(packet: bytearray) -> bytearray:
    """Return the raw packet — caller parses the bytes."""
    return packet


COMMAND_HANDLERS: dict[int, Callable[[bytearray], Any]] = dict(_BASE_COMMAND_HANDLERS)

# Register commands that the colmi_r02_client library doesn't know about
# but that the R09 firmware supports (documented in Gadgetbridge).
# Also override the library's empty_parse for CMD_SET_TIME (0x01) so the
# ring's capability response lands in the queue — the library discards it.
COMMAND_HANDLERS[0x01] = _pass_through   # CMD_SET_TIME (override empty_parse)
COMMAND_HANDLERS[0x21] = _pass_through   # CMD_GOALS
COMMAND_HANDLERS[0x37] = _pass_through   # CMD_SYNC_STRESS
COMMAND_HANDLERS[0x39] = _pass_through   # CMD_SYNC_HRV


# ---------------------------------------------------------------------------
# R09 BLE state management utilities
#
# The R09 firmware (3.10.21) has a known bug: after a BLE disconnect, it
# often refuses new connections. BlueZ holds stale GATT/service cache that
# prevents bleak from reconnecting. The workaround (confirmed by the
# patmorli/colmi-r09-smart-ring fork) is to `bluetoothctl remove` the
# device (clearing all cached state) and re-pair before each new connection.
# ---------------------------------------------------------------------------

def forget_ring(address: str) -> None:
    """Disconnect, then remove the ring from BlueZ's known-device cache.

    This clears ALL cached state: GATT services, pairing/bonding, connection
    history. Disconnect first ensures BlueZ releases any lingering GATT link
    before we clear the bond. The R09 requires this to accept a new connection.
    """
    try:
        subprocess.run(
            ["bluetoothctl", "disconnect", address],
            capture_output=True, timeout=10,
        )
    except Exception:
        pass  # ring may already be disconnected
    try:
        subprocess.run(
            ["bluetoothctl", "remove", address],
            capture_output=True, timeout=10,
        )
        logger.info(f"Forgot ring {address} from BlueZ")
    except Exception as e:
        logger.warning(f"forget_ring failed (non-fatal): {e}")


def disconnect_ring(address: str) -> None:
    """Disconnect the ring from BlueZ (release GATT link)."""
    try:
        subprocess.run(
            ["bluetoothctl", "disconnect", address],
            capture_output=True, timeout=10,
        )
        logger.info(f"Disconnected ring {address} from BlueZ")
    except Exception as e:
        logger.warning(f"disconnect_ring failed (non-fatal): {e}")


def pair_ring(address: str, timeout: float = 30.0) -> bool:
    """Pair the ring via bluetoothctl. Ring MUST be advertising.

    Returns True on success, False on any failure.
    """
    try:
        result = subprocess.run(
            ["bluetoothctl", "pair", address],
            capture_output=True, text=True, timeout=timeout,
        )
        success = "Pairing successful" in (result.stdout or "")
        if success:
            logger.info(f"Paired ring {address}")
            # bluetoothctl holds the GATT link after pairing —
            # disconnect immediately so bleak can own it.
            disconnect_ring(address)
        else:
            logger.warning(f"Pairing failed: {result.stdout} {result.stderr}")
        return success
    except subprocess.TimeoutExpired:
        logger.warning(f"Pairing timed out after {timeout}s")
        return False
    except Exception as e:
        logger.warning(f"pair_ring failed: {e}")
        return False


async def scan_for_address(address: str, timeout: float = 15.0) -> bool:
    """Quick scan to verify the ring is advertising. Returns True if found."""
    logger.info(f"Scanning {timeout}s for {address}...")
    devices = await BleakScanner.discover(timeout=timeout, return_adv=True)
    found = address.lower() in (a.lower() for a in devices)
    if found:
        logger.info(f"Ring {address} is advertising")
    else:
        logger.warning(f"Ring {address} not found in scan")
    return found


async def forget_and_repair(address: str, timeout: float = 30.0) -> bool:
    """Forget the ring from BlueZ, re-discover via scan, then re-pair.

    This is the full R09 reconnect-bug workaround. After `remove`, BlueZ
    doesn't know about the device — we must scan to re-discover before
    pairing. Returns True if pairing succeeded.
    """
    forget_ring(address)
    # Quick scan so BlueZ re-discovers the device after forget
    await scan_for_address(address, timeout=5.0)
    return pair_ring(address, timeout=timeout)


class Client:
    """A slight superset of colmi_r02_client.client.Client with explicit timeout."""

    def __init__(
        self,
        address: str,
        record_to: Optional[Path] = None,
        timeout: float = 30.0,
    ) -> None:
        self.address = address
        self.bleak_client = BleakClient(address, timeout=timeout)
        self.queues: dict[int, asyncio.Queue] = {
            cmd: asyncio.Queue() for cmd in COMMAND_HANDLERS
        }
        # Cmd 115 (Device Notify) — the ring pushes async notifications
        # (temperature, battery, etc.) via this command with bit 7 set.
        # Add an explicit queue so raw() can read them.
        self.queues[115] = asyncio.Queue()
        self.record_to = record_to
        self.rx_char = None

        # V2 big-data service
        self.big_data_queue: asyncio.Queue = asyncio.Queue()
        self._bd_buf: Optional[bytearray] = None
        self._bd_size: int = 0
        self.cmd_char = None
        self.has_v2: bool = False

    async def __aenter__(self) -> "Client":
        logger.info(f"Connecting to {self.address}")
        await self.connect()
        logger.info("Connected!")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        logger.info("Disconnecting")
        if exc_val is not None:
            logger.error("had an error")
        await self.disconnect()

    async def connect(self) -> None:
        await self.bleak_client.connect()

        nrf_uart_service = self.bleak_client.services.get_service(UART_SERVICE_UUID)
        assert nrf_uart_service
        rx_char = nrf_uart_service.get_characteristic(UART_RX_CHAR_UUID)
        assert rx_char
        self.rx_char = rx_char

        await self.bleak_client.start_notify(UART_TX_CHAR_UUID, self._handle_tx)

        # Try to discover V2 big-data service (sleep, SpO2, temperature)
        v2_service = self.bleak_client.services.get_service(BIG_DATA_SERVICE_UUID)
        if v2_service:
            self.cmd_char = v2_service.get_characteristic(COMMAND_CHAR_UUID)
            if self.cmd_char:
                await self.bleak_client.start_notify(
                    NOTIFY_V2_CHAR_UUID, self._handle_big_data
                )
                self.has_v2 = True
                logger.info("V2 big-data service available (sleep/SpO2/temp)")
            else:
                logger.debug("V2 service found but COMMAND char missing")
        else:
            logger.info("V2 big-data service not found — sleep/SpO2/temp unavailable")

    async def disconnect(self) -> None:
        try:
            await self.bleak_client.disconnect()
        except Exception:
            pass

    def _handle_tx(self, _, packet: bytearray) -> None:
        logger.debug(f"Received packet {packet}")
        if len(packet) != 16:
            logger.debug(f"Ignoring non-16-byte packet (len={len(packet)})")
            return
        packet_type = packet[0]
        command = packet_type & 0x7F  # unmask error/ack bit
        # High bit (0x80) is "error/ack" bit — async push notification.
        # Handle known async types (device notify = temp, battery, etc.);
        # skip unknown async packets.
        if packet_type >= 127:
            if command == 115:
                logger.debug(f"Device notify received: type={packet[1]}")
            else:
                logger.debug(f"Ring pushed async packet type=0x{packet_type:02x}")
                return

        try:
            if command in COMMAND_HANDLERS:
                result = COMMAND_HANDLERS[command](packet)
                if result is not None:
                    self.queues[command].put_nowait(result)
                else:
                    logger.debug(f"No result returned from parser for {command}")
            elif command in self.queues:
                # Raw pass-through for commands not in COMMAND_HANDLERS
                # (e.g. cmd 115 device notify — placed directly in queue).
                self.queues[command].put_nowait(packet)
            else:
                logger.debug(f"Unhandled packet type {packet_type}")
        except Exception as e:
            logger.warning(f"Parser failed for type {packet_type}: {e}")

        if self.record_to is not None:
            with self.record_to.open("ab") as f:
                f.write(packet)
                f.write(b"\n")

    def _handle_big_data(self, _, data: bytearray) -> None:
        """Handle big-data responses from NOTIFY_V2 characteristic.

        Big-data (sleep, SpO2, temperature) can span multiple BLE packets.
        Header bytes [2:3] = uint16 total length.  Accumulate until complete.
        """
        logger.debug(f"Big-data chunk: {len(data)} bytes")
        if self._bd_buf is not None:
            self._bd_buf.extend(data)
            data = self._bd_buf
        if len(data) < 6:
            return
        packet_length = struct.unpack_from("<H", data, 2)[0]
        if len(data) < packet_length + 6:
            self._bd_buf = bytearray(data)
            self._bd_size = packet_length
            logger.debug(f"  awaiting more: {len(data)}/{packet_length + 6}")
            return
        self._bd_buf = None
        self._bd_size = 0
        logger.debug(f"  complete: {len(data)} bytes, data type 0x{data[1]:02x}")
        self.big_data_queue.put_nowait(bytearray(data))

    async def send_packet(self, packet: bytearray) -> None:
        logger.debug(f"Sending packet: {packet}")
        await self.bleak_client.write_gatt_char(self.rx_char, packet, response=False)

    async def send_command(self, packet: bytearray) -> None:
        """Write raw bytes to the V2 COMMAND characteristic (no 16-byte framing)."""
        if not self.cmd_char:
            raise RuntimeError("V2 command characteristic not available")
        logger.debug(f"Sending big-data command: {packet.hex()}")
        await self.bleak_client.write_gatt_char(self.cmd_char, packet, response=False)

    async def get_battery(self) -> battery.BatteryInfo:
        await self.send_packet(battery.BATTERY_PACKET)
        result = await self.queues[battery.CMD_BATTERY].get()
        assert isinstance(result, battery.BatteryInfo)
        return result

    async def _poll_real_time_reading(
        self, reading_type: real_time.RealTimeReading
    ) -> Optional[list[int]]:
        start_packet = real_time.get_start_packet(reading_type)
        stop_packet = real_time.get_stop_packet(reading_type)

        await self.send_packet(start_packet)

        valid_readings: list[int] = []
        error = False
        tries = 0
        while len(valid_readings) < 6 and tries < 20:
            try:
                data: real_time.Reading | real_time.ReadingError = (
                    await asyncio.wait_for(
                        self.queues[real_time.CMD_START_REAL_TIME].get(),
                        timeout=2,
                    )
                )
                if isinstance(data, real_time.ReadingError):
                    error = True
                    break
                if data.value != 0:
                    valid_readings.append(data.value)
            except TimeoutError:
                tries += 1

        await self.send_packet(stop_packet)
        if error:
            return None
        return valid_readings

    async def get_realtime_reading(
        self, reading_type: real_time.RealTimeReading
    ) -> Optional[list[int]]:
        return await self._poll_real_time_reading(reading_type)

    async def set_time(self, ts: datetime) -> None:
        logger.warning("set_time() is deprecated — use set_time_local() instead. "
                       "The library's set_time_packet sends UTC BCD bytes but "
                       "the R09 firmware reads them as local wall-clock values.")
        await self.send_packet(set_time.set_time_packet(ts))

    async def set_time_local(self, ts: datetime) -> None:
        """Set ring time using LOCAL hour/minute/second components.

        The upstream ``set_time_packet`` always converts to UTC before
        encoding, but the R09 firmware reads the BCD bytes as local
        wall-clock values. Sending UTC components therefore shifts the
        ring's "midnight" by the host's UTC offset, which accumulates
        drift across syncs. This bypasses the UTC conversion and sends
        the host's local time directly.

        Matches Gadgetbridge's ``ColmiR0xDeviceSupport.setDateTime()``
        byte-for-byte: 6 BCD-encoded data bytes, no language flag.
        """
        local = ts.replace(tzinfo=None) if ts.tzinfo is None else ts.astimezone().replace(tzinfo=None)
        data = bytearray(6)
        data[0] = set_time.byte_to_bcd(local.year % 2000)
        data[1] = set_time.byte_to_bcd(local.month)
        data[2] = set_time.byte_to_bcd(local.day)
        data[3] = set_time.byte_to_bcd(local.hour)
        data[4] = set_time.byte_to_bcd(local.minute)
        data[5] = set_time.byte_to_bcd(local.second)
        await self.send_packet(packet.make_packet(set_time.CMD_SET_TIME, data))

    async def blink_twice(self) -> None:
        await self.send_packet(blink_twice.BLINK_TWICE_PACKET)

    async def get_device_info(self) -> dict[str, str]:
        client = self.bleak_client
        data: dict[str, Any] = {}
        device_info_service = client.services.get_service(DEVICE_INFO_UUID)
        assert device_info_service

        hw_info_char = device_info_service.get_characteristic(DEVICE_HW_UUID)
        assert hw_info_char
        hw_version = await client.read_gatt_char(hw_info_char)
        data["hw_version"] = hw_version.decode("utf-8")

        fw_info_char = device_info_service.get_characteristic(DEVICE_FW_UUID)
        assert fw_info_char
        fw_version = await client.read_gatt_char(fw_info_char)
        data["fw_version"] = fw_version.decode("utf-8")

        return data

    async def get_heart_rate_log(self, target: Optional[datetime] = None):
        if target is None:
            target = date_utils.start_of_day(date_utils.now())
        await self.send_packet(hr.read_heart_rate_packet(target))
        return await asyncio.wait_for(
            self.queues[hr.CMD_READ_HEART_RATE].get(),
            timeout=2,
        )

    async def get_heart_rate_log_settings(self):
        await self.send_packet(hr_settings.READ_HEART_RATE_LOG_SETTINGS_PACKET)
        return await asyncio.wait_for(
            self.queues[hr_settings.CMD_HEART_RATE_LOG_SETTINGS].get(),
            timeout=2,
        )

    async def set_heart_rate_log_settings(self, enabled: bool, interval: int) -> None:
        await self.send_packet(
            hr_settings.hr_log_settings_packet(
                hr_settings.HeartRateLogSettings(enabled, interval)
            )
        )
        await asyncio.wait_for(
            self.queues[hr_settings.CMD_HEART_RATE_LOG_SETTINGS].get(),
            timeout=2,
        )

    async def get_steps(self, target: datetime, today: Optional[datetime] = None):
        if today is None:
            today = datetime.now()
        # Compute days offset — both target and today should use the same
        # timezone basis. The caller passes naive local datetimes; strip
        # any tzinfo to avoid astimezone() ValueError on naive inputs.
        target = target.replace(tzinfo=None)
        today = today.replace(tzinfo=None)
        days = (today.date() - target.date()).days
        await self.send_packet(steps.read_steps_packet(days))
        return await asyncio.wait_for(
            self.queues[steps.CMD_GET_STEP_SOMEDAY].get(),
            timeout=2,
        )

    async def reboot(self) -> None:
        await self.send_packet(reboot.REBOOT_PACKET)

    async def raw(self, command: int, subdata: bytearray, replies: int = 0):
        p = packet.make_packet(command, subdata)
        await self.send_packet(p)

        results = []
        while replies > 0:
            data: bytearray = await asyncio.wait_for(
                self.queues[command].get(),
                timeout=2,
            )
            results.append(data)
            replies -= 1
        return results

    async def get_full_data(self, start: datetime, end: datetime):
        heart_rate_logs = []
        sport_detail_logs = []
        for d in date_utils.dates_between(start, end):
            heart_rate_logs.append(await self.get_heart_rate_log(d))
            sport_detail_logs.append(await self.get_steps(d))
        # Return a simple object so sync_ring.py can access .heart_rates / .sport_details
        from types import SimpleNamespace
        return SimpleNamespace(
            address=self.address,
            heart_rates=heart_rate_logs,
            sport_details=sport_detail_logs,
        )
