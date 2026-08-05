import { useDataQuality } from "../../api/hooks";
import { todayKey } from "../../utils/date";

// Short labels sized for the top nav row.
const TYPES = [
  { key: "heart_rate", label: "HR" },
  { key: "hrv", label: "HRV" },
  { key: "steps", label: "Stp" },
  { key: "spo2", label: "SpO₂" },
  { key: "stress", label: "Str" },
  { key: "temperature", label: "T" },
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
 * Compact per-sensor freshness chips for the top nav row (ring only).
 *
 * Green = ok, amber = stale, gray = no row / no data yet today.
 * Title attr carries detail (age + reason) for hover/long-press.
 * Sits next to the battery indicator on every tab. Always visible —
 * gray means "no analytics row for today yet" (early morning, no sync).
 */
export function SensorFreshnessNav() {
  const { data } = useDataQuality(1, "ring");

  const today = todayKey();
  const byType = new Map(
    (data ?? []).filter((r) => r.day === today).map((r) => [r.data_type, r]),
  );

  return (
    <div className="flex items-center gap-0.5 sm:gap-1 overflow-x-auto [scrollbar-width:none] [-ms-overflow-style:none] [&::-webkit-scrollbar]:hidden">
      {TYPES.map(({ key, label }) => {
        const row = byType.get(key);
        const status = row?.status ?? "missing";
        const reason = row?.reason ?? "";
        const tip =
          row == null
            ? `${label} · no data yet today`
            : [
                label,
                status === "ok" ? "OK" : status === "stale" ? "Stale" : "—",
                row.last_ts ? relativeAge(row.last_ts) : "no samples",
                reason ? REASON_HINT[reason] || reason : "",
              ]
                .filter(Boolean)
                .join(" · ");

        const color =
          status === "ok"
            ? "text-emerald-600 dark:text-emerald-400"
            : status === "stale"
              ? "text-amber-600 dark:text-amber-400"
              : "text-gray-400 dark:text-gray-500";

        const dot =
          status === "ok"
            ? "bg-emerald-500"
            : status === "stale"
              ? "bg-amber-500"
              : "bg-gray-400 dark:bg-gray-500";

        return (
          <span
            key={key}
            title={tip}
            className={`inline-flex items-center gap-0.5 px-1 sm:px-1.5
              text-[10px] sm:text-xs font-medium ${color}
              whitespace-nowrap`}
          >
            <span className={`h-1.5 w-1.5 rounded-full ${dot}`} />
            {label}
          </span>
        );
      })}
    </div>
  );
}
