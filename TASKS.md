# Smart Ring Task List

## Temperature Fix Complete ✅

**Problem:** Ring stores 5 days of temperature across big-data types 0x25-0x29 (one type per day, oldest to newest). Previous code only queried 0x25 (4 days ago), missing 4 days of data.

**Fix:** Updated `fetch_temperature_history()` in `collector/sync_ring.py` to loop types 0x25-0x29.

**Result:** 142 temperature records synced (5 nights, 30-min intervals during sleep)

**DB Status:** 142 temp records across 5 nights (Jul 8-12). Temperature chart on dashboard now shows 5 nights of overnight skin temp.

---

## Phase 1: Mobile GUI Polish (6 tasks, ~30 min)

| # | Task | Priority | Status |
|---|------|----------|--------|
| 1 | Responsive vitals chart SVG (max-width:100%, smaller fonts on < sm) | High | ⬜ |
| 2 | Card grid stacks single-column on mobile (grid-cols-1 sm:grid-cols-2) | High | ⬜ |
| 3 | Sync button larger touch target, full-width on mobile | Medium | ⬜ |
| 4 | Tab bar larger tap targets (px-4 py-3 min), better spacing | Medium | ⬜ |
| 5 | Admin tables compact, nowrap dates — verify scroll | Low | ⬜ |
| 6 | Battery indicator more prominent, better nav positioning | Low | ⬜ |

---

## Phase 2: Web Bluetooth Phone Sync (7 tasks, ~3.5 hrs)

| # | Task | Priority | Status |
|---|------|----------|--------|
| 7 | POST /api/mobile/sync endpoint (accepts ring data from phone) | High | ⬜ |
| 8 | JS sync module — packet framing, cmd/response, all 8 data types | High | ⬜ |
| 9 | 'Sync Now' button in mobile nav + BLE device picker | High | ⬜ |
| 10 | 12-phase progress badge + conflict check (ring busy guard) | Medium | ⬜ |
| 11 | POST results to API → analytics runs → toast notification | Medium | ⬜ |
| 12 | Multi-packet big-data assembly (matching ring_client.py logic) | High | ⬜ |
| 13 | Tailscale HTTPS setup for PWA installability | Low | ⬜ |

---

## Key Architecture Decisions

### Temperature Buffer
- Ring stores 5 days of temperature across big-data types 0x25-0x29 (one type per day, oldest to newest)
- `fetch_temperature_history()` now loops 0x25-0x29 → 142 records synced (5 nights, 30-min intervals)
- Buffer is circular — oldest day overwritten each new day

### Sync Conflict Resolution
**No conflict resolution needed.** Ring is read-only, timestamps are source of truth, DB has `ON CONFLICT (ts, source) DO NOTHING`. Both devices sync independently, duplicates silently skipped.

### Web Bluetooth Phone Sync
- Phone syncs independently (5-day buffer means no coordination needed)
- Linux box continues 24/7 polling sync
- Phone syncs on-demand via Web Bluetooth
- Phone connects → syncs → POSTs to `/api/mobile/sync` → analytics runs → disconnects

---

## Files to Modify

| File | Changes |
|------|---------|
| `dashboard/index.html` | Mobile CSS (6 tasks) + Web BLE sync module (7 tasks) |
| `api/main.py` | Add `POST /api/mobile/sync` endpoint |
| `collector/sync_ring.py` | Already fixed: `fetch_temperature_history()` loops 0x25-0x29 |

---

## Quick Status Check

```bash
# Verify temp data
curl -s "http://localhost:8000/api/raw/temperature?hours=168&limit=200" | python3 -c "
import json, sys
data = json.load(sys.stdin)
print(f'Total: {len(data)} records')
from collections import Counter
by_date = {}
for r in data:
    d = r['ts'][:10]
    by_date[d] = by_date.get(d, 0) + 1
for d in sorted(by_date):
    print(f'  {d}: {by_date[d]} readings')
"
```

