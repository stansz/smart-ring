/**
 * Analytics tab — trends + time-scale control + click-to-zoom.
 *
 * Design (analytics rework, Phases 1-2):
 *   - One shared `{start, end}` window drives every trend chart.
 *   - Presets (3/7/14/30/90/180d) and a custom date-range picker set the window.
 *   - Click a point on any chart → narrows the shared window to 1/3 its current
 *     width, centered on the clicked day. Floors at 3d. All 8 charts re-render
 *     together, so you stay aligned across metrics.
 *   - Breadcrumb + Reset button appear whenever the window isn't a recognized
 *     preset (zoomed-in or custom range). Reset returns to the 30d default.
 *   - All daily-aggregate endpoints fetch the max span (180d) once; filtering
 *     to the window is client-side. Keeps the TanStack Query cache stable
 *     across window changes and avoids per-window refetches.
 *   - Raw timestamped data (temp, SpO2) is bucketed to daily averages by the
 *     `aggregateByDay` helper — uses `dayKeyFromTs` so local-day bucketing is
 *     correct near midnight (the old `ts.slice(0,10)` pattern was wrong after
 *     ~5pm Pacific).
 *
 * Score cards and the always-visible methodology table have been removed —
 * score cards duplicated the Dashboard + the rightmost point of each trend
 * below, and the methodology content moved into `HelpPopover`.
 *
 * Phase 3 (not yet implemented) will switch each trend to an hourly raw
 * signal when the window narrows to a single day.
 */

import { useState } from "react";
import { HelpPopover } from "../components/analytics/HelpPopover";
import { TimeScaleControls } from "../components/analytics/TimeScaleControls";
import { TrendChart } from "../components/analytics/TrendChart";
import { Card } from "../components/ui";
import {
  useRecovery, useSleep, useStress, useRestingHr,
  useRawTemperature, useRawSpo2, useStrainTrend, useDailyActivity,
} from "../api/hooks";
import { todayKey, dateKey, aggregateByDay } from "../utils/date";

const MAX_FETCH_DAYS = 180;
const ZOOM_FLOOR_DAYS = 3;
const DEFAULT_WINDOW_DAYS = 30;
const PRESETS = [3, 7, 14, 30, 90, 180] as const;

function defaultWindow(today: string) {
  const d = new Date(today + "T00:00:00");
  d.setDate(d.getDate() - DEFAULT_WINDOW_DAYS);
  return { start: dateKey(d), end: today };
}

/** Which preset (if any) matches the current window. Null = custom range or zoomed-in. */
function activePreset(start: string, end: string, today: string): number | null {
  if (end !== today) return null;
  const days = Math.round(
    (new Date(today + "T00:00:00").getTime() - new Date(start + "T00:00:00").getTime()) / 86400000,
  );
  return (PRESETS as readonly number[]).find((p) => p === days) ?? null;
}

