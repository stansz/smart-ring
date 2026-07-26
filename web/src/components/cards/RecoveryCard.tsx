import { useRecovery, useRawHrv, useReadiness } from "../../api/hooks";

interface RecoveryCardProps {
  selectedKey: string;
}

export function RecoveryCard({ selectedKey }: RecoveryCardProps) {
  const { data: recoveryRows } = useRecovery(30);
  const { data: hrvRaw } = useRawHrv(168, 500);
  const { data: readinessRows } = useReadiness(30);

  const recoveryMatch = recoveryRows?.find((r) => r.day === selectedKey);
  const readinessMatch = readinessRows?.find((r) => r.day === selectedKey);

  const hrvToday = hrvRaw?.filter((r) => r.ts.slice(0, 10) === selectedKey) || [];
  // FIX: pick the most recent sample by timestamp (desc), not hrvToday[0] which is
  // insertion order — previously mislabeled "latest HRV" while showing the first
  // sample of the day. ISO ts sorts chronologically.
  const hrvSorted = [...hrvToday].sort((a, b) => (a.ts < b.ts ? 1 : a.ts > b.ts ? -1 : 0));
  const hrvLatest = hrvSorted.length > 0 ? hrvSorted[0].hrv_value : null;
  const hrvRangeVal = hrvToday.length > 0
    ? { min: Math.min(...hrvToday.map((r) => r.hrv_value)), max: Math.max(...hrvToday.map((r) => r.hrv_value)) }
    : null;

  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 border border-gray-100 dark:border-gray-700 flex flex-col">
      <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-4">💓 Recovery</h2>

      {/* Hero HRV (top on mobile, left on desktop) + 2-column stat grid.
          Stacks vertically on narrow screens to avoid overflow. */}
      <div className="flex flex-col sm:flex-row sm:items-center gap-4 sm:gap-10">
        <div className="text-center flex-shrink-0">
          <p className={`text-4xl font-bold ${hrvLatest != null && hrvLatest >= 45 ? "text-green-600 dark:text-green-400" : hrvLatest != null && hrvLatest >= 30 ? "text-amber-600 dark:text-amber-400" : "text-red-600 dark:text-red-400"}`}>
            {hrvLatest != null ? hrvLatest + "ms" : "—"}
          </p>
          <p className="text-xs text-gray-400 dark:text-gray-500 mt-1">latest HRV</p>
        </div>
        <div className="flex-1 grid grid-cols-1 sm:grid-cols-2 gap-x-8 gap-y-2">
          {recoveryMatch?.baseline_rmssd != null && (
            <div className="flex gap-3 text-base items-baseline">
              <span className="w-32 flex-shrink-0 text-gray-500 dark:text-gray-400">7-day baseline</span>
              <span className="font-mono text-gray-700 dark:text-gray-300">{recoveryMatch.baseline_rmssd}ms</span>
            </div>
          )}
          {hrvRangeVal != null && (
            <div className="flex gap-3 text-base items-baseline">
              <span className="w-32 sm:w-24 flex-shrink-0 text-gray-500 dark:text-gray-400">Range</span>
              <span className="font-mono text-gray-700 dark:text-gray-300">{hrvRangeVal.min}–{hrvRangeVal.max}ms</span>
            </div>
          )}
          {recoveryMatch?.z_score != null && (
            <div className="flex gap-3 text-base items-baseline">
              <span className="w-32 flex-shrink-0 text-gray-500 dark:text-gray-400">Z-score</span>
              <span className={`font-mono ${recoveryMatch.z_score >= 0.5 ? "text-green-600 dark:text-green-400" : recoveryMatch.z_score >= -0.5 ? "text-gray-600 dark:text-gray-300" : "text-red-500 dark:text-red-400"}`}>
                {recoveryMatch.z_score > 0 ? "+" : ""}{recoveryMatch.z_score.toFixed(2)}
              </span>
            </div>
          )}
          {readinessMatch?.resting_hr != null && (
            <div className="flex gap-3 text-base items-baseline">
              <span className="w-32 sm:w-24 flex-shrink-0 text-gray-500 dark:text-gray-400">Resting HR</span>
              <span className="font-mono text-gray-700 dark:text-gray-300">{readinessMatch.resting_hr} bpm</span>
            </div>
          )}
        </div>
      </div>

      {/* Footer — what this card means. Pinned to the bottom (mt-auto) so it
          fills the card height (grid stretches this card to match its neighbour).
          Grounded in the Plews/Altini z-score framework — see docs/RESEARCH.md. */}
      <div className="mt-auto pt-4 border-t border-gray-100 dark:border-gray-700">
        <p className="text-xs text-gray-400 dark:text-gray-500 leading-relaxed">
          HRV (heart rate variability) reflects parasympathetic "rest and digest" nervous-system activity. We compare today against your own rolling 7-day baseline.
        </p>
        <p className="text-xs text-gray-400 dark:text-gray-500 leading-relaxed mt-1.5">
          Z-score ≥ +0.5 means recovering well; ≤ −0.5 suggests accumulated strain.
        </p>
      </div>
    </div>
  );
}
