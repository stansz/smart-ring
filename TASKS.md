# Smart Ring Task List

## Temperature Fix ✅

**Problem:** Ring stores ~8 days of temperature across big-data types 0x23-0x2B (one per day, skipping 0x2A = SpO2). The slot→day mapping rotates daily. Previous code only queried 0x25-0x29, missing current-day data at 0x23/0x24/0x2B.

**Fix:** `fetch_temperature_history()` queries 0x22-0x2C (skip 0x2A) with response dataId=0x25 check. Queue drain + `_bd_buf` reset between requests prevents shared-queue desync. 329 records synced (9 days, 30-min intervals).

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
| — | Parser tests (Tier 1 item 4 — deferred as optional, see `docs/CLEANUP_PLAN.md`) |
| — | Fix per-attempt `accepted` counting in `/api/mobile/sync` (use `cursor.rowcount`; pinned by `tests/test_mobile_sync.py`) |
| — | **Investigate `stress_classification` schema bug**: columns named `_rmssd` but store stress_values (0-99). Documented in `db/init.sql`. Rename via migration when next touching the table. |
| — | Current Status trend chart (intra-day line graph; data already retained in `current_status` table) |
| — | Auto-refresh Current Status card on sync completion (currently requires page refresh) |
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

### CFW Roadmap (from docs/RESEARCH.md)

Stock firmware is the starting point. Custom firmware mods to explore:

| # | Task | Notes |
|---|------|-------|
| — | Sync behavior control | Never clear on sync, or "give me everything since timestamp X" |
| — | Faster raw PPG polling | atc1441 has `R02_3.00.06_FasterRawValuesMOD.bin` |
| — | MAC whitelist | Only authorized devices can connect (~10 lines of C) |
| — | Custom storage model | Circular buffer with proper timestamps, configurable retention |
| — | Shared secret auth | Collector sends password byte before data commands accepted |

Flash via atc1441's web-based OTA tool: https://atc1441.github.io/ATC_RF03_Writer.html

### Readiness Score Improvements (prioritized, from gap analysis)

Ranked by impact-to-effort ratio:

| # | Task | Effort | Notes |
|---|------|--------|-------|
| — | **Add Temperature deviation** | Low | We have data, just wire it in. Add as 5th pillar ~10% weight |
| — | **Add HRV Balance** | Low | 14-day vs 30-day baseline (currently 7-day only). Captures chronic changes |
| — | **Add Sleep Regularity** | Low | Variance of bed/wake times over 7 days. Oura uses this |
| — | **Bump HRV weight** | Low | WHOOP uses ~70%. Consider 40-50% if composite HRV proves reliable |
| — | **Add Recovery Index** | Medium | Time from overnight HR low to wake. Oura's unique contributor |
| — | **Illness early warning** | Medium | HRV drop + RHR rise >3 bpm for 2+ days → flag |

---

## Phone-sync analytics trigger ✅ (2026-07-12)

The API container can't run the host collector (no venv, no BLE), so phone syncs didn't recompute scores. Fix: `mobile_sync` queues a `sync_requests` row with `requested_by='phone-analytics'`; the host poller detects it and runs `python -m collector.analytics` only (no collector). Verified: request queued → poller runs analytics within 30s.

## Timezone cutoffs ✅ (2026-07-13)

Day boundaries were inconsistent: analytics + `/api/resting-hr` used Pacific, but the API container had no `$TZ` and the Postgres session was UTC — so `CURRENT_DATE`/`ts::date` grouped by UTC day. Evening Pacific activity (after 5pm PDT) got attributed to the next day (e.g. a Saturday 7pm walk showed under Sunday). Fix: `ALTER SYSTEM SET TimeZone='America/Vancouver'` (server-wide, persists) + `TZ=America/Vancouver` on both containers (`~/.config/containers/systemd/*.container`). No data rewrite — stored `ts` are correct instants; only the day-boundary interpretation changed. Ring time-setting unaffected (host collector's `set_time_local` still sends Pacific-local BCD).


---

## Source dedup ✅ (2026-07-12, updated 2026-07-20)

Phone (Web Bluetooth) and ring (Linux box) sample the same physical slots, so ~99% of phone records duplicated ring. Fix: **ring canonical, phone fills gaps.**

- The single source of truth is `collector/analytics/dedupe.py:dedupe_sources()`, run by the host poller at the start of every analytics pass (before scorers).
- The API previously had its own `_dedupe_sources` copy that ran inline on every `/api/mobile/sync` — **removed 2026-07-20** as redundant (API cleanup Step 2). Phone-sync now relies on analytics-side dedup running within ~30s (poller cadence).
- Deletes phone rows where ring has the same key (timestamp for points; day for sleep). Keeps phone rows that fill genuine gaps, labeled `source='phone'`.
- First run removed 356 redundant duplicates; live DB currently shows `ring=493 / phone=2`.
- Regression net: `tests/test_dedupe.py` (13 tests against ephemeral PostgreSQL).

---

## Quick Status Check

```bash
# Full regression net (65 tests, ~4s) — run before any refactor
venv/bin/python3 -m pytest tests/

# Verify all sensors working
curl -s "http://localhost:8000/api/raw/temperature?hours=168&limit=200" | python3 -c 'import json,sys; print(f"Temp: {len(json.load(sys.stdin))}")'
curl -s "http://localhost:8000/api/raw/spo2?hours=168&limit=200" | python3 -c 'import json,sys; print(f"SpO2: {len(json.load(sys.stdin))}")'
curl -s "http://localhost:8000/api/raw/heart-rate?hours=168&limit=500" | python3 -c 'import json,sys; print(f"HR: {len(json.load(sys.stdin))}")'
```

---

## Cleanup arc ✅ (2026-07-18 to 2026-07-20)

Major refactor work — see `docs/CLEANUP_PLAN.md` for full history.

### Collector/analytics refactor (Phases 0–4)
- Deleted `collector-wrapper.py`, `analytics-wrapper.py`, scratch test scripts
- Split `sync_ring.py` (1079 → 284 lines) into `collector/protocol/` package
- Split `analytics.py` (1079 → 13 focused files) into `collector/analytics/` package
- Poller rewritten as thin orchestrator over `collector/jobs/`
- `argparse` everywhere (no more `sys.argv.index()`)
- Forget+repair is the default; `--no-forget` for diagnostics

### API cleanup (Steps 1, 2, 4)
- Step 1: Dropped dead `Base(DeclarativeBase)` + `create_all()` (no ORM models exist)
- Step 2: Dropped redundant `_dedupe_sources` from `api/main.py` (analytics owns dedup)
- Step 3: **Skipped indefinitely** — "rearranging deck chairs" per reviewer
- Step 4: Generic `upsert_many` dispatcher in `api/upsert.py` (-30 lines)

### Test suite (Tier 1, items 1–3 + bonus)
- `tests/test_trap_score.py` (20 tests) — scoring math boundaries + linearity
- `tests/test_time_sync_bcd.py` (16 tests) — sacred BCD encoding byte-for-byte vs Gadgetbridge
- `tests/test_dedupe.py` (13 tests) — source dedup with ephemeral PostgreSQL
- `tests/test_mobile_sync.py` (16 tests) — full mobile_sync contract
- **Total: 65 tests pass in ~4s.** Parser tests (item 4) deferred as optional.
