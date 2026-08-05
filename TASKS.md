# Smart Ring — Open Backlog

Single source of truth for what's open. Each item lists its unblock condition so a future session knows exactly what's needed.

For historical phases (Temperature Fix, Mobile GUI, Phone Sync, Timezone Audit, PWA, Cleanup arc), see git history and `docs/done/`.

---

## Garmin: daily monitoring files (Phase 1.5) — BLOCKED

The 745's `Garmin/Metrics/` + `Garmin/Sleep/` files contain per-day HR, HRV, SpO2, body battery, overnight skin temp, and sometimes step totals. These would map to the existing `raw_*` tables with `source='garmin'`, giving cross-validation against the ring's readings.

**Blocker:** the files use Garmin-manufacturer-specific FIT message global_ids (232, 281, 282, 294, 339, 356) that **no public FIT SDK profile documents** — not the public 21.60 profile (bundled with `fitparse`), not the 21.202 profile (bundled with the Rust `fitparser` crate), and not Gadgetbridge's `FitRecordDataFactory` (which only handles the new 21.202-standard gids 211, 227, 269, 273, 297, 346, 370, 371, 398). The binary data is present and readable; the field semantics (what each value means, what unit it's in) are the unknown.

**Unblock path (pick one):**
1. **Garmin Connect export → reference decode (recommended).** Request a CSV export from Garmin Connect (~1 week of data, include sleep). I match the displayed values (HR min/avg/max, HRV, SpO2%, skin temp) to the FIT field values for the same days. Once 2-3 reference days are matched, the field-id → semantic mapping is clear and the extractors in `collector/garmin/monitoring.py` can be filled in. ~1 day of work after the export arrives. The blocker is on the user (requesting the export), not on code.
2. **Rust port with newer FIT SDK profile.** The Rust `fitparser` crate uses 21.202, but as of the search on 2026-07-30, 21.202 does NOT have definitions for the 745's legacy gids either — they were removed from the public profile. This path would only help if a newer device (FR965, Fenix 7+, etc.) is added later that writes the 21.202-standard gids. Not useful for the 745 specifically.
3. **Port from Gadgetbridge.** Gadgetbridge's 745 support (added late 2025) handles *activity* data over BLE but does NOT decode the 745's USB monitoring files — same gap we hit. Not a viable unblock.

**Status of the framework (already shipped):** `collector/garmin/monitoring.py` has the file discovery, the fit_tool-based record reader that exposes `(global_id, {field_id: encoded_values})` tuples, the `ParsedMonitoring` dataclass, and 15 unit tests. The per-message extractors (`_extract_hr`, `_extract_hrv`, etc.) are stubbed — they return empty until the field IDs are validated. Filling them in is ~2-3 hours once the reference data is in hand.

### Garmin: elevation profile overlay — BLOCKED

The base GPS route map is done (`web/src/components/garmin/ActivityMap.tsx`, commit `6cc5bc1`). The elevation profile overlay is blocked on geo-api setup. The geo-api (`maps.ogsapps.cc`) has `/api/elevation/profile` that would produce an SVG elevation chart color-coded by grade (bike-map pattern). Needs CORS/auth opened up for the smart-ring dashboard origin before it can be called from the browser. ~1 hour once the API is accessible.

**Note:** the geo-api does NOT serve map tiles — it's a data API (elevation, places, trails, transit). Tile rendering uses CARTO/OSM either way. The geo-api value-add is the elevation profile enrichment.

---

## Merge `garmin-integration` → `dev` — READY

The branch has 24 commits, 279 tests pass, dashboard builds clean. Garmin integration arc complete at Phase 1 + dashboard (activities, map, upload) + analytics rework (zoom, hourly resolution, sensor freshness nav). Phase 1.5 (daily monitoring files) remains blocked on FIT SDK decode.

**Unblock:** user decision (when to merge). No code blockers.

---

## Activity detection (Colmi ring) — DESIGNED, NOT BUILT

`docs/ACTIVITY_DETECTION_RESEARCH.md` has a build contract for deriving activity/strain from the ring's HR-zone minutes (Edwards TRIMP) and 15-min step+HR segments. Phase 1 = Edwards TRIMP→strain 0–21 + zone minutes; Phase 2 = walk/run/general_activity segments. Not started.

**Unblock:** none — independent of Garmin work. ~2-3 days per the research doc.

---

## Packaged-app fork — DESIGNED, NOT BUILT

`docs/PACKAGED_APP.md` describes forking the project into a standalone desktop app (SQLite instead of Postgres, single binary, no containers). Phase 1 of the packaged-app plan was dialect-neutral SQL (shipped 2026-07-25, commit `eba7848`). The actual fork hasn't been started.

**Unblock:** none. ~1 week per the research doc.

---

## CFW Roadmap (from docs/RESEARCH.md)

Stock firmware is the starting point. Custom firmware mods to explore:

| # | Task | Notes |
|---|------|-------|
| — | Sync behavior control | Never clear on sync, or "give me everything since timestamp X" |
| — | Faster raw PPG polling | atc1441 has `R02_3.00.06_FasterRawValuesMOD.bin` |
| — | MAC whitelist | Only authorized devices can connect (~10 lines of C) |
| — | Custom storage model | Circular buffer with proper timestamps, configurable retention |
| — | Shared secret auth | Collector sends password byte before data commands accepted |

Flash via atc1441's web-based OTA tool: https://atc1441.github.io/ATC_RF03_Writer.html

---

## Readiness Score Improvements (prioritized, from gap analysis)

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

## Other Open Items

| # | Task | Notes |
|---|------|-------|
| — | Fix per-attempt `accepted` counting in `/api/mobile/sync` | Use `cursor.rowcount`; pinned by `tests/test_mobile_sync.py` |
| — | Investigate `stress_classification` schema bug | Columns named `_rmssd` but store stress_values (0-99). Documented in `db/init.sql`. Rename via migration when next touching the table. |
| — | Current Status trend chart | Intra-day line graph; data already retained in `current_status` table |
| — | Auto-refresh Current Status card on sync completion | Currently requires page refresh |
| — | systemd auto-sync timer | Scheduled, not manual |
| — | 0x80-bit async packets investigation | Undocumented ring behavior |
