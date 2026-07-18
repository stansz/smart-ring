# Colmi R09 — Device Behavior

> Empirical behavior of the Colmi R09 (FW `RT09_3.10.21_251107`, HW `RT09_V3.1`).
> This is the canonical reference for *how the ring actually behaves* — connection quirks,
> data buffers, publish cadence, and firmware workarounds. For score formulas, hardware
> specs, and analytics methodology, see `RESEARCH.md`.

## Connection quirks

The R09 firmware has several BLE behaviors requiring workarounds. Operational procedure
(forget+repair, retry backoff) lives in `../AGENTS.md`.

1. **Aggressive sleep** — stops advertising ~30s after disconnect. RSSI drops from -68 to -127.
2. **Reconnect bug (Linux/BlueZ specific)** — BlueZ holds stale GATT state after disconnect.
   Does NOT happen on Android.
3. **Single BLE connection** — hardware limitation of the RF03 SoC. Only one device can
   connect at a time. While the Linux box holds the connection during a sync, the phone
   cannot pair; `forget_ring()` frees it.
4. **bluetoothctl vs bleak conflict** — must pair → disconnect → bleak connect.

## Sync is read-only (data persists)

**Confirmed read-only on firmware RT09_3.10.21.** Syncing reads data without clearing it.
Tested both within-connection (two fetches, same session) and across-disconnect
(fetch → disconnect → reconnect → fetch). Both returned identical data.

Data persists on the ring regardless of read or disconnect. Storage is an age-based
circular buffer. Under normal operation, data is only lost when it ages out.

Multiple devices (phone + Linux collector) can sync independently without data loss
(for data the ring *did* record).

## Data type reference

Each data type below lists: **command · interval · buffer · publish cadence · format · gotchas**.
The *publish cadence* field matters: some types are not readable for the current day until
the ring commits them (see Temperature).

