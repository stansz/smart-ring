"""Regression test for the BCD time encoding used by set_time_local.

This is the regression net for the sacred time-sync code path. The encoding
must match Gadgetbridge's ColmiR0xDeviceSupport.setDateTime() byte-for-byte:
  - Exactly 6 data bytes (no language flag)
  - Order: YY MM DD HH MM SS
  - Year is local.year % 2000 (2026 -> 0x26)
  - Each component is BCD: ((n // 10) << 4) | (n % 10)

The hand-computed expected bytes below are derived independently of
colmi_r02_client.set_time.byte_to_bcd. If both sides agree, we know:
  - The encoder is BCD (not binary)
  - The order is correct
  - The length is correct
  - The year modulo is correct

Any change to _encode_time_bcd that breaks these tests will silently break
the ring's clock at the next sync — that's why this file exists.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from collector.ring_client import _encode_time_bcd


# Hand-computed BCD reference bytes, derived directly from the encoding spec:
#   byte_n = ((value // 10) << 4) | (value % 10)
# Examples:
#   26 -> (2<<4)|6 = 0x26      7 -> (0<<4)|7 = 0x07      20 -> (2<<4)|0 = 0x20
#   14 -> (1<<4)|4 = 0x14     30 -> (3<<4)|0 = 0x30     45 -> (4<<4)|5 = 0x45


def test_encode_canonical_gadgetbridge_reference() -> None:
    """The canonical reference case — pin the exact byte sequence."""
    ts = datetime(2026, 7, 20, 14, 30, 45)
    expected = bytes([0x26, 0x07, 0x20, 0x14, 0x30, 0x45])
    assert _encode_time_bcd(ts) == expected


def test_returns_exactly_six_bytes() -> None:
    """No language flag, no padding — exactly 6 bytes per Gadgetbridge layout."""
    ts = datetime(2026, 7, 20, 14, 30, 45)
    result = _encode_time_bcd(ts)
    assert isinstance(result, bytes)
    assert len(result) == 6


@pytest.mark.parametrize(
    "year, expected_yy_byte",
    [
        (2000, 0x00),  # 2000 % 2000 = 0
        (2009, 0x09),  # 2009 % 2000 = 9
        (2026, 0x26),  # current year
        (2050, 0x50),
        (2099, 0x99),  # max representable (BCD limit, not Y2.1K)
    ],
)
def test_year_modulo_2000(year: int, expected_yy_byte: int) -> None:
    """Year wraps via % 2000. Documents the wrap, doesn't claim Y2.1K safety."""
    ts = datetime(year, 1, 1, 0, 0, 0)
    result = _encode_time_bcd(ts)
    assert result[0] == expected_yy_byte


def test_max_values_each_component() -> None:
    """Largest representable calendar value per component -> expected BCD."""
    # 2099-12-31 23:59:59 — every component is at its calendar max
    ts = datetime(2099, 12, 31, 23, 59, 59)
    expected = bytes([0x99, 0x12, 0x31, 0x23, 0x59, 0x59])
    assert _encode_time_bcd(ts) == expected


def test_min_values_each_component() -> None:
    """Smallest calendar value per component -> expected BCD."""
    # 2000-01-01 00:00:00 — every component is at its calendar min
    ts = datetime(2000, 1, 1, 0, 0, 0)
    expected = bytes([0x00, 0x01, 0x01, 0x00, 0x00, 0x00])
    assert _encode_time_bcd(ts) == expected


def test_byte_order_is_yymmdd_hhmmss() -> None:
    """Document and enforce the byte order — any reorder silently breaks sync."""
    # Use a datetime where every component has a distinct value
    # so a swap would be detectable.
    ts = datetime(2026, 7, 20, 14, 30, 45)
    result = _encode_time_bcd(ts)
    assert result[0] == 0x26  # YY
    assert result[1] == 0x07  # MM
    assert result[2] == 0x20  # DD
    assert result[3] == 0x14  # HH
    assert result[4] == 0x30  # mm
    assert result[5] == 0x45  # ss


@pytest.mark.parametrize(
    "ts, expected",
    [
        # Random-ish mix of values to catch any encoding wonkiness
        (datetime(2026, 1, 1, 0, 0, 0),    bytes([0x26, 0x01, 0x01, 0x00, 0x00, 0x00])),
        (datetime(2026, 10, 10, 10, 10, 10), bytes([0x26, 0x10, 0x10, 0x10, 0x10, 0x10])),
        (datetime(2026, 12, 31, 23, 59, 59), bytes([0x26, 0x12, 0x31, 0x23, 0x59, 0x59])),
        (datetime(2021, 3, 14, 15, 9, 26), bytes([0x21, 0x03, 0x14, 0x15, 0x09, 0x26])),  # pi-day
        (datetime(2030, 6, 7, 8, 9, 10),   bytes([0x30, 0x06, 0x07, 0x08, 0x09, 0x10])),
    ],
)
def test_encode_known_datetimes(ts: datetime, expected: bytes) -> None:
    assert _encode_time_bcd(ts) == expected


def test_returns_bytes_not_bytearray() -> None:
    """Helper returns immutable bytes; callers can hash/freeze the result."""
    ts = datetime(2026, 7, 20, 14, 30, 45)
    result = _encode_time_bcd(ts)
    # bytes is immutable; bytearray is mutable. We want the immutable contract.
    assert type(result) is bytes
