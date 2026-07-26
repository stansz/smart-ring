import { useCurrentStatus } from "../../api/hooks";

const LADDER = [
  { emoji: "🔥", label: "Locked In", colorClass: "text-emerald-600 dark:text-emerald-400", min: 80 },
  { emoji: "💪", label: "Solid",     colorClass: "text-sky-600 dark:text-sky-400",      min: 60 },
  { emoji: "🌊", label: "Vibing",    colorClass: "text-amber-600 dark:text-amber-400",  min: 40 },
  { emoji: "😮‍💨", label: "Winded", colorClass: "text-orange-600 dark:text-orange-400", min: 20 },
  { emoji: "😴", label: "Gassed",    colorClass: "text-red-500 dark:text-red-400",       min: 0 },
] as const;

function sparklinePath(values: number[]): string {
  if (values.length < 2) return "";
  const w = 60, h = 20;
  const xScale = (i: number) => (i / (values.length - 1)) * w;
  const yScale = (v: number) => h - (v / 99) * h;
  const points = values.map((v, i) => `${xScale(i).toFixed(1)},${yScale(Math.min(99, Math.max(0, v))).toFixed(1)}`);
  return `M${points.join(" L")}`;
}

export function CurrentStatusPanel() {
  const { data } = useCurrentStatus(168);
  const latest = data?.[0] ?? null;
  const score = latest?.score ?? null;
  const stressRaw = latest?.stress_recent ?? null;
  const hrvSlope = latest?.hrv_trend ?? null;
  const updated = latest?.ts ? new Date(latest.ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : null;
  const activeRung = LADDER.find((r) => score != null && score >= r.min) || LADDER[LADDER.length - 1];

  // Stress history (last 12 snapshots, any day)
  const stressHistory = (data || []).slice(0, 12).reverse().map((r) => r.stress_recent).filter((v): v is number => v != null);
  const stressHistoryTs = (data || []).slice(0, 12).reverse().map((r) => r.ts).filter((v): v is string => v != null);
  const oldestStressTs = stressHistoryTs.length > 0
    ? new Date(stressHistoryTs[0]).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : "";

  // Stress label
  function stressLabel(): string {
    if (stressRaw == null) return "";
    if (stressRaw <= 50) return "Low";
    if (stressRaw <= 75) return "Medium";
    return "High";
  }

  // Trend label
  function trendLabel() {
    if (hrvSlope == null) return { arrow: "—", label: "", detail: "", colorClass: "" };
    if (hrvSlope > 0.5) return { arrow: "↑", label: "Rising", detail: "recovering", colorClass: "text-emerald-600 dark:text-emerald-400" };
    if (hrvSlope < -0.5) return { arrow: "↓", label: "Falling", detail: "fatiguing", colorClass: "text-amber-600 dark:text-amber-400" };
    return { arrow: "→", label: "Steady", detail: "stable", colorClass: "text-gray-500 dark:text-gray-400" };
  }

  function trendPosition(): number {
    if (hrvSlope == null) return 50;
    const clamped = Math.max(-1, Math.min(1, hrvSlope));
    return ((clamped + 1) / 2) * 100;
  }

  const tr = trendLabel();

  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow border border-gray-100 dark:border-gray-700 mb-8">
      <div className="px-6 py-4">
        <div className="flex justify-between items-baseline mb-3">
          <div className="flex items-center gap-2 flex-wrap">
            <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">Current Status</h2>
            <span className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400 font-medium uppercase tracking-wide">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
              Live
            </span>
            {latest?.confidence === "partial" && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400 font-medium uppercase tracking-wide">partial</span>
            )}
          </div>
          <span className="text-xs text-gray-400 dark:text-gray-500">
            {updated ? `as of ${updated}` : ""}
          </span>
        </div>

        {/* 3-card grid: Vibe(1) + Stress(2) + Trend(2) */}
        <div className="grid grid-cols-1 sm:grid-cols-5 gap-3">

          {/* VIBE — 5-rung ladder */}
          <div className="sm:col-span-1 rounded-lg border border-gray-100 dark:border-gray-700 p-3">
            <div className="space-y-1.5">
              {LADDER.map((rung) => {
                const active = rung === activeRung;
                return (
                  <div key={rung.label} className={`flex items-center gap-2.5 transition-all duration-200 ${active ? "opacity-100" : "opacity-40"}`}>
                    <span className={`transition-transform duration-200 leading-none ${active ? "text-2xl" : "text-lg"}`}>
                      {rung.emoji}
                    </span>
                    <span className={`text-sm font-medium whitespace-nowrap ${rung.colorClass}`}>
                      {active && score != null ? `${rung.label} · ${score}` : rung.label}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>

          {/* STRESS — raw 0-99 + sparkline */}
          <div className="sm:col-span-2 rounded-lg border border-gray-100 dark:border-gray-700 p-3 flex flex-col">
            <div className="flex items-baseline justify-between mb-1">
              <p className="text-[10px] font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">Stress</p>
              <p className="text-[11px] text-gray-500 dark:text-gray-400">
                {stressRaw != null ? `${stressRaw} / 99 · ${stressLabel()} · 2h avg` : ""}
              </p>
            </div>
            <p className="text-xl font-semibold text-amber-600 dark:text-amber-400 leading-tight">
              {stressRaw != null ? `${stressRaw} / 99` : "—"}
            </p>
            {stressHistory.length >= 2 && (
              <div className="flex gap-1.5 mt-2 flex-1 min-h-[50px]">
                <div className="flex flex-col justify-between text-[9px] text-gray-400 dark:text-gray-500 py-0.5 leading-none">
                  <span>99</span><span>50</span><span>0</span>
                </div>
                <div className="flex-1 flex flex-col">
                  <svg viewBox="0 0 60 20" preserveAspectRatio="none" className="w-full flex-1 min-h-[36px] text-amber-400 dark:text-amber-500 overflow-visible">
                    <path d={sparklinePath(stressHistory)} fill="none" stroke="currentColor" strokeWidth="1.5"
                      strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
                  </svg>
                  <div className="flex justify-between text-[9px] text-gray-400 dark:text-gray-500 mt-0.5 leading-none">
                    <span>{oldestStressTs}</span>
                    <span>now</span>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* TREND — HRV slope with gradient track */}
          <div className="sm:col-span-2 rounded-lg border border-gray-100 dark:border-gray-700 p-3 flex flex-col">
            <div className="flex items-baseline justify-between mb-1">
              <p className="text-[10px] font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
                Trend <span className="font-normal normal-case text-gray-400">(HRV 2h)</span>
              </p>
              <p className={`text-[11px] ${tr.colorClass}`}>{tr.detail}</p>
            </div>
            <p className={`text-xl font-semibold leading-tight ${tr.colorClass}`}>
              {hrvSlope != null ? `${tr.arrow} ${tr.label}` : "—"}
            </p>
            {hrvSlope != null && (
              <div className="mt-3 flex-1 flex flex-col">
                <div className="relative h-2 rounded-full bg-gradient-to-r from-amber-500 via-gray-300 dark:via-gray-600 to-emerald-500">
                  <div className={`absolute top-1/2 -translate-x-1/2 -translate-y-1/2 w-3.5 h-3.5 rounded-full bg-white dark:bg-gray-800 border-2 shadow ring-2 ring-white dark:ring-gray-800 ${
                    hrvSlope > 0.5 ? "border-emerald-500" : hrvSlope < -0.5 ? "border-amber-500" : "border-gray-400 dark:border-gray-500"
                  }`}
                    style={{ left: `${trendPosition()}%` }} />
                </div>
                <div className="flex text-[9px] text-gray-500 dark:text-gray-400 mt-1.5 leading-none">
                  <span className="w-1/4 text-left">Falling</span>
                  <span className="w-1/2 text-center">Steady</span>
                  <span className="w-1/4 text-right">Rising</span>
                </div>
                <p className="text-[10px] text-gray-400 dark:text-gray-500 mt-auto pt-2 leading-snug">
                  HRV slope per hour (last 2h). Rising = recovering, Falling = fatiguing.
                </p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