| Type | Command | Interval | Buffer | Publish cadence | Format / gotchas |
|------|---------|----------|--------|-----------------|------------------|
| Heart Rate | `0x15` | 5-min | ~7 days (288 slots/day) | current day readable | processed BPM, multi-packet per day |
| Steps / Activity | `0x43` | 15-min slots (0–95/day) | ~7 days | current day readable | steps + calories + distance per slot. **Hourly zero-suppressed in practice** — the ring emits a sample only for hours with steps, so Gadgetbridge's gap-fill renders zero-step hours as "not worn" (it has no wear sensor). |
| HRV | `0x39` | 30-min | ~3 days | current day readable | composite single-byte ms value (0–255), NOT RR intervals — see [HRV limitations](#hrv-limitations-no-rr-intervals) |
| Sleep | `0xBC` + type `0x27` | per-session | ~7 days | current day readable | V2 big-data: per-session stages with timestamps |
| SpO₂ | `0xBC` + type `0x2A` | hourly | ~7 days | current day readable | V2 big-data: hourly min/max averaged to single % |
| Temperature | `0xBC` + types `0x23`–`0x2B` (skip `0x2A`) | 30-min | **7 completed days** | ⚠️ **completed days only — see below** | V2 big-data, R09 exclusive. `temp_c = (raw/10)+20`. Slots rotate daily; query `0x22`–`0x2C` with `dataId == 0x25` check. |
| Stress | `0x37` | 30-min | ~7 days | current day readable | 0–99 scale |
| Battery | `0x03` | — | — | live | battery percentage |
| Goals | `0x21` | — | — | live | steps/calorie/distance targets |
| Device Info | GATT `0x180A` | — | — | live | hardware + firmware version |

### Temperature publish cadence (important)

The temperature history buffer only exposes **completed days** (`daysAgo` 1–7). The current
day (`daysAgo = 0`) is **absent from the buffer until the ring commits it** — observed to
happen late in the evening / around the day rollover. Confirmed empirically:

- 07-16 data first became readable ~22:04 on 07-16 (late evening, same day).
- 07-17 data was still absent at the 19:53 sync (no `daysAgo=0` block returned).

Each big-data response carries one day-block: `daysAgo` (1B) + skip byte (`0x1e`) + 48 bytes
(24 h × 2 half-hour values). A clean sync returns seven day-blocks (`daysAgo` 1–7); the
collector logs `Temp audit: no records for today in ring big-data buffer` when `daysAgo=0`
is missing — which is the normal state during the day.

**Implications:**
- Historical temperature for "today" is generally not fetchable until late evening or the
  next day. The dashboard temp chart inherently lags by up to a day. This is ring firmware
  behavior, **not a collector bug** — the fetch correctly reads all available completed days.
- The **only** same-day temperature source is the live push (`cmd 115`, type 5 device-notify),
  which requires a sustained active connection. Gadgetbridge gets it (stays connected); our
  ~40 s sync windows usually miss it.

## V2 Big-Data protocol (sleep, SpO₂, temperature)

These use a second BLE service (`de5bf728`) separate from Nordic UART:
- **Request**: write raw bytes to COMMAND char (`de5bf72a`) — no 16-byte framing.
  `bytearray([0xBC, data_type, 0x01, 0x00, 0xFF, 0x00, 0xFF])`.
- **Response**: notify on NOTIFY_V2 char (`de5bf729`) — multi-packet; accumulate until
  `length + 6` bytes (header bytes `[2:3]` = uint16 LE total length).
- **Shared queue**: sleep/SpO₂/temp share one queue and one accumulator. Drain the queue
  and reset `_bd_buf` before each request, or stale responses poison the next read
  (was causing 15/0/15/0 flakiness with sleep type `0x27` collisions).

## Real-time only (NOT stored)

Requires an active BLE connection; not in the historical buffers:
- Raw PPG (photoplethysmogram waveform)
- Raw accelerometer (x/y/z at full rate)
- Live HR (current BPM reading)

The 512 KB flash can't hold continuous waveform data. For raw PPG you must be actively
connected and streaming — drains the 15 mAh battery in ~4–6 hours.

## HRV limitations (no RR intervals)

The ring provides a **composite HRV value** — not RR intervals. Consequences:
- ❌ True RMSSD and pNN50 cannot be computed.
- ✅ Trend analysis works: composite value tracks meaningfully day-to-day.
- ✅ Z-score recovery works: uses personal baseline + SD, robust to monotonic transform.
- ✅ All commercial rings (Oura, WHOOP) use PPG-derived values the same way.

## Background logger stall (HR-log + temperature)

The background logging task (`cmd 0x15` HeartRateLog, shared with temperature) runs as a
**separate firmware task** from live PPG measurement. It can hang silently — the ring
continues real-time measurement (HRV, SpO₂, stress still flow), but new HR/temp samples
stop being written to the on-board buffer. When this happens, the buffer returns
`NoData`/empty for the affected types, and no client (our collector, Gadgetbridge, phone)
can recover data the ring never wrote. HR and temperature stall together (same task).

**Detection signal:** HRV present for today (ring worn + measuring) but HR log/temp empty
→ logger stalled.

**Auto-recovery:** toggle `set_heart_rate_log_settings(False→True)` to re-kick the firmware
logger task (implemented in `sync_ring.py`). If the toggle doesn't revive it, a full
power-cycle (discharge → recharge) is needed.

## Time sync protocol

The R09 firmware reads the `set_time` BCD bytes as **local wall-clock values** (not UTC).
Three implementations compared:

| Aspect | Gadgetbridge | Our `set_time_local()` | Library `set_time_packet()` |
|--------|--------------|------------------------|------------------------------|
| Timezone | LOCAL | LOCAL | UTC |
| Data bytes | 6 (year/month/day/hour/min/sec) | 6 (same) | 7 (+ language flag) |
| Encoding | BCD | BCD | BCD |

The library's UTC approach shifts the ring's "midnight" by the host's UTC offset, causing
data to land in wrong time slots. Our 6-byte local packet matches Gadgetbridge byte-for-byte.

The ring acknowledges `set_time` with a 16-byte capability packet. The library's `client.py`
silently discards this via `empty_parse` — we override with `_pass_through` so the ack is
captured. After sending, we wait 3 s for the response to confirm the ring processed the command.

**Drift measurement pitfall:** do NOT measure clock drift as `max(HR ts) - now()`. With
30-min HR sampling this always shows −10 to −30 min "drift" — that's sampling lag, not clock
error. Any data-freshness-based check will false-alarm when the ring is off the finger.
