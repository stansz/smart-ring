# Mobile Sync Roadmap

> **Phase 1 + 2a implemented July 2026.** Web Bluetooth PWA sync works end-to-end:
> phone (Android Chrome) → ring over BLE → `/api/mobile/sync` → Postgres → dedup → analytics.
> See AGENTS.md for details.

## Goal

Ring syncs when away from home → data reaches Linux box Postgres → analytics run → dashboard shows everything.

## Architecture (Planned)

```
┌─────────────────────────────────────────────────────────────┐
│  Linux Box (Home) — always on, Tailscale                    │
│  ├─ Postgres + FastAPI (port 8000)                          │
│  ├─ Python Analytics (sleep, HRV, stress, circadian, RHR)   │
│  └─ Dashboard (3-tab Alpine.js PWA)                          │
└─────────────────────────────────────────────────────────────┘
                          ▲
         Tailscale        │
                          │
┌─────────────────────────┴──────────────────────┐
│  Phone (Android) OR MacBook (Chrome PWA)        │
│  ├─ BLE → Ring                                 │
│  ├─ Syncs ring on demand (manual)              │
│  └─ POSTs raw data to Linux box FastAPI        │
└────────────────────────────────────────────────┘
```

**Linux box Postgres remains the source of truth.** Phone/MacBook are edge collectors that push data when online.

---

## Phase 1: FastAPI Mobile Sync Endpoint

### `POST /api/mobile/sync`

```json
{
  "ring_address": "XX:XX:XX:XX:XX:XX",
  "synced_at": "2026-07-12T14:30:00Z",
  "battery_pct": 85,
  "fw_version": "RT09_3.10.21",
  "heart_rate": [
    { "ts": "2026-07-12T10:00:00Z", "bpm": 72, "hrv": null }
  ],
  "steps": [
    { "ts": "2026-07-12T09:30:00Z", "steps": 120, "calories": 5, "distance": 80 }
  ],
  "hrv": [
    { "ts": "2026-07-12T08:00:00Z", "hrv_value": 42, "hrv_type": "composite" }
  ],
  "sleep": [
    {
      "start_ts": "2026-07-11T23:00:00Z",
      "end_ts": "2026-07-12T06:30:00Z",
      "stage": 3,
      "stage_name": "deep",
      "duration_minutes": 45
    }
  ],
  "spo2": [
    { "ts": "2026-07-12T02:00:00Z", "spo2_value": 97 }
  ],
  "temperature": [
    { "ts": "2026-07-12T03:00:00Z", "temp_c": 36.2 }
  ],
  "stress": [
    { "ts": "2026-07-12T11:00:00Z", "stress_value": 34 }
  ],
  "goals": {
    "steps_goal": 5000,
    "calories_goal": 300,
    "distance_m_goal": 3000,
    "sport_goal": null,
    "sleep_goal": null
  }
}
```

- **Auth:** API key via `X-Device-Key` header or Tailscale IP allowlist
- **Upsert:** `ON CONFLICT (ts) DO NOTHING` — idempotent, no duplicates
- **Triggers:** `collector/analytics.py` after commit
- **Returns:** `{ "accepted": 42, "duplicates_skipped": 3 }`
- **All arrays optional** — only send what changed

---

## Phase 2a: WebBluetooth PWA (MacBook / Android Chrome)

### Why This Over Android App
- Development stays on Linux box (where opencode runs)
- No Android Studio / Gradle / SDK setup
- No Windows machine needed
- Same code serves dashboard + sync from one PWA
- MacBook gets native-feeling app via Chrome install

### What to Build

#### 1. PWA Setup (already mostly done)
- `manifest.json` — name, icons, `display: standalone`
- `service-worker.js` — cache static assets, offline shell

#### 2. WebBluetooth Module (the main work)
```
dashboard/static/js/ring-ble.js
├─ Nordic UART (6E40FFF0-...)
│   ├─ 16-byte packet framing + checksum
│   ├─ Command/response flow
│   └─ Handlers: HR, steps, HRV, stress, goals
└─ V2 Big Data (de5bf728-...)
    ├─ Raw byte writes (no 16-byte framing)
    ├─ Multi-packet assembly (header [2:4] = total length)
    └─ Handlers: sleep, SpO2, temperature
```

#### 3. Sync Flow
```
1. User opens PWA → "Mobile Sync" tab
2. navigator.bluetooth.requestDevice({filters: [{namePrefix: 'R09'}]})
3. Connect GATT → discover Nordic UART + V2 Big Data services
4. Run 12-phase sync (reuse progress badge from dashboard)
5. Cache results in IndexedDB
6. POST batch to /api/mobile/sync
7. Show: "Synced 48 records" or "Network error — cached 48 records locally"
```

#### 4. Reference Implementations
- Python BLE: `collector/sync_ring.py` + `collector/ring_client.py`
- WebBluetooth: `atc1441/ATC_RF03_Writer` (proves ring works via browser)

### Limitations
- Foreground only (browser tab must stay open during ~5 min sync)
- No background sync on MacBook or Android
- Not on iOS Safari (Apple blocks WebBluetooth)
- Ring must be forgotten from phone before browser can pair

---

## Phase 2b: Gadgetbridge Fork (Android, Alternative)

### If PWA Doesn't Work Out
- Fork Gadgetbridge PR #3896 at Colmi module
- Strip to R02/R03/R06/R09 only
- Add `MobileSyncService`: query unsynced rows → POST to FastAPI → mark synced
- Requires Android Studio + device testing (Windows box)

### Advantages Over PWA
- Background sync via WorkManager (optional, not initially planned)
- Local SQLite for offline resilience
- Already proven: Gadgetbridge + R09 works
- Handles BLE reconnection, buffering, sleep detection

---

## Implementation Order

| Step | Effort | Blocked By |
|------|--------|------------|
| 1. `POST /api/mobile/sync` endpoint | ~2 hrs | Nothing |
| 2. PWA manifest + service worker | ~1 hr | Nothing |
| 3. WebBluetooth protocol port (JS) | ~12-16 hrs | Step 1 |
| 4. PWA sync UI (reuse dashboard components) | ~2 hrs | Steps 2, 3 |
| 5. End-to-end test (MacBook Chrome) | ~2 hrs | Steps 1-4 |
| 6. (Optional) Gadgetbridge fork | ~18-20 hrs | Step 1 |

**Total Phase 1+2a (PWA): ~17-23 hrs** — all on Linux box with opencode.

---

## Decision Points

| Question | Answer |
|----------|--------|
| **Source of truth?** | Linux box Postgres |
| **Phone/Mac role?** | Edge collector, pushes when online |
| **Offline OK?** | IndexedDB caches, flushes when Tailscale up |
| **Background sync?** | No (manual trigger only) |
| **iOS support?** | No (WebBluetooth blocked by Apple) |
| **Auth?** | API key header or Tailscale IP allowlist |
| **Analytics?** | Run on Linux box only (Python, unchanged) |
