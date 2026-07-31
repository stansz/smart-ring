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

// Default to the ring source only — that's the canonical collector and
// matches the pre-Phase-0 single-source banner UX. When Garmin is
// added in Phase 1, this can be extended to surface garmin-specific
// staleness (e.g. `useDataQuality(3, "garmin")`) alongside the ring
// banner, or rendered as a second banner.
const PRIMARY_SOURCE = "ring";

export function DataQualityBanner() {
  const { data } = useDataQuality(3, PRIMARY_SOURCE);
  if (!data) return null;

  const today = todayKey();
  const todayRows = data.filter((r) => r.day === today && r.source === PRIMARY_SOURCE);
  const staleRows = todayRows.filter((r) => r.status === "stale");
  const staleTypes = [...new Set(staleRows.map((r) => r.data_type))];

  if (staleTypes.length === 0) return null;

  const names = staleTypes.map((t) => TYPE_LABELS[t] || t).join(", ");

  // Two paths lead to "stale":
  //  - cnt == 0: total absence today (logger stall, ring toggle, etc.)
  //  - cnt  > 0: has samples but last_ts lags peers (collector issue, firmware delay)
  // Pick the remedy text based on which case we're in.
  const allMissing = staleRows.every((r) => (r.sample_count ?? 0) === 0);
  const allLagging = staleRows.every((r) => (r.sample_count ?? 0) > 0);

  let description: string;
  if (allMissing) {
    description = "no samples today despite ring being worn. If your ring has been toggled, the logger will resume on the next sync.";
  } else if (allLagging) {
    description = "stale today — last update is hours behind other metrics. The next sync should catch up; if it persists, check the collector.";
  } else {
    description = "incomplete or stale today despite ring being worn. The next sync should catch up.";
  }

  return (
    <div className="mb-6 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-lg px-4 py-3 flex items-start gap-3">
      <span className="text-amber-600 dark:text-amber-400 text-lg flex-shrink-0">⚠️</span>
      <div className="text-sm text-amber-800 dark:text-amber-300">
        <p className="font-medium">Data gap detected</p>
        <p className="text-amber-700 dark:text-amber-400">
          {names} — {description}
        </p>
      </div>
    </div>
  );
}
