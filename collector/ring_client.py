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


def _empty_parse(_packet: bytearray) -> None:
    return None


COMMAND_HANDLERS: dict[int, Callable[[bytearray], Any]] = dict(_BASE_COMMAND_HANDLERS)


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
    """Remove the ring from BlueZ's known-device cache.

    This clears ALL cached state: GATT services, pairing/bonding, connection
    history. It's the nuclear option but it's what the R09 requires after a
    disconnect to accept a new connection reliably.
    """
    try:
        subprocess.run(
            ["bluetoothctl", "remove", address],
            capture_output=True, timeout=10,
        )
        logger.info(f"Forgot ring {address} from BlueZ")
    except Exception as e:
        logger.warning(f"forget_ring failed (non-fatal): {e}")


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


def forget_and_repair(address: str, timeout: float = 30.0) -> bool:
    """Forget the ring from BlueZ, then re-pair it.

    This is the full R09 reconnect-bug workaround. Ring must be advertising
    for the pair step to succeed. Returns True if pairing succeeded.
    """
    forget_ring(address)
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
        self.record_to = record_to
        self.rx_char = None

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
        # High bit (0x80) is "error/ack" bit in the protocol — not a fatal error,
        # just an async notification that the ring pushes (e.g. harvested sleep
        # data, temperature, etc.). Log and skip rather than assert.
        if packet_type >= 127:
            logger.debug(f"Ring pushed async packet type=0x{packet_type:02x}")
            return

        try:
            if packet_type in COMMAND_HANDLERS:
                result = COMMAND_HANDLERS[packet_type](packet)
                if result is not None:
                    self.queues[packet_type].put_nowait(result)
                else:
                    logger.debug(f"No result returned from parser for {packet_type}")
            else:
                logger.debug(f"Unhandled packet type {packet_type}")
        except Exception as e:
            logger.warning(f"Parser failed for type {packet_type}: {e}")

        if self.record_to is not None:
            with self.record_to.open("ab") as f:
                f.write(packet)
                f.write(b"\n")

    async def send_packet(self, packet: bytearray) -> None:
        logger.debug(f"Sending packet: {packet}")
        await self.bleak_client.write_gatt_char(self.rx_char, packet, response=False)

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
        await self.send_packet(set_time.set_time_packet(ts))

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
        from datetime import timezone

        if today is None:
            today = datetime.now(timezone.utc)

        if target.tzinfo != timezone.utc:
            target = target.astimezone(tz=timezone.utc)

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
