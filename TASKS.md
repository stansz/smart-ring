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
| B | BLE picker should show on `https://<hostname>.<ts-domain>` after refresh | ⬜ needs phone test |
| C | Sleep stage parsing — math was OK; real bug was an extra `}` closing `connect()` early (fixed) | ✅ brace fixed / ⬜ live test |
| D | HR multi-packet response handled now (header pkt0 → pkt1 ts+9 vals → pkts 2..N 13 vals, 288 slots) | ✅ |
| E | Root cause of "only 6 records": response queue dropped all but 1st pkt → HR/HRV got ~0 data + extra `}` killed module | ✅ fixed / ⬜ verify on phone |
| F | `syncFromPhone()` works, wired correctly | ✅ |
| G | HRV (0x39) is multi-packet too (sub0/1/2..4) — rewritten via `sendCmdMulti` | ✅ |
| H | API had duplicate SpO2 insert block (double-counted accepted) — removed | ✅ |

### Phone Sync Debug Steps for Next Session

```
0. (done) Host-side: JS + API syntax-checked; service restarted; dashboard 200.
1. Hard refresh https://<hostname>.<ts-domain>  (clear cache — old JS cached)
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
| 1-2 | dashboard | Phone sync uses local timezone, not UTC |
| 3 | `api/main.py` | TZ from `$TZ` env var or `/etc/timezone` |
| 4 | `collector/ring_client.py` | Fixed `get_steps()` broken `.astimezone(tz=utc)` |
| 5 | `collector/sync_ring.py` | Fixed `upsert_steps()` UTC fallback |
| 6 | `collector/ring_client.py` | Added deprecation warning to `set_time()` |

---

## Phase 4: PWA ✅ DONE (2026-07-21)

Dashboard ships as installable PWA. Manifest + offline-shell SW + 5 PNG icons
(regular/maskable/192/512/apple-180) generated via `scripts/gen_icons.py`.

| # | Task | Status |
|---|------|--------|
| 1 | `dashboard/manifest.webmanifest` (name, theme #2563eb, display:standalone, 4 icons) | ✅ |
| 2 | `dashboard/sw.js` — offline-shell strategies (network-first `/api/*` + navigations, SWR CDN, cache-first static, network-only POST) | ✅ |
| 3 | Icons (192/512/maskable-192/maskable-512/apple-180) via Pillow one-shot | ✅ |
| 4 | `api/main.py`: `/sw.js` + `/manifest.webmanifest` root routes (Service-Worker-Allowed: /) | ✅ |
| 5 | dashboard: PWA meta tags + feature-detected SW registration | ✅ |
| 6 | Verified live on Android Chrome | ✅ |

See `docs/PWA_PLAN.md` for full details. 132/132 tests still pass; no Python
logic touched.

---

## Phase 5: Future

| # | Task |
|---|------|
| — | **Activity detection** — Phase 1 (HR zones + strain) then Phase 2 (step+HR segments). Contract: `docs/ACTIVITY_DETECTION_RESEARCH.md`. Not started. |
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

Day boundaries were inconsistent: analytics + `/api/resting-hr` used Pacific, but the API container had no `$TZ` and the Postgres session was UTC — so `CURRENT_DATE`/`ts::date` grouped by UTC day. Evening Pacific activity (after 5pm PDT) got attributed to the next day (e.g. a Saturday 7pm walk showed under Sunday). Fix: `ALTER SYSTEM SET TimeZone='America/Vancouver'` (server-wide, persists) + `TZ=America/Vancouver` on both containers (`smart-ring-db` / `smart-ring-api` system units). No data rewrite — stored `ts` are correct instants; only the day-boundary interpretation changed. Ring time-setting unaffected (host collector's `set_time_local` still sends Pacific-local BCD).


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
# Full regression net (132 tests, ~5s) — run before any refactor
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

---

## Open Backlog (Jul 2026)

Single source of truth for what's open after the Garmin integration arc
(Phases 0 + 1 + 1.5-framework + dashboard tab). Each item lists its
unblock condition so a future session knows exactly what's needed.

### Garmin: daily monitoring files (Phase 1.5) — BLOCKED

The 745's `Garmin/Metrics/` + `Garmin/Sleep/` files contain per-day HR,
HRV, SpO2, body battery, overnight skin temp, and sometimes step totals.
These would map to the existing `raw_*` tables with `source='garmin'`,
giving cross-validation against the ring's readings.

**Blocker:** the files use Garmin-manufacturer-specific FIT message
global_ids (232, 281, 282, 294, 339, 356) that **no public FIT SDK
profile documents** — not the public 21.60 profile (bundled with
`fitparse`), not the 21.202 profile (bundled with the Rust `fitparser`
crate), and not Gadgetbridge's `FitRecordDataFactory` (which only
handles the new 21.202-standard gids 211, 227, 269, 273, 297, 346, 370,
371, 398). The binary data is present and readable; the field semantics
(what each value means, what unit it's in) are the unknown.

**Unblock path (pick one):**
1. **Garmin Connect export → reference decode (recommended).** Request a
   CSV export from Garmin Connect (~1 week of data, include sleep). I
   match the displayed values (HR min/avg/max, HRV, SpO2%, skin temp) to
   the FIT field values for the same days. Once 2-3 reference days are
   matched, the field-id → semantic mapping is clear and the extractors
   in `collector/garmin/monitoring.py` can be filled in. ~1 day of work
   after the export arrives. The blocker is on the user (requesting the
   export), not on code.
2. **Rust port with newer FIT SDK profile.** The Rust `fitparser` crate
   uses 21.202, but as of the search on 2026-07-30, 21.202 does NOT have
   definitions for the 745's legacy gids either — they were removed from
   the public profile. This path would only help if a newer device
   (FR965, Fenix 7+, etc.) is added later that writes the 21.202-standard
   gids. Not useful for the 745 specifically.
3. **Port from Gadgetbridge.** Gadgetbridge's 745 support (added late
   2025) handles *activity* data over BLE but does NOT decode the 745's
   USB monitoring files — same gap we hit. Not a viable unblock.

**Status of the framework (already shipped):** `collector/garmin/
monitoring.py` has the file discovery, the fit_tool-based record reader
that exposes `(global_id, {field_id: encoded_values})` tuples, the
`ParsedMonitoring` dataclass, and 15 unit tests. The per-message
extractors (`_extract_hr`, `_extract_hrv`, etc.) are stubbed — they
return empty until the field IDs are validated. Filling them in is ~2-3
hours once the reference data is in hand.

### Garmin: Leaflet map for GPS trackpoints — PARTIALLY READY

The `/api/activities/{id}/trackpoints` endpoint already returns lat/lon
converted from FIT semicircles to degrees. The dashboard needs a Leaflet
map component to render the route.

Two pieces, different readiness:

1. **Base map + GPS route polyline** — READY. Uses CARTO Voyager tiles
   (same as bike.ogsapps.cc) or OSM fallback. No geo-api needed. ~1 hour.
2. **Elevation profile overlay** — BLOCKED on geo-api setup. The geo-api
   (`maps.ogsapps.cc`) has `/api/elevation/profile` that would produce
   an SVG elevation chart color-coded by grade (bike-map pattern). Needs
   CORS/auth opened up for the smart-ring dashboard origin before it
   can be called from the browser. ~1 hour once the API is accessible.

**Note:** the geo-api does NOT serve map tiles — it's a data API
(elevation, places, trails, transit). Tile rendering uses CARTO/OSM
either way. The geo-api value-add is the elevation profile enrichment.

### Garmin: drag-and-drop upload UI — READY

Right now re-ingesting activities requires `ssh + python -m
collector.garmin.ingest --fit-dir <path>`. A drag-and-drop zone in the
Admin tab would let you drop the `Garmin/` folder from the browser.
Accept the whole tree, ingest `Activity/` + `Summary/`, log+skip
`Metrics/` and `Sleep/` (Phase 1.5 pending).

**Unblock:** none — just build it. ~0.5 day. FastAPI `UploadFile` +
a React dropzone component.

### Merge `garmin-integration` → `dev` — READY

The branch has 6 commits, 268 tests pass, dashboard builds clean.
Could be merged to `dev` to close out the Garmin arc at Phase 1 +
dashboard, leaving Phase 1.5 (daily monitoring files) and the map/upload
follow-ups as separate future PRs off `dev`.

**Unblock:** user decision (when to merge). No code blockers.

### Activity detection (Colmi ring) — DESIGNED, NOT BUILT

`docs/ACTIVITY_DETECTION_RESEARCH.md` has a build contract for deriving
activity/strain from the ring's HR-zone minutes (Edwards TRIMP) and
15-min step+HR segments. Phase 1 = Edwards TRIMP→strain 0–21 + zone
minutes; Phase 2 = walk/run/general_activity segments. Not started.

**Unblock:** none — independent of Garmin work. ~2-3 days per the
research doc.

### Packaged-app fork — DESIGNED, NOT BUILT

`docs/PACKAGED_APP.md` describes forking the project into a standalone
desktop app (SQLite instead of Postgres, single binary, no containers).
Phase 1 of the packaged-app plan was dialect-neutral SQL (shipped
2026-07-25, commit `eba7848`). The actual fork hasn't been started.

**Unblock:** none. ~1 week per the research doc.
