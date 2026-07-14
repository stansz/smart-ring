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

## Phase 2: Web Bluetooth Phone Sync ✅ DONE

| # | Task | Status |
|---|------|--------|
| 7 | `POST /api/mobile/sync` endpoint | ✅ |
| 8 | JS sync module — packet framing, all 8 types | ✅ (multi-pkt fixed) |
| 9 | 📱 BLE button in nav | ✅ |
| 10 | 12-phase progress badge | ⬜ |
| 11 | Toast notification on complete | ✅ |
| 12 | Multi-packet big-data assembly | ✅ |
| 13 | Tailscale HTTPS (`tailscale serve`) | ✅ |

### Phone Sync Known Issues

| # | Issue | Status |
|---|-------|--------|
| A | `const` → `let` reassignment bug fixed (was silently killing module) | ✅ |
| B | BLE picker should show on `https://mint.tail1b421.ts.net` after refresh | ⬜ needs phone test |
| C | Sleep stage parsing — math was OK; real bug was an extra `}` closing `connect()` early (fixed) | ✅ brace fixed / ⬜ live test |
| D | HR multi-packet response handled now (header pkt0 → pkt1 ts+9 vals → pkts 2..N 13 vals, 288 slots) | ✅ |
| E | Root cause of "only 6 records": response queue dropped all but 1st pkt → HR/HRV got ~0 data + extra `}` killed module | ✅ fixed / ⬜ verify on phone |
| F | `syncFromPhone()` Alpine method works, wired correctly | ✅ |
| G | HRV (0x39) is multi-packet too (sub0/1/2..4) — rewritten via `sendCmdMulti` | ✅ |
| H | API had duplicate SpO2 insert block (double-counted accepted) — removed | ✅ |

### Phone Sync Debug Steps for Next Session

```
0. (done) Host-side: JS + API syntax-checked; service restarted; dashboard 200.
1. Hard refresh https://mint.tail1b421.ts.net  (clear cache — old JS cached)
2. Open DevTools (Chrome) → Console, watch for errors during sync
3. Tap 📱 BLE → picker → select ring
4. Expect: hundreds of HR records (8 days × 288 slots) + HRV + temp + SpO2 + sleep
5. Check DB:  SELECT source, COUNT(*) FROM raw_heart_rate GROUP BY source;
              SELECT source, COUNT(*) FROM raw_hrv GROUP BY source;
6. If HR still sparse: log sendCmdMulti packet count per day (size from pkt[1]=0)
7. If HRV empty: confirm ring sends sub_type up to 4 (some FW may differ)
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
| — | Dashboard polish: stress/recovery timeline on dashboard tab |
| — | Dashboard polish: sleep quality trendline / week-over-week comparison |
| — | Dashboard polish: weekly/monthly summary views |
| — | Readiness score: click sub-cards for detail breakdown |
| — | Readiness score: 7/30-day trend sparkline |
| — | Readiness score: personalize weights (user profile) |
| — | Activity ring: faster rendering (Canvas/SVG optimization) |
| — | Steps: improve ring undercount (known limitation — wrist always higher) |
| — | Calories: fix firmware-unit display (divide by ~100 for kcal) |
| — | Live temp/pulse during workout |
| — | Gadgetbridge fork for Android native sync |

---

## Phone-sync analytics trigger ✅ (2026-07-12)

The API container can't run the host's `collector/analytics.py` (no venv, no collector/ mounted), so phone syncs didn't recompute scores. Fix: `mobile_sync` queues a `sync_requests` row with `requested_by='phone-analytics'`; the host poller detects it and runs analytics only (no collector). Verified: request queued → poller runs analytics within 30s.

## Timezone cutoffs ✅ (2026-07-13)

Day boundaries were inconsistent: analytics + `/api/resting-hr` used Pacific, but the API container had no `$TZ` and the Postgres session was UTC — so `CURRENT_DATE`/`ts::date` grouped by UTC day. Evening Pacific activity (after 5pm PDT) got attributed to the next day (e.g. a Saturday 7pm walk showed under Sunday). Fix: `ALTER SYSTEM SET TimeZone='America/Vancouver'` (server-wide, persists) + `TZ=America/Vancouver` on both containers (`~/.config/containers/systemd/*.container`). No data rewrite — stored `ts` are correct instants; only the day-boundary interpretation changed. Ring time-setting unaffected (host collector's `set_time_local` still sends Pacific-local BCD).


---

## Source dedup ✅ (2026-07-12)

Phone (Web Bluetooth) and ring (Linux box) sample the same physical slots, so ~99% of phone records duplicated ring. Fix: **ring canonical, phone fills gaps.**

- `mobile_sync` endpoint runs `_dedupe_sources(db)` after inserts (in-container, reliable).
- `analytics.py` `run_all` runs `dedupe_sources()` first (host, after ring syncs via poller).
- Deletes phone rows where ring has the same key (timestamp for points; day for sleep). Keeps phone rows that fill genuine gaps, labeled `source='phone'`.
- First run removed 356 redundant duplicates; only 7 phone gap-fills remain.

---

## Quick Status Check

```bash
# Verify all sensors working
curl -s "http://localhost:8000/api/raw/temperature?hours=168&limit=200" | python3 -c 'import json,sys; print(f"Temp: {len(json.load(sys.stdin))}")'
curl -s "http://localhost:8000/api/raw/spo2?hours=168&limit=200" | python3 -c 'import json,sys; print(f"SpO2: {len(json.load(sys.stdin))}")'
curl -s "http://localhost:8000/api/raw/heart-rate?hours=168&limit=500" | python3 -c 'import json,sys; print(f"HR: {len(json.load(sys.stdin))}")'
```
