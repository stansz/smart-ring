/**
 * Analytics tab — trends + time-scale control.
 *
 * Design (Phase 1 of the analytics rework):
 *   - One shared `{start, end}` window drives every trend chart.
 *   - Presets (3/7/14/30/90/180d) and a custom date-range picker set the window.
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

export function AnalyticsTab() {
  const today = todayKey();
  const defaultStart = (() => {
    const d = new Date();
    d.setDate(d.getDate() - 30);
    return dateKey(d);
  })();

  const [window, setWindow] = useState<{ start: string; end: string }>({
    start: defaultStart,
    end: today,
  });

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

        <div className="space-y-6">
          <TrendChart data={hrvData} title="HRV Recovery Trend" description="Z-score vs 7-day baseline. Positive = recovering well. Negative = under strain." color="#8b5cf6" />
          <div className="border-t border-gray-100 dark:border-gray-700 pt-4">
            <TrendChart data={sleepData} title="Sleep Quality Trend" description="5-component score (0-100). Higher = better sleep." color="#6366f1" />
          </div>
          <div className="border-t border-gray-100 dark:border-gray-700 pt-4">
            <TrendChart data={stressData} title="Stress Trend" description="Weighted daily score. Lower = more relaxed." color="#f59e0b" />
          </div>
          <div className="border-t border-gray-100 dark:border-gray-700 pt-4">
            <TrendChart data={rhrData} title="Resting HR Trend" description="Overnight average (1-5 AM). Lower = better recovery." color="#3b82f6" />
          </div>
          <div className="border-t border-gray-100 dark:border-gray-700 pt-4">
            <TrendChart data={tempData} title="Skin Temperature Trend" description="Daily average °C. Shows overnight baseline over time." color="#f43f5e" />
          </div>
          <div className="border-t border-gray-100 dark:border-gray-700 pt-4">
            <TrendChart data={spo2Data} title="SpO₂ Trend" description="Daily average blood oxygen %. Higher = better oxygenation." color="#10b981" />
          </div>
          <div className="border-t border-gray-100 dark:border-gray-700 pt-4">
            <TrendChart data={stepsData} title="Steps Trend" description="Daily step count." color="#3b82f6" />
          </div>
          <div className="border-t border-gray-100 dark:border-gray-700 pt-4">
            <TrendChart data={strainData} title="Cardio Load / Strain Trend" description="Edwards TRIMP daily strain (0-21). Reflects cardiovascular load & training stress." color="#3b82f6" />
          </div>
        </div>
      </Card>

      <HelpPopover />
    </main>
  );
}
