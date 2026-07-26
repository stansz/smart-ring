import { useMemo, useRef, useState, useCallback, type ReactNode } from "react";
import { polar, arc, tsToDayMinutes } from "../../utils/dayring";
import type { DailyActivityRow, RawSleepRow } from "../../api/types";

const CX = 120;
const CY = 90;
const BASE_IN = 70;
const BASE_OUT = 84;
const BAR_IN = 86;
const BAR_MAX = 48;
const LABEL_R = 62;

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

const WORN_BASE = "#d1d5db";

interface DayRingProps {
  row: DailyActivityRow | undefined;
  sleepStages: RawSleepRow[];
  darkMode: boolean;
  dayKey: string;
}

interface TooltipState {
  text: string;
  x: number;
  y: number;
}

export function DayRing({ row, sleepStages, darkMode, dayKey }: DayRingProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [tooltip, setTooltip] = useState<TooltipState | null>(null);

  const grey = darkMode ? "#374151" : "#e5e7eb";

  const { segments, labels, centerTop, centerSub, legend } = useMemo(() => {
    const worn = (row?.hourly_worn) || new Array(24).fill(0) as number[];
    const steps = (row?.hourly_steps) || new Array(24).fill(0) as number[];
    const maxSteps = Math.max(...steps, 1);

    // ── Sleep overlay arcs ──
    const sleepSegs: ReactNode[] = [];
    const stageMin: Record<string, number> = { deep: 0, rem: 0, light: 0, awake: 0 };
    for (const s of sleepStages) {
      if (!STAGE_COLORS[s.stage]) continue;
      const sMin = tsToDayMinutes(s.start_ts, dayKey);
      const eMin = tsToDayMinutes(s.end_ts, dayKey);
      if (eMin <= sMin) continue;
      const a0 = (sMin / 1440) * 360;
      const a1 = (eMin / 1440) * 360;
      const dur = Math.round(eMin - sMin);
      stageMin[s.stage] = (stageMin[s.stage] || 0) + dur;
      const tip = `${STAGE_LABELS[s.stage]} · ${dur}m`;
      sleepSegs.push(
        <path
          key={`sleep-${s.start_ts}-${s.stage}`}
          className="ringbar"
          d={arc(CX, CY, BASE_OUT, BASE_IN, a0, a1)}
          fill={STAGE_COLORS[s.stage]}
          data-tip={tip}
        />,
      );
    }

    // ── Hourly segments (worn baseline + activity bars) ──
    const segs: ReactNode[] = [];
    for (let h = 0; h < 24; h++) {
      const a0 = h * 15 + 0.7;
      const a1 = (h + 1) * 15 - 0.7;

      let baseFill: string, baseTip: string;
      if (worn[h] > 0 || steps[h] > 0) {
        baseFill = WORN_BASE;
        baseTip = `${h}:00 · worn${steps[h] > 0 ? " · " + steps[h] + " steps" : ""}`;
      } else {
        baseFill = grey;
        baseTip = `${h}:00 · not worn`;
      }
      segs.push(
        <path
          key={`base-${h}`}
          className="ringbar"
          d={arc(CX, CY, BASE_OUT, BASE_IN, a0, a1)}
          fill={baseFill}
          data-tip={baseTip}
        />,
      );

      const v = steps[h];
      if (v > 0) {
        const top = BAR_IN + (v / maxSteps) * BAR_MAX;
        segs.push(
          <path
            key={`steps-${h}`}
            className="ringbar"
            d={arc(CX, CY, top, BAR_IN, a0, a1)}
            fill="#10b981"
            opacity="0.95"
            data-tip={`${h}:00–${h + 1}:00 · ${v} steps`}
          />,
        );
      }
    }

    // ── Hour labels ──
    const labelCol = darkMode ? "#9ca3af" : "#6b7280";
    const labelEls = [0, 6, 12, 18].map((h) => {
      const [lx, ly] = polar(CX, CY, LABEL_R, h * 15);
      const txt = h === 0 ? "12a" : h === 12 ? "12p" : h < 12 ? h + "a" : (h - 12) + "p";
      return (
        <text key={`lbl-${h}`} x={lx.toFixed(1)} y={(ly + 4).toFixed(1)}
          textAnchor="middle" fontSize="11" fontWeight="500" fill={labelCol}>
          {txt}
        </text>
      );
    });

    // ── Center text ──
    let top = "—", sub = "no data";
    if (row) {
      top = (row.steps_total || 0).toLocaleString();
      if (row.first_hr_ts && row.last_hr_ts) {
        const ms = new Date(row.last_hr_ts).getTime() - new Date(row.first_hr_ts).getTime();
        const wornH = Math.round(ms / 3_600_000);
        sub = wornH > 0 ? `${wornH}h worn` : "no wear data";
      }
    }

    // ── Legend ──
    const fmtMin = (m: number) => m > 0 ? `${Math.floor(m / 60)}h ${m % 60}m` : "—";
    const wornH = row ? Math.round(((new Date(row.last_hr_ts!).getTime() - new Date(row.first_hr_ts!).getTime()) / 3_600_000)) : 0;
    const legendItems: [string, string, string][] = [
      ["#10b981", "Steps", row ? row.steps_total.toLocaleString() : "—"],
      ["#4338ca", "Deep", fmtMin(stageMin.deep || 0)],
      ["#a855f7", "REM", fmtMin(stageMin.rem || 0)],
      ["#60a5fa", "Light", fmtMin(stageMin.light || 0)],
      ["#fb923c", "Awake", fmtMin(stageMin.awake || 0)],
      ["#d1d5db", "Worn", wornH ? `${wornH}h` : "—"],
      [grey, "Off", "—"],
    ];

    return {
      segments: [...segs, ...sleepSegs],
      labels: labelEls,
      centerTop: top,
      centerSub: sub,
      legend: legendItems,
    } as const;
  }, [row, sleepStages, darkMode, dayKey, grey]);

  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    const target = (e.target as Element).closest?.(".ringbar") as HTMLElement | null;
    if (target?.dataset.tip) {
      setTooltip({ text: target.dataset.tip, x: e.clientX + 14, y: e.clientY - 32 });
    } else {
      setTooltip(null);
    }
  }, []);

  const handleMouseLeave = useCallback(() => setTooltip(null), []);

  const centerCol = darkMode ? "#e5e7eb" : "#111827";
  const subCol = darkMode ? "#9ca3af" : "#6b7280";
  const legendValCol = darkMode ? "#e5e7eb" : "#374151";

  return (
    <>
      <div className="flex flex-col items-center w-full flex-1">
        <div className="flex justify-center w-full" onMouseMove={handleMouseMove} onMouseLeave={handleMouseLeave}>
          <svg ref={svgRef} viewBox="-18 -18 276 276" className="w-full" style={{ width: 360, maxWidth: "100%" }}>
            {segments}
            {labels}
            <text x={CX} y={CY - 4} textAnchor="middle" fontSize="30" fontWeight="700" fill={centerCol}>
              {centerTop}
            </text>
            <text x={CX} y={CY + 14} textAnchor="middle" fontSize="10" fill={subCol}>steps</text>
            <text x={CX} y={CY + 32} textAnchor="middle" fontSize="10" fontWeight="500" fill={subCol}>{centerSub}</text>
          </svg>
        </div>

        {/* Legend */}
        <div className="w-full mt-2">
          <div className="flex flex-wrap justify-center gap-x-6 gap-y-2 text-sm">
            {legend.map(([color, label, value]) => (
              <span key={label} className="flex items-center gap-2">
                <span className="w-3 h-3 rounded-full flex-shrink-0" style={{ background: color }} />
                <span className="text-gray-600 dark:text-gray-400">{label}</span>
                <span className="font-mono" style={{ color: legendValCol }}>{value}</span>
              </span>
            ))}
          </div>
        </div>
      </div>

      {/* Tooltip */}
      {tooltip && (
        <div
          className="fixed z-50 px-2 py-1 rounded bg-gray-900 text-white text-xs pointer-events-none"
          style={{ left: Math.min(tooltip.x, window.innerWidth - 140), top: tooltip.y }}
        >
          {tooltip.text}
        </div>
      )}
    </>
  );
}
