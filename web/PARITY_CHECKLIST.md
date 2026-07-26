# Parity Checklist — Smoked from dashboard/index.html (2026-07-25)

## Layout / Shell
- [ ] 3 tabs: Dashboard, Analytics, Admin
- [ ] Dark mode toggle (class-based, localStorage)
- [ ] Date nav: prev / today / next, drives day filter
- [ ] Battery indicator (pct + icon, pulls from /api/admin/ring-status)
- [ ] Toasts: success / error / info fade-out
- [ ] prefers-reduced-motion respect

## Dashboard Tab

### Hero Panel
- [ ] DayRing (custom SVG radial bars + sleep overlay, click-to-navigate day)
- [ ] Readiness score (0–100, with sub-scores)
- [ ] Preliminary badge (frozen_at === null)
- [ ] Activity ring: steps / calories / distance dials
- [ ] Worn-hours display

### Vitals Panel (3-card)
- [ ] Vibe card — Current Status score + vibe label (Locked In / Solid / Vibing / Winded / Gassed) + 12-phase sparkline
- [ ] Stress card — recent stress avg + mini bar chart (last 2h)
- [ ] Trend card — HRV slope (rising/falling indicator)
- [ ] Confidence badges (partial/full) on Vibe card

### Charts
- [ ] Vitals chart — HR + SpO₂ dual-axis line chart
- [ ] Circadian HR — area chart with gradient fill
- [ ] Sleep donut — deep/rem/light/awake pie/donut
- [ ] Raw HR table — scrollable recent records
- [ ] Raw Steps table — scrollable recent records

### Sync Widget (desktop)
- [ ] Sync Now button → POST /api/admin/sync
- [ ] Polling progress display (current_step, elapsed timer)
- [ ] Cancel sync button → POST /api/admin/cancel-sync
- [ ] Auto-refresh dashboard queries on sync complete

### Data Quality
- [ ] Stale-data banner (staleTypes, shown when any type stale)
- [ ] Per-type status grid (ok / stale / missing, from /api/data-quality)

## Analytics Tab
- [ ] Data pipeline reference table (static)
- [ ] Recovery score card + trend chart (range toggles: 7/14/30/90d)
- [ ] Sleep score card + trend chart
- [ ] Stress score card + trend chart
- [ ] Resting HR score card + trend chart
- [ ] Temperature trend chart (last 30d)
- [ ] Range toggle (7/14/30/90d) drives all chart queries

## Admin Tab
- [ ] Ring status card (battery, clock_drift_ms, firmware)
- [ ] Last sync summary
- [ ] Health check: DB, row counts, pending requests
- [ ] Clock alert: future_rows, future_hr
- [ ] Sync log table with pagination
- [ ] Sync requests queue (id, status, result, error)
- [ ] Sync-progress display

## Sync UX (shared)
- [ ] SyncProgressDialog — phase display (12 phases)
- [ ] Screen wake-lock during phone sync
- [ ] Toasts on sync start / complete / error
- [ ] Elapsed timer during sync

## Web Bluetooth (phone sync)
- [ ] 📱 BLE button (conditional on navigator.bluetooth)
- [ ] Ring connection via Web Bluetooth (Colmi service UUIDs)
- [ ] set_time command (send local time to ring)
- [ ] Battery fetch
- [ ] Temperature fetch (types 0x22–0x2C, skip 0x2A)
- [ ] SpO2 fetch (type 0x2A)
- [ ] HR fetch (type 0x15, multi-packet)
- [ ] Sleep fetch (type 0x27)
- [ ] Steps fetch (type 0x19)
- [ ] Stress fetch (type 0x25)
- [ ] HRV fetch (type 0x39, multi-packet)
- [ ] Goals fetch
- [ ] 12-phase progress UI during sync
- [ ] POST /api/mobile/sync with all records
- [ ] Error handling (connection lost, timeout)

## PWA
- [ ] Manifest + icons (192, 512, maskable, apple-180)
- [ ] Service worker: network-first /api/*, SWR CDN, cache-first static, network-only POST /api/mobile/sync
- [ ] Offline shell
- [ ] Install prompt
- [ ] Cache version bump on cutover
