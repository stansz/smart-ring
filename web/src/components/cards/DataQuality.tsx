import { useDataQuality } from "../../api/hooks";
import { todayKey } from "../../utils/date";

const TYPE_LABELS: Record<string, string> = {
  heart_rate: "Heart Rate",
  temperature: "Skin Temp",
  spo2: "SpO₂",
  hrv: "HRV",
  steps: "Steps",
  stress: "Stress",
};

export function DataQualityBanner() {
  const { data } = useDataQuality(3);
  if (!data) return null;

  const today = todayKey();
  const todayRows = data.filter((r) => r.day === today);
  const staleTypes = [...new Set(
    todayRows.filter((r) => r.status === "stale").map((r) => r.data_type)
  )];

  if (staleTypes.length === 0) return null;

  const names = staleTypes.map((t) => TYPE_LABELS[t] || t).join(", ");

  return (
    <div className="mb-6 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-lg px-4 py-3 flex items-start gap-3">
      <span className="text-amber-600 dark:text-amber-400 text-lg flex-shrink-0">⚠️</span>
      <div className="text-sm text-amber-800 dark:text-amber-300">
        <p className="font-medium">Data gap detected</p>
        <p className="text-amber-700 dark:text-amber-400">
          {names} — no data today despite ring being worn. If your ring has been toggled, the logger will resume on the next sync.
        </p>
      </div>
    </div>
  );
}

export function DataQualityGrid() {
  const { data } = useDataQuality(3);
  if (!data || data.length === 0) return null;

  const today = todayKey();
  const todayRows = data.filter((r) => r.day === today);

  const statusColor = (status: string) =>
    status === "ok" ? "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300" :
    status === "stale" ? "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-300" :
    "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-300";

  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow border border-gray-100 dark:border-gray-700 p-6 mb-8">
      <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-3">Data Quality</h2>
      <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-6 gap-3">
        {todayRows.map((r) => (
          <div key={r.data_type} className="text-center p-2 rounded-lg bg-gray-50 dark:bg-gray-700/50">
            <p className="text-xs text-gray-500 dark:text-gray-400">{TYPE_LABELS[r.data_type] || r.data_type}</p>
            <span className={`text-[10px] px-1.5 py-0.5 rounded mt-1 inline-block ${statusColor(r.status)}`}>
              {r.status}
            </span>
            <p className="text-xs font-mono text-gray-400 dark:text-gray-500 mt-1">{r.sample_count}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
