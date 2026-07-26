import { useReadiness } from "../../api/hooks";
import type { ReadinessRow } from "../../api/types";

interface ReadinessHeroProps {
  selectedKey: string;
}

export function ReadinessHero({ selectedKey }: ReadinessHeroProps) {
  const { data } = useReadiness(30);
  const row: ReadinessRow | undefined = data?.find((r) => r.day === selectedKey);

  const score = row?.score;
  const label =
    score != null ?
      score >= 80 ? "Excellent" : score >= 60 ? "Good" : score >= 40 ? "Fair" : "Low"
    : null;

  const isToday = selectedKey === new Date().toISOString().slice(0, 10);
  const frozenAt = row?.frozen_at;
  const showPreliminary = isToday && !frozenAt;

  // Concentric ring computations (circumference: 2πr — outer ≈ 251, middle ≈ 201, inner ≈ 151)
  const circumferences = { sleep: 251, hrv: 201, rhr: 151 };

  return (
    <div className="p-6">
      <div className="flex justify-between items-baseline mb-4">
        <div className="flex items-center gap-2 flex-wrap">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">Readiness</h2>
          {showPreliminary && (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400 font-medium uppercase tracking-wide">
              Preliminary
            </span>
          )}
          {row?.confidence === "partial" && (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400 font-medium uppercase tracking-wide">
              partial · missing {row.missing_components?.join(", ") || ""}
            </span>
          )}
        </div>
        <span className="text-xs text-gray-400 dark:text-gray-500">
          {row?.day ? new Date(row.day + "T00:00").toLocaleDateString() : ""}
        </span>
      </div>

      {/* Concentric rings */}
      <div className="relative mx-auto mb-3" style={{ width: 300, maxWidth: "100%" }}>
        <svg viewBox="0 0 100 100" className="w-full -rotate-90">
          {/* Tracks */}
          <circle cx="50" cy="50" r="40" fill="none" className="text-gray-200 dark:text-gray-700" strokeWidth="6" stroke="currentColor" />
          <circle cx="50" cy="50" r="32" fill="none" className="text-gray-200 dark:text-gray-700" strokeWidth="6" stroke="currentColor" />
          <circle cx="50" cy="50" r="24" fill="none" className="text-gray-200 dark:text-gray-700" strokeWidth="6" stroke="currentColor" />
          {/* Filled rings: Sleep (indigo), HRV (purple), RHR (rose) */}
          <circle cx="50" cy="50" r="40" fill="none" strokeWidth="6" strokeLinecap="round"
            stroke="#6366f1"
            strokeDasharray={circumferences.sleep}
            strokeDashoffset={circumferences.sleep * (1 - ((row?.sleep_score || 0) / 100))}
          />
          <circle cx="50" cy="50" r="32" fill="none" strokeWidth="6" strokeLinecap="round"
            stroke="#a855f7"
            strokeDasharray={circumferences.hrv}
            strokeDashoffset={circumferences.hrv * (1 - ((row?.hrv_score || 0) / 100))}
          />
          <circle cx="50" cy="50" r="24" fill="none" strokeWidth="6" strokeLinecap="round"
            stroke="#f43f5e"
            strokeDasharray={circumferences.rhr}
            strokeDashoffset={circumferences.rhr * (1 - ((row?.rhr_score || 0) / 100))}
          />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-4xl font-bold text-gray-900 dark:text-gray-100">{score ?? "—"}</span>
        </div>
      </div>

      <p className={`text-sm font-medium text-center ${
        score != null && score >= 80 ? "text-green-600" : score != null && score >= 60 ? "text-amber-600" : "text-red-500"
      }`}>
        {label || "—"}
      </p>

      {/* Sub-score legend */}
      <div className="flex flex-wrap justify-center gap-x-6 gap-y-2 text-sm mt-4">
        <span className="flex items-center gap-2 text-gray-500 dark:text-gray-400">
          <span className="w-3 h-3 rounded-full flex-shrink-0" style={{ background: "#6366f1" }} />
          Sleep <span className="text-base font-bold text-indigo-600 dark:text-indigo-400">{row?.sleep_score ?? "—"}</span>
        </span>
        <span className="flex items-center gap-2 text-gray-500 dark:text-gray-400">
          <span className="w-3 h-3 rounded-full flex-shrink-0" style={{ background: "#a855f7" }} />
          HRV <span className="text-base font-bold text-purple-600 dark:text-purple-400">{row?.hrv_score ?? "—"}</span>
        </span>
        <span className="flex items-center gap-2 text-gray-500 dark:text-gray-400">
          <span className="w-3 h-3 rounded-full flex-shrink-0" style={{ background: "#f43f5e" }} />
          RHR <span className="text-base font-bold text-rose-600 dark:text-rose-400">{row?.rhr_score ?? "—"}</span>
        </span>
      </div>
    </div>
  );
}
