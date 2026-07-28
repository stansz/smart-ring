import { useRecovery, useReadiness } from "../../api/hooks";
import { CountUp, FreshDot, Skeleton } from "../ui";

interface RecoveryCardProps {
  selectedKey: string;
}

export function RecoveryCard({ selectedKey }: RecoveryCardProps) {
  const { data: recoveryRows, dataUpdatedAt, isLoading, isError, refetch } = useRecovery(30);
  const { data: readinessRows } = useReadiness(30);

  const recoveryMatch = recoveryRows?.find((r) => r.day === selectedKey);
  const readinessMatch = readinessRows?.find((r) => r.day === selectedKey);

  // Hero uses today's daily average HRV (rmssd from daily_recovery) — stable,
  // already computed by analytics. No raw single-sample noise. This is a
  // running average that updates with each analytics pass as more samples
  // accumulate today; for past days it's the final daily average.
  const hrvAvg = recoveryMatch?.rmssd ?? null;

  if (isLoading) {
    return (
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 border border-gray-100 dark:border-gray-700">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-4">💓 Recovery</h2>
        <Skeleton className="h-32" />
      </div>
    );
  }

  if (isError) {
    return (
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 border border-gray-100 dark:border-gray-700">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-4">💓 Recovery</h2>
        <p className="text-sm text-rose-500">Failed to load recovery data.</p>
        <button onClick={() => refetch()} className="text-xs text-blue-600 mt-2 underline">Retry</button>
      </div>
    );
  }

  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 border border-gray-100 dark:border-gray-700 flex flex-col">
      <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-4">💓 Recovery<FreshDot updatedAt={dataUpdatedAt} /></h2>

      <div className="flex flex-col sm:flex-row sm:items-center gap-4 sm:gap-10">
        <div className="text-center flex-shrink-0">
          <p className={`text-4xl font-bold ${hrvAvg != null && hrvAvg >= 45 ? "text-green-600 dark:text-green-400" : hrvAvg != null && hrvAvg >= 30 ? "text-amber-600 dark:text-amber-400" : "text-red-600 dark:text-red-400"}`}>
            {hrvAvg != null ? <CountUp value={hrvAvg} format={(n) => `${Math.round(n)}ms`} /> : "—"}
          </p>
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">today's avg</p>
        </div>
        <div className="flex-1 grid grid-cols-1 sm:grid-cols-2 gap-x-8 gap-y-2">
          {recoveryMatch?.baseline_rmssd != null && (
            <div className="flex gap-3 text-base items-baseline">
              <span className="w-32 flex-shrink-0 text-gray-500 dark:text-gray-400">7-day baseline</span>
              <span className="font-mono text-gray-700 dark:text-gray-300">{recoveryMatch.baseline_rmssd}ms</span>
            </div>
          )}
          {readinessMatch?.resting_hr != null && (
            <div className="flex gap-3 text-base items-baseline">
              <span className="w-32 sm:w-24 flex-shrink-0 text-gray-500 dark:text-gray-400">Resting HR</span>
              <span className="font-mono text-gray-700 dark:text-gray-300">{readinessMatch.resting_hr} bpm</span>
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
          {recoveryMatch?.readiness_text != null && (
            <div className="flex gap-3 text-base items-baseline">
              <span className="w-32 sm:w-24 flex-shrink-0 text-gray-500 dark:text-gray-400">Recovery</span>
              <span className={`font-medium ${recoveryMatch.z_score != null && recoveryMatch.z_score >= 0.5 ? "text-green-600 dark:text-green-400" : recoveryMatch.z_score != null && recoveryMatch.z_score >= -0.5 ? "text-gray-600 dark:text-gray-300" : "text-red-500 dark:text-red-400"}`}>
                {recoveryMatch.readiness_text}
              </span>
            </div>
          )}
        </div>
      </div>

      {/* Footer — what this card means. Pinned to the bottom (mt-auto) so it
          fills the card height (grid stretches this card to match its neighbour).
          Grounded in the Plews/Altini z-score framework — see docs/RESEARCH.md. */}
      <div className="mt-auto pt-4 border-t border-gray-100 dark:border-gray-700">
        <p className="text-xs text-gray-500 dark:text-gray-400 leading-relaxed">
          HRV (heart rate variability) reflects parasympathetic "rest and digest" nervous-system activity. We compare today against your own rolling 7-day baseline.
        </p>
        <p className="text-xs text-gray-500 dark:text-gray-400 leading-relaxed mt-1.5">
          Z-score ≥ +0.5 means recovering well; ≤ −0.5 suggests accumulated strain.
        </p>
      </div>
    </div>
  );
}
