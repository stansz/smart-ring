import { useRawSleep } from "../../api/hooks";

interface SleepSectionProps {
  selectedKey: string;
}

const STAGE_COLORS: Record<string, string> = {
  deep: "#4338ca",
  rem: "#a855f7",
  light: "#60a5fa",
  awake: "#fb923c",
};
const STAGE_LABELS: Record<string, string> = {
  deep: "Deep",
  rem: "REM",
  light: "Light",
  awake: "Awake",
};
const STAGE_ORDER = ["deep", "rem", "light", "awake"];

export function SleepSection({ selectedKey }: SleepSectionProps) {
  const { data: rawSleep } = useRawSleep(720, 1000);

  const stages = rawSleep?.filter((s) => s.day === selectedKey && s.duration_minutes > 0) || [];

  // Empty state
  if (stages.length === 0) {
    return (
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 border border-gray-100 dark:border-gray-700">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-4">Last Night's Sleep</h2>
        <div className="flex flex-col sm:flex-row items-center gap-6">
          <div className="relative w-44 h-44 flex-shrink-0">
            <div className="absolute inset-0 rounded-full bg-gray-200 dark:bg-gray-700" />
            <div className="absolute inset-3 bg-white dark:bg-gray-800 rounded-full flex flex-col items-center justify-center">
              <span className="text-3xl mb-1 opacity-60">🌙</span>
              <span className="text-lg font-bold text-gray-500 dark:text-gray-400">0h 0m</span>
            </div>
          </div>
          <div className="flex-1 self-center">
            <p className="text-sm text-gray-500 dark:text-gray-400">
              {new Date().toISOString().slice(0, 10) === selectedKey
                ? "No sleep recorded last night"
                : "No sleep data for this day"}
            </p>
          </div>
        </div>
      </div>
    );
  }

  // Compute stage minutes
  const byType: Record<string, number> = {};
  for (const s of stages) {
    byType[s.stage] = (byType[s.stage] || 0) + (s.duration_minutes || 0);
  }
  const total = Object.values(byType).reduce((a, b) => a + b, 0) || 1;

  // Build conic gradient
  let cumulative = 0;
  const slices: string[] = [];
  for (const stage of STAGE_ORDER) {
    const pct = ((byType[stage] || 0) / total) * 100;
    if (pct > 0) {
      slices.push(`${STAGE_COLORS[stage]} ${cumulative}% ${cumulative + pct}%`);
      cumulative += pct;
    }
  }

  // Bed/wake times
  const sortedStages = [...stages].sort((a, b) => new Date(a.start_ts).getTime() - new Date(b.start_ts).getTime());
  const bedTime = new Date(sortedStages[0].start_ts);
  const wakeTime = new Date(sortedStages[sortedStages.length - 1].end_ts);

  const totalHours = Math.floor(total / 60);
  const remMin = Math.round(total % 60);

  // Legend
  const legendRows = STAGE_ORDER.map((stage) => {
    const min = byType[stage] || 0;
    const pct = Math.round((min / total) * 100);
    return { stage, min, pct };
  }).filter((r) => r.min > 0);

  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 border border-gray-100 dark:border-gray-700">
      <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-4">
        Last Night's Sleep
        <span className="text-sm font-normal text-gray-400 dark:text-gray-500 ml-2">
          ({new Date(selectedKey + "T00:00").toLocaleDateString()})
        </span>
      </h2>
      <div className="flex flex-col sm:flex-row items-center gap-6">
        {/* Conic donut */}
        <div className="relative w-44 h-44 flex-shrink-0">
          <div
            className="absolute inset-0 rounded-full"
            style={{
              background: `conic-gradient(${slices.join(", ")})`,
              boxShadow: "inset 0 2px 6px rgba(0,0,0,0.18)",
            }}
          />
          <div className="absolute inset-0 rounded-full"
            style={{
              background: "radial-gradient(circle at 35% 30%, rgba(255,255,255,0.35), rgba(255,255,255,0) 55%)",
              mixBlendMode: "screen",
            }} />
          <div
            className="absolute inset-3 bg-white dark:bg-gray-800 rounded-full flex flex-col items-center justify-center"
            style={{ boxShadow: "inset 0 4px 14px rgba(0,0,0,0.10)" }}
          >
            <span className="text-2xl font-bold text-gray-900 dark:text-gray-100">
              {totalHours}h {remMin}m
            </span>
            <span className="text-xs text-gray-400 dark:text-gray-500">
              {bedTime.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} – {wakeTime.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
            </span>
          </div>
        </div>

        {/* Stage legend */}
        <div className="flex-1 space-y-1.5">
          <p className="text-xs font-medium text-gray-400 dark:text-gray-500 uppercase tracking-wide mb-2">Stage Breakdown</p>
          {legendRows.map((r) => (
            <div key={r.stage} className="flex items-center gap-2 text-sm">
              <span className="w-3 h-3 rounded-full flex-shrink-0" style={{ background: STAGE_COLORS[r.stage] }} />
              <span className="text-gray-700 dark:text-gray-300">{STAGE_LABELS[r.stage]}</span>
              <span className="ml-auto font-mono text-gray-500 dark:text-gray-400">{r.min}m ({r.pct}%)</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
