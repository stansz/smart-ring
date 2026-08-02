import { useDataQuality } from "../../api/hooks";
import { todayKey } from "../../utils/date";

const TYPES = [
  { key: "heart_rate", label: "HR" },
  { key: "hrv", label: "HRV" },
  { key: "steps", label: "Steps" },
  { key: "spo2", label: "SpO₂" },
  { key: "stress", label: "Stress" },
  { key: "temperature", label: "Temp" },
] as const;

const REASON_HINT: Record<string, string> = {
  ok: "Fresh",
  absent: "No samples today while ring looks worn",
  lag: "Last update older than expected",
  hr_logger_stall: "HR frozen while other metrics still update",
  temp_pending: "Temp publishes completed days only — normal",
  not_worn: "Ring appears off / not recently measuring",
  stress_sparse_ok: "Stress not due yet today",
};

function relativeAge(ts: string | null | undefined): string {
  if (!ts) return "no data";
  const ms = Date.now() - new Date(ts).getTime();
  if (Number.isNaN(ms)) return "—";
  const mins = Math.floor(ms / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 48) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

/**
 * Always-visible per-sensor freshness strip (today, ring only).
 *
 * Green = ok, amber = stale. Replaces the old surprise-only banner.
 */
export function SensorFreshnessStrip() {
  const { data, isLoading } = useDataQuality(1, "ring");
  if (isLoading && !data) return null;
  if (!data) return null;

  const today = todayKey();
  const byType = new Map(
    data.filter((r) => r.day === today).map((r) => [r.data_type, r]),
  );

  // Nothing for today yet (no analytics pass) — stay quiet.
  if (byType.size === 0) return null;

  const anyStale = TYPES.some((t) => byType.get(t.key)?.status === "stale");

  return (
    <div
      className={`mb-6 rounded-lg border px-3 py-2.5 sm:px-4 ${
        anyStale
          ? "bg-amber-50 dark:bg-amber-900/20 border-amber-200 dark:border-amber-800"
          : "bg-gray-50 dark:bg-gray-800/60 border-gray-200 dark:border-gray-700"
      }`}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-medium text-gray-500 dark:text-gray-400 mr-1">
          Sensors
        </span>
        {TYPES.map(({ key, label }) => {
          const row = byType.get(key);
          const status = row?.status ?? "missing";
          const reason = row?.reason ?? "";
          const tip = [
            label,
            status === "ok" ? "OK" : status === "stale" ? "Stale" : "—",
            row?.last_ts ? relativeAge(row.last_ts) : "no samples",
            reason ? REASON_HINT[reason] || reason : "",
          ]
            .filter(Boolean)
            .join(" · ");

          const chip =
            status === "ok"
              ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300"
              : status === "stale"
                ? "bg-amber-200 text-amber-900 dark:bg-amber-800/50 dark:text-amber-200"
                : "bg-gray-200 text-gray-600 dark:bg-gray-700 dark:text-gray-400";

          const dot =
            status === "ok"
              ? "bg-emerald-500"
              : status === "stale"
                ? "bg-amber-500"
                : "bg-gray-400";

          return (
            <span
              key={key}
              title={tip}
              className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${chip}`}
            >
              <span className={`h-1.5 w-1.5 rounded-full ${dot}`} />
              {label}
            </span>
          );
        })}
      </div>
      {anyStale && (
        <p className="mt-1.5 text-xs text-amber-800 dark:text-amber-300">
          Amber = freshness gap. Hover a chip for last update + reason.
        </p>
      )}
    </div>
  );
}

/** @deprecated Use SensorFreshnessStrip */
export const DataQualityBanner = SensorFreshnessStrip;
