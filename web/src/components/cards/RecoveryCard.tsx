import { useRecovery, useRawHrv, useStress, useReadiness } from "../../api/hooks";

interface RecoveryCardProps {
  selectedKey: string;
}

export function RecoveryCard({ selectedKey }: RecoveryCardProps) {
  const { data: recoveryRows } = useRecovery(30);
  const { data: hrvRaw } = useRawHrv(168, 500);
  const { data: stressRows } = useStress(30);
  const { data: readinessRows } = useReadiness(30);

  const recoveryMatch = recoveryRows?.find((r) => r.day === selectedKey);
  const stressMatch = stressRows?.find((r) => r.day === selectedKey);
  const readinessMatch = readinessRows?.find((r) => r.day === selectedKey);

  const hrvToday = hrvRaw?.filter((r) => r.ts.slice(0, 10) === selectedKey) || [];
  const hrvLatest = hrvToday.length > 0 ? hrvToday[0].hrv_value : null;
  const hrvRangeVal = hrvToday.length > 0
    ? { min: Math.min(...hrvToday.map((r) => r.hrv_value)), max: Math.max(...hrvToday.map((r) => r.hrv_value)) }
    : null;

  const stressVals = [
    stressMatch?.morning_rmssd, stressMatch?.noon_rmssd, stressMatch?.evening_rmssd,
  ].filter((v): v is number => v != null);
  const stressDailyAvg = stressVals.length > 0 ? stressVals.reduce((a, b) => a + b) / stressVals.length : null;

  const sortedDays = stressRows?.map((r) => r.day).sort() || [];
  const todayIdx = sortedDays.indexOf(selectedKey);
  let stressTrendText = "";
  if (todayIdx > 0 && stressDailyAvg != null) {
    const prev = stressRows?.find((r) => r.day === sortedDays[todayIdx - 1]);
    const prevVals = [prev?.morning_rmssd, prev?.noon_rmssd, prev?.evening_rmssd].filter((v): v is number => v != null);
    if (prevVals.length > 0) {
      const prevAvg = prevVals.reduce((a, b) => a + b) / prevVals.length;
      const diff = Math.round(stressDailyAvg - prevAvg);
      if (diff !== 0) stressTrendText = (diff > 0 ? "↑+" : "↓") + Math.abs(diff) + " from yesterday";
    }
  }

  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 border border-gray-100 dark:border-gray-700">
      <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-4">💓 Recovery</h2>
      <div className="flex items-center gap-6">
        <div className="text-center flex-shrink-0">
          <p className={`text-4xl font-bold ${hrvLatest != null && hrvLatest >= 45 ? "text-green-600" : hrvLatest != null && hrvLatest >= 30 ? "text-amber-600" : "text-red-600"}`}>
            {hrvLatest != null ? hrvLatest + "ms" : "—"}
          </p>
          <p className="text-xs text-gray-400 dark:text-gray-500 mt-1">latest HRV</p>
        </div>
        <div className="flex-1 space-y-2">
          {recoveryMatch?.baseline_rmssd != null && (
            <div className="flex justify-between text-sm">
              <span className="text-gray-500 dark:text-gray-400">7-day baseline</span>
              <span className="font-mono text-gray-700 dark:text-gray-300">{recoveryMatch.baseline_rmssd}ms</span>
            </div>
          )}
          {recoveryMatch?.z_score != null && (
            <div className="flex justify-between text-sm">
              <span className="text-gray-500 dark:text-gray-400">Z-score</span>
              <span className={`font-mono ${recoveryMatch.z_score >= 0.5 ? "text-green-600" : recoveryMatch.z_score >= -0.5 ? "text-gray-600 dark:text-gray-300" : "text-red-500"}`}>
                {recoveryMatch.z_score > 0 ? "+" : ""}{recoveryMatch.z_score.toFixed(2)}
              </span>
            </div>
          )}
          {hrvRangeVal != null && (
            <div className="flex justify-between text-sm">
              <span className="text-gray-500 dark:text-gray-400">Range</span>
              <span className="font-mono text-gray-700 dark:text-gray-300">{hrvRangeVal.min}–{hrvRangeVal.max}ms</span>
            </div>
          )}
          {readinessMatch?.resting_hr != null && (
            <div className="flex justify-between text-sm">
              <span className="text-gray-500 dark:text-gray-400">Resting HR</span>
              <span className="font-mono text-gray-700 dark:text-gray-300">{readinessMatch.resting_hr} bpm</span>
            </div>
          )}
          {stressMatch?.classification != null && (
            <div className="flex justify-between text-sm">
              <span className="text-gray-500 dark:text-gray-400">Stress</span>
              <span className="text-right">
                <span>
                  <span className={`font-bold ${stressDailyAvg != null && stressDailyAvg <= 25 ? "text-green-600" : stressDailyAvg != null && stressDailyAvg <= 50 ? "text-gray-600 dark:text-gray-300" : stressDailyAvg != null && stressDailyAvg <= 75 ? "text-amber-600" : "text-red-600"}`}>
                    {stressDailyAvg != null ? Math.round(stressDailyAvg) : ""}
                  </span>
                  <span className={`font-medium capitalize ml-1 ${stressMatch.classification === "relaxed" ? "text-green-600" : stressMatch.classification === "low" ? "text-gray-500" : stressMatch.classification === "medium" ? "text-amber-600" : "text-red-600"}`}>
                    {stressMatch.classification}
                  </span>
                </span>
                {stressTrendText && <p className="text-xs text-gray-400 dark:text-gray-500">{stressTrendText}</p>}
              </span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
