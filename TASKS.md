# Smart Ring Task List

## Temperature Fix ✅

**Problem:** Ring stores 5 days of temperature across big-data types 0x25-0x29 (one per day, oldest to newest). Previous code only queried 0x25.

**Fix:** `fetch_temperature_history()` loops 0x25-0x29. 153 records synced (5 nights, 30-min intervals, overnight skin temp).

---

## Phase 1: Mobile GUI ✅ DONE

| # | Task | Status |
|---|------|--------|
| 1 | Responsive vitals chart SVG | ✅ |
| 2 | Card grid stacks single-column on mobile | ✅ |
| 3 | Sync button larger touch target | ✅ |
| 4 | Tab bar dropdown on mobile | ✅ |
| 5 | Admin tables compact + nowrap | ✅ |
| 6 | Battery + nav compact two-row layout | ✅ |
| — | ClockAlert false-alarm banner | ✅ REMOVED |
| — | Circadian HR card matches Vitals layout | ✅ |
| — | Sync log pagination 10/page | ✅ |

---

## Phase 2: Web Bluetooth Phone Sync 🔧 IN PROGRESS

| # | Task | Status |
|---|------|--------|
| 7 | `POST /api/mobile/sync` endpoint | ✅ |
| 8 | JS sync module — packet framing, all 8 types | ✅ (buggy) |
| 9 | 📱 BLE button in nav | ✅ |
| 10 | 12-phase progress badge | ⬜ |
| 11 | Toast notification on complete | ✅ |
| 12 | Multi-packet big-data assembly | ✅ |
| 13 | Tailscale HTTPS (`tailscale serve`) | ✅ |

### Phone Sync Known Issues (next session)

| # | Issue |
|---|-------|
| A | `const` → `let` reassignment bug fixed (was silently killing module) |
| B | BLE picker should show on `https://mint.tail1b421.ts.net` after refresh |
| C | Sleep stage parsing needs testing (date/timezone may still be off) |
| D | HR multi-packet response isn't handled (ring sends multiple 16-byte pkts) |
| E | Only got 6 records test-synced — need to verify full sync flow works |
| F | `syncFromPhone()` Alpine method works, wired correctly |

### Phone Sync Debug Steps for Next Session

```
1. Hard refresh https://mint.tail1b421.ts.net
2. Tap 📱 BLE → BLE picker should appear
3. Select ring → sync runs
4. Check DB for source='phone' records
5. If no data: add console.log to connect() to trace
6. If partial data: debug individual parsers (sleep, HR)
```

---

## Phase 3: Timezone Audit ✅ DONE

| # | File | Fix |
|---|------|-----|
| 1-2 | `dashboard/index.html` | Phone sync uses local timezone, not UTC |
| 3 | `api/main.py` | TZ from `$TZ` env var or `/etc/timezone` |
| 4 | `collector/ring_client.py` | Fixed `get_steps()` broken `.astimezone(tz=utc)` |
| 5 | `collector/sync_ring.py` | Fixed `upsert_steps()` UTC fallback |
| 6 | `collector/ring_client.py` | Added deprecation warning to `set_time()` |

---

## Phase 4: Future

| # | Task |
|---|------|
| — | systemd auto-sync timer (scheduled, not manual) |
| — | 0x80-bit async packets investigation |
| — | HR multi-packet response handling in phone sync |
| — | Live temp/pulse during workout |
| — | Gadgetbridge fork for Android native sync |

---

## Quick Status Check

```bash
# Verify all sensors working
curl -s "http://localhost:8000/api/raw/temperature?hours=168&limit=200" | python3 -c 'import json,sys; print(f"Temp: {len(json.load(sys.stdin))}")'
curl -s "http://localhost:8000/api/raw/spo2?hours=168&limit=200" | python3 -c 'import json,sys; print(f"SpO2: {len(json.load(sys.stdin))}")'
curl -s "http://localhost:8000/api/raw/heart-rate?hours=168&limit=500" | python3 -c 'import json,sys; print(f"HR: {len(json.load(sys.stdin))}")'
```
