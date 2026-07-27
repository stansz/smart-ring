import { useRecovery, useSleep, useStress, useRestingHr } from "../../api/hooks";

export function ScoreCards() {
  const { data: recovery } = useRecovery(7);
  const { data: sleep } = useSleep(7);
  const { data: stress } = useStress(7);
  const { data: restingHr } = useRestingHr(7);

  const latestRecovery = recovery?.[0];
  const latestSleep = sleep?.[0];
  // Stress classification uses the latest day's values as summary
  const latestStress = stress?.[0];
  // daily_score = avg of morning/noon/evening stress values
  const stressDailyScore = latestStress
    ? (() => {
        const vals = [latestStress.morning_rmssd, latestStress.noon_rmssd, latestStress.evening_rmssd].filter((v): v is number => v != null);
        return vals.length ? Math.round(vals.reduce((a, b) => a + b, 0) / vals.length) : null;
      })()
    : null;
  const latestResting = restingHr?.[0];

  const recColor = (t: string | null) =>
    t?.includes("Excellent") || t?.includes("Good") ? "text-green-600" :
    t?.includes("Fair") ? "text-amber-600" : "text-red-500";

  const sleepColor = (s: number | null | undefined) =>
    s != null && s >= 80 ? "text-green-600 dark:text-green-400" :
    s != null && s >= 60 ? "text-amber-600 dark:text-amber-400" : "text-red-600 dark:text-red-400";

  const stressColor = (c: string | null) =>
    c === "relaxed" ? "text-green-600 dark:text-green-400" :
    c === "low" ? "text-gray-600 dark:text-gray-300" :
    c === "medium" ? "text-amber-600 dark:text-amber-400" : "text-red-600 dark:text-red-400";

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
      {/* Recovery */}
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-5 border border-gray-100 dark:border-gray-700">
        <p className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide">Recovery</p>
        <p className="text-2xl font-bold mt-1 text-gray-900 dark:text-gray-100">
          {latestRecovery?.z_score != null
            ? `${latestRecovery.z_score > 0 ? "+" : ""}${latestRecovery.z_score.toFixed(2)}`
            : "—"}
        </p>
        <p className={`text-sm font-semibold mt-1 ${recColor(latestRecovery?.readiness_text ?? null)}`}>
          {latestRecovery?.readiness_text || "—"}
        </p>
        <details className="mt-2 text-xs text-gray-500 dark:text-gray-400">
          <summary className="cursor-pointer">How this works</summary>
          <p className="mt-1 pl-3 border-l-2 border-gray-200 dark:border-gray-600">
            HRV values are ln-transformed to normalize distribution. Z-score = (today − 7-day mean) / 7-day SD. Readiness labels follow Altini/Plews thresholds: Excellent &gt;1.0, Good &gt;0.5, Fair &gt;−0.5, Poor &gt;−1.0, Very Poor below −1.0.
          </p>
        </details>
      </div>

      {/* Sleep */}
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-5 border border-gray-100 dark:border-gray-700">
        <p className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide">Sleep Quality</p>
        <p className={`text-2xl font-bold mt-1 ${sleepColor(latestSleep?.score)}`}>
          {latestSleep?.score != null ? `${Math.round(latestSleep.score)}/100` : "—"}
        </p>
        <div className="mt-2 space-y-1 text-xs text-gray-500 dark:text-gray-400">
          <div className="flex justify-between"><span>Duration</span><span className="font-mono">{latestSleep?.total_sleep_minutes ? `${Math.floor(latestSleep.total_sleep_minutes / 60)}h ${latestSleep.total_sleep_minutes % 60}m` : "—"}</span></div>
          <div className="flex justify-between"><span>Deep sleep</span><span className="font-mono">{latestSleep?.deep_pct != null ? `${Math.round(latestSleep.deep_pct)}%` : "—"}</span></div>
          <div className="flex justify-between"><span>REM sleep</span><span className="font-mono">{latestSleep?.rem_pct != null ? `${Math.round(latestSleep.rem_pct)}%` : "—"}</span></div>
        </div>
        <details className="mt-2 text-xs text-gray-500 dark:text-gray-400">
          <summary className="cursor-pointer">How this works</summary>
          <p className="mt-1 pl-3 border-l-2 border-gray-200 dark:border-gray-600">
            5-component score (0-100): 30% Duration (7-9h optimal), 25% Efficiency, 25% Architecture (deep 13-23%, REM 20-25% per Ohayon 2004 norms), 15% Continuity, 5% Latency. Trapezoidal scoring — full credit in optimal range, linear decline outside.
          </p>
        </details>
      </div>

      {/* Stress */}
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-5 border border-gray-100 dark:border-gray-700">
        <p className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide">Stress</p>
        <p className={`text-2xl font-bold mt-1 ${stressColor(latestStress?.classification ?? null)}`}>
          {stressDailyScore != null ? stressDailyScore : "—"}
        </p>
        <p className={`text-sm font-semibold mt-1 capitalize ${stressColor(latestStress?.classification ?? null)}`}>
          {latestStress?.classification || "—"}
        </p>
        <details className="mt-2 text-xs text-gray-500 dark:text-gray-400">
          <summary className="cursor-pointer">How this works</summary>
          <p className="mt-1 pl-3 border-l-2 border-gray-200 dark:border-gray-600">
            Weighted daily score: 0.5×daytime avg + 0.3×peak sustained (2h) + 0.2×overnight avg. Classified with Garmin/Firstbeat thresholds: 0-25 relaxed, 26-50 low, 51-75 medium, 76-100 high.
          </p>
        </details>
      </div>

      {/* Resting HR */}
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-5 border border-gray-100 dark:border-gray-700">
        <p className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide">Resting HR</p>
        <p className="text-2xl font-bold mt-1 text-blue-600 dark:text-blue-400">
          {latestResting?.resting_hr != null ? `${Math.round(latestResting.resting_hr)} bpm` : "—"}
        </p>
        <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">Overnight avg (1-5 AM)</p>
        <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">{latestResting?.day || ""}</p>
        <details className="mt-2 text-xs text-gray-500 dark:text-gray-400">
          <summary className="cursor-pointer">How this works</summary>
          <p className="mt-1 pl-3 border-l-2 border-gray-200 dark:border-gray-600">
            Average of all raw HR readings between 1:00–5:00 AM local time.
          </p>
        </details>
      </div>
    </div>
  );
}
