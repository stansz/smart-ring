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