function formatShort(key: string): string {
  return new Date(key + "T00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

export function AnalyticsTab() {
  const today = todayKey();
  const [window, setWindow] = useState<{ start: string; end: string }>(defaultWindow(today));

  // Fetch the max span once. Filter client-side to the window so window
  // changes don't trigger refetches.
  const { data: recovery } = useRecovery(MAX_FETCH_DAYS);
  const { data: sleep } = useSleep(MAX_FETCH_DAYS);
  const { data: stress } = useStress(MAX_FETCH_DAYS);
  const { data: restingHr } = useRestingHr(MAX_FETCH_DAYS);
  const { data: strainTrend } = useStrainTrend(MAX_FETCH_DAYS);
  const { data: dailyActivity } = useDailyActivity(MAX_FETCH_DAYS);
  const { data: rawTemp } = useRawTemperature(MAX_FETCH_DAYS * 24, 10000);
  const { data: rawSpo2 } = useRawSpo2(MAX_FETCH_DAYS * 24, 3000);

  // ── Zoom state ─────────────────────────────────────────────────────────────
  // Click a point on any chart → narrows the shared window to 1/3 its current
  // width, centered on the clicked day. Floors at 3d (can't go narrower).
  // `isZoomedIn` is true whenever the window isn't a recognized preset — used
  // to show the breadcrumb + Reset button.
  const onPointClick = (day: string) => {
    const currentDays = Math.round(
      (new Date(window.end + "T00:00:00").getTime() - new Date(window.start + "T00:00:00").getTime()) / 86400000,
    );
    if (currentDays <= ZOOM_FLOOR_DAYS) return;
    const newHalf = Math.max(1, Math.round(currentDays / 6));
    const clicked = new Date(day + "T00:00:00");
    const newStart = new Date(clicked);
    newStart.setDate(newStart.getDate() - newHalf);
    const newEnd = new Date(clicked);
    newEnd.setDate(newEnd.getDate() + newHalf);
    // Clamp to [today - 180d, today]
    const earliest = new Date();
    earliest.setDate(earliest.getDate() - MAX_FETCH_DAYS);
    const todayDate = new Date();
    if (newStart < earliest) newStart.setTime(earliest.getTime());
    if (newEnd > todayDate) newEnd.setTime(todayDate.getTime());
    setWindow({ start: dateKey(newStart), end: dateKey(newEnd) });
  };

  const preset = activePreset(window.start, window.end, today);
  const isZoomedIn = preset === null;
  const resetToDefault = () => setWindow(defaultWindow(today));

  // Filter a daily-keyed row array to the current window.
  const inWindow = <T extends { day: string }>(rows: T[] | undefined | null): T[] =>
    (rows ?? []).filter((r) => r.day >= window.start && r.day <= window.end);

  // ── Build trend data ───────────────────────────────────────────────────────
  // Daily-aggregate metrics: map → filter.
  const hrvData = inWindow(recovery).map((r) => ({ day: r.day, value: r.z_score ?? null }));
  const sleepData = inWindow(sleep).map((r) => ({ day: r.day, value: r.score ?? null }));
  const stressData = inWindow(stress).map((r) => {
    const vals = [r.morning_rmssd, r.noon_rmssd, r.evening_rmssd].filter((v): v is number => v != null);
    return { day: r.day, value: vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null };
  });
  const rhrData = inWindow(restingHr).map((r) => ({ day: r.day, value: r.resting_hr ?? null }));
  const strainData = inWindow(strainTrend).map((r) => ({ day: r.day, value: r.strain_today }));
  const stepsData = inWindow(dailyActivity).map((r) => ({ day: r.day, value: r.steps_total }));

  // Raw timestamped metrics: aggregate to daily averages → filter.
  const tempData = aggregateByDay(rawTemp, "temp_c").filter((r) => r.day >= window.start && r.day <= window.end);
  const spo2Data = aggregateByDay(rawSpo2, "spo2_pct").filter((r) => r.day >= window.start && r.day <= window.end);

  return (
    <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      <Card className="p-6 mb-8">
        <div className="flex flex-wrap justify-between items-center gap-4 mb-4">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">Trends</h2>
          <TimeScaleControls
            start={window.start}
            end={window.end}
            onChange={(start, end) => setWindow({ start, end })}
          />
        </div>

        {isZoomedIn && (
          <div className="flex items-center justify-between gap-3 mb-4 px-3 py-2 rounded bg-blue-50 dark:bg-blue-950/40 border border-blue-200 dark:border-blue-800">
            <p className="text-xs text-blue-700 dark:text-blue-300">
              <span className="font-medium">Zoomed in</span>
              <span className="mx-2 text-blue-400 dark:text-blue-500">·</span>
              <span>Showing {formatShort(window.start)} – {formatShort(window.end)}</span>
              <span className="mx-2 text-blue-400 dark:text-blue-500">·</span>
              <span className="text-blue-600/70 dark:text-blue-400/70">Click any chart point to zoom further</span>
            </p>
            <button
              onClick={resetToDefault}
              className="flex-shrink-0 text-xs px-2 py-1 rounded bg-white dark:bg-gray-800 border border-blue-200 dark:border-blue-800 text-blue-700 dark:text-blue-300 hover:bg-blue-100 dark:hover:bg-blue-900/50 transition"
            >
              Reset
            </button>
          </div>
        )}

        <div className="space-y-6">
          <TrendChart data={hrvData} title="HRV Recovery Trend" description="Z-score vs 7-day baseline. Positive = recovering well. Negative = under strain." color="#8b5cf6" onPointClick={onPointClick} />
          <div className="border-t border-gray-100 dark:border-gray-700 pt-4">
            <TrendChart data={sleepData} title="Sleep Quality Trend" description="5-component score (0-100). Higher = better sleep." color="#6366f1" onPointClick={onPointClick} />
          </div>
          <div className="border-t border-gray-100 dark:border-gray-700 pt-4">
            <TrendChart data={stressData} title="Stress Trend" description="Weighted daily score. Lower = more relaxed." color="#f59e0b" onPointClick={onPointClick} />
          </div>
          <div className="border-t border-gray-100 dark:border-gray-700 pt-4">
            <TrendChart data={rhrData} title="Resting HR Trend" description="Overnight average (1-5 AM). Lower = better recovery." color="#3b82f6" onPointClick={onPointClick} />
          </div>
          <div className="border-t border-gray-100 dark:border-gray-700 pt-4">
            <TrendChart data={tempData} title="Skin Temperature Trend" description="Daily average °C. Shows overnight baseline over time." color="#f43f5e" onPointClick={onPointClick} />
          </div>
          <div className="border-t border-gray-100 dark:border-gray-700 pt-4">
            <TrendChart data={spo2Data} title="SpO₂ Trend" description="Daily average blood oxygen %. Higher = better oxygenation." color="#10b981" onPointClick={onPointClick} />
          </div>
          <div className="border-t border-gray-100 dark:border-gray-700 pt-4">
            <TrendChart data={stepsData} title="Steps Trend" description="Daily step count." color="#3b82f6" onPointClick={onPointClick} />
          </div>
          <div className="border-t border-gray-100 dark:border-gray-700 pt-4">
            <TrendChart data={strainData} title="Cardio Load / Strain Trend" description="Edwards TRIMP daily strain (0-21). Reflects cardiovascular load & training stress." color="#3b82f6" onPointClick={onPointClick} />
          </div>
        </div>
      </Card>

      <HelpPopover />
    </main>
  );
}