**Expected output:** 142 records across 5 days (Jul 8-1I'll write the task checklist to a .md file for you.
<tool_call>
<function=write>
<parameter=content>
# Smart Ring Task List

## Temperature Fix Complete ✅

**Problem:** Ring stores 5 days of temperature across big-data types 0x25-0x29 (one type per day, oldest to newest). Previous code only queried 0x25 (4 days ago), missing 4 days of data.

**Fix:** Updated `fetch_temperature_history()` in `collector/sync_ring.py` to loop types 0x25-0x29.

**Result:** 142 temperature records synced (5 nights, 30-min intervals during sleep)

**DB Status:** 142 temp records across 5 nights (Jul 8-12). Temperature chart on dashboard now shows 5 nights of overnight skin temp.

---

## Phase 1: Mobile GUI Polish (6 tasks, ~30 min)

| # | Task | Priority | Status |
|---|------|----------|--------|
| 1 | Responsive vitals chart SVG (max-width:100%, smaller fonts on < sm) | High | ⬜ |
| 2 | Card grid stacks single-column on mobile (grid-cols-1 sm:grid-cols-2) | High | ⬜ |
| 3 | Sync button larger touch target, full-width on mobile | Medium | ⬜ |
| 4 | Tab bar larger tap targets (px-4 py-3 min), better spacing | Medium | ⬜ |
| 5 | Admin tables compact, nowrap dates — verify scroll | Low | ⬜ |
| 6 | Battery indicator more prominent, better nav positioning | Low | ⬜ |

---

## Phase 2: Web Bluetooth Phone Sync (7 tasks, ~3.5 hrs)

| # | Task | Priority | Status |
|---|------|----------|--------|
| 7 | POST /api/mobile/sync endpoint (accepts ring data from phone) | High | ⬜ |
| 8 | JS sync module — packet framing, cmd/response, all 8 data types | High | ⬜ |
| 9 | 'Sync Now' button in mobile nav + BLE device picker | High | ⬜ |
| 10 | 12-phase progress badge + conflict check (ring busy guard) | Medium | ⬜ |
| 11 | POST results to API → analytics runs → toast notification | Medium | ⬜ |
| 12 | Multi-packet big-data assembly (matching ring_client.py logic) | High | ⬜ |
| 13 | Tailscale HTTPS setup for PWA installability | Low | ⬜ |

---

## Key Architecture Decisions

### Temperature Buffer
- Ring stores 5 days of temperature across big-data types 0x25-0x29 (one type per day, oldest to newest)
- `fetch_temperature_history()` now loops 0x25-0x29 → 142 records synced (5 nights, 30-min intervals)
- Buffer is circular — oldest day overwritten each new day

### Sync Conflict Resolution
**No conflict resolution needed.** Ring is read-only, timestamps are source of truth, DB has `ON CONFLICT (ts, source) DO NOTHING`. Both devices sync independently, duplicates silently skipped.

### Web Bluetooth Phone Sync
- Phone syncs independently (5-day buffer means no coordination needed)
- Linux box continues 24/7 polling sync
- Phone syncs on-demand via Web Bluetooth
- Phone connects → syncs → POSTs to `/api/mobile/sync` → analytics runs → disconnects

---

## Files to Modify

| File | Changes |
|------|---------|
| `dashboard/index.html` | Mobile CSS (6 tasks) + Web BLE sync module (7 tasks) |
| `api/main.py` | Add `POST /api/mobile/sync` endpoint |
| `collector/sync_ring.py` | Already fixed: `fetch_temperature_history()` loops 0x25-0x29 |

---

## Quick Status Check

```bash
# Verify temp data
curl -s "http://localhost:8000/api/raw/temperature?hours=168&limit=200" | python3 -c "
import json, sys
data = json.load(sys.stdin)
print(f'Total: {len(data)} records')
from collections import Counter
by_date = {}
for r in data:
    d = r['ts'][:10]
    by_date[d] = by_date.get(d, 0) + 1
for d in sorted(by_date):
    print(f'  {d}: {by_date[d]} readings')
"
```

**Expected output:** 142 records across 5 days (Jul 8-12)