import { useState } from "react";
import { DataPipeline } from "../components/analytics/DataPipeline";
import { ScoreCards } from "../components/analytics/ScoreCards";
import { TrendChart } from "../components/analytics/TrendChart";
import { Card } from "../components/ui";
import { useRecovery, useSleep, useStress, useRestingHr, useRawTemperature, useStrainTrend } from "../api/hooks";

const RANGES = [7, 14, 30, 90] as const;

export function AnalyticsTab() {
  const [range, setRange] = useState<number>(30);

  const { data: recovery } = useRecovery(range);
  const { data: sleep } = useSleep(range);
  const { data: stress } = useStress(range);
  const { data: restingHr } = useRestingHr(range);
  const { data: rawTemp } = useRawTemperature(range * 24, range * 48);
  const { data: strainTrend } = useStrainTrend(range);

  const hrvData = recovery?.map((r) => ({ day: r.day, value: r.z_score })) || [];
  const sleepData = sleep?.map((r) => ({ day: r.day, value: r.score })) || [];
  // Stress trend: compute daily_score as avg of morning/noon/evening (matches legacy)
  const stressData = stress?.map((r) => {
    const vals = [r.morning_rmssd, r.noon_rmssd, r.evening_rmssd].filter((v): v is number => v != null);
    return { day: r.day, value: vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null };
  }) || [];
  const rhrData = restingHr?.map((r) => ({ day: r.day, value: r.resting_hr })) || [];
  const strainData = strainTrend?.map((r) => ({ day: r.day, value: Number(r.strain_today) })) || [];

  const tempMap = new Map<string, { sum: number; n: number }>();
  for (const r of rawTemp || []) {
    const day = r.ts.slice(0, 10);
    const entry = tempMap.get(day) || { sum: 0, n: 0 };
    entry.sum += r.temp_c;
    entry.n += 1;
    tempMap.set(day, entry);
  }
  const tempData = [...tempMap.entries()].map(([day, { sum, n }]) => ({
    day,
    value: sum / n,
  }));

  return (
    <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      <DataPipeline />
      <ScoreCards />

      <Card className="p-6 mb-8">
        <div className="flex justify-between items-center mb-4">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">Trends</h2>
          <div className="flex space-x-1">
            {RANGES.map((d) => (
              <button
                key={d}
                onClick={() => setRange(d)}
                className={`px-3 py-2 sm:py-1 text-xs rounded transition ${
                  range === d
                    ? "bg-blue-600 text-white"
                    : "text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700"
                }`}
              >
                {d}d
              </button>
            ))}
          </div>
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
            <TrendChart data={strainData} title="Cardio Load / Strain Trend" description="Edwards TRIMP daily strain (0-21). Reflects cardiovascular load & training stress." color="#3b82f6" />
          </div>
        </div>
      </Card>

      {/* Research References */}
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 border border-gray-100 dark:border-gray-700">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-4">Research References</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs text-gray-600 dark:text-gray-400">
          <div>
            <p className="font-semibold text-gray-700 dark:text-gray-300">Sleep Quality</p>
            <p>Ohayon, M. M., et al. (2004). "Meta-analysis of quantitative sleep parameters." <em>Sleep</em>, 27(7), 1255-1273. (3,327 citations)</p>
          </div>
          <div>
            <p className="font-semibold text-gray-700 dark:text-gray-300">HRV Recovery</p>
            <p>Plews, D. J., et al. (2017). "Monitoring training with HRV." <em>Frontiers in Physiology</em>. Altini, M. (2021). <em>Sensors</em>, 21(7). (9M measurements)</p>
          </div>
          <div>
            <p className="font-semibold text-gray-700 dark:text-gray-300">Stress Classification</p>
            <p>Garmin/Firstbeat thresholds (0-25/26-50/51-75/76-100). <em>Frontiers in Physiology</em>, 2025, for circadian stress patterns.</p>
          </div>
          <div>
            <p className="font-semibold text-gray-700 dark:text-gray-300">Trapezoidal Scoring</p>
            <p>Inspired by Oura's reverse-engineered algorithms (Chheda). R²=0.846 correlation with Oura sleep scores.</p>
          </div>
          <div>
            <p className="font-semibold text-gray-700 dark:text-gray-300">Training Load & ACWR</p>
            <p>Gabbett, T. J. (2016). "The training-injury paradox: acute:chronic workload ratios." <em>Br J Sports Med</em>, 50(5), 273-275. Edwards TRIMP methodology for cardiovascular strain (0-21).</p>
          </div>
        </div>
      </div>
    </main>
  );
}
