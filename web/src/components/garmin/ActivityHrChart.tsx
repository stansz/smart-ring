import { useMemo } from "react";
import {
  Area,
  AreaChart,
  ReferenceArea,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import type { ActivityHrRow } from "../../api/types";

// Garmin's standard 5-zone defaults (used by the 745 with HR setting = %max).
// RHR=53, maxHR=185 → 50%=93, 60%=111, 70%=130, 80%=148, 90%=167.
// Used only for visual reference bands on the chart.
const ZONE_1_MAX = 90;
const ZONE_2_MAX = 110;
const ZONE_3_MAX = 130;
const ZONE_4_MAX = 150;

interface ActivityHrChartProps {
  data: ActivityHrRow[];
}

export function ActivityHrChart({ data }: ActivityHrChartProps) {
  // Pre-format: convert ISO ts → ms epoch for the X axis (Recharts handles
  // numeric better than date strings for large datasets). Use relative
  // seconds-since-start for the X axis label (cleaner than absolute time
  // for a multi-hour activity).
  const chartData = useMemo(() => {
    if (data.length === 0) return [];
    const start = new Date(data[0].ts).getTime();
    return data.map((r) => ({
      t: (new Date(r.ts).getTime() - start) / 1000, // seconds since start
      hr: r.hr,
    }));
  }, [data]);

  if (chartData.length < 2) {
    return (
      <p className="text-sm text-gray-500 dark:text-gray-400 italic py-8 text-center">
        Not enough HR samples to chart
      </p>
    );
  }

  const formatXAxis = (sec: number) => {
    const h = Math.floor(sec / 3600);
    const m = Math.floor((sec % 3600) / 60);
    if (h > 0) return `${h}h${m.toString().padStart(2, "0")}`;
    return `${m}m`;
  };

  const formatTooltip = (entry: { t: number; hr: number }) => {
    const totalSec = Math.floor(entry.t);
    const h = Math.floor(totalSec / 3600);
    const m = Math.floor((totalSec % 3600) / 60);
    const s = totalSec % 60;
    const elapsed = h > 0
      ? `${h}h ${m}m ${s}s`
      : `${m}m ${s}s`;
    return { elapsed, hr: entry.hr };
  };

  return (
    <div style={{ minHeight: 220 }}>
      <ResponsiveContainer width="100%" height={220}>
        <AreaChart data={chartData} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
          {/* HR zone bands — light tinted backgrounds to show effort zones */}
          <ReferenceArea y1={0} y2={ZONE_1_MAX} fill="#22c55e" fillOpacity={0.05} />
          <ReferenceArea y1={ZONE_1_MAX} y2={ZONE_2_MAX} fill="#84cc16" fillOpacity={0.06} />
          <ReferenceArea y1={ZONE_2_MAX} y2={ZONE_3_MAX} fill="#eab308" fillOpacity={0.07} />
          <ReferenceArea y1={ZONE_3_MAX} y2={ZONE_4_MAX} fill="#f97316" fillOpacity={0.08} />
          <ReferenceArea y1={ZONE_4_MAX} y2={220} fill="#ef4444" fillOpacity={0.09} />

          <defs>
            <linearGradient id="hrGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#ef4444" stopOpacity={0.6} />
              <stop offset="100%" stopColor="#ef4444" stopOpacity={0.05} />
            </linearGradient>
          </defs>
          <XAxis
            dataKey="t"
            tickFormatter={formatXAxis}
            tick={{ fontSize: 10, fill: "currentColor" }}
            interval="preserveStartEnd"
            minTickGap={40}
            className="text-gray-500 dark:text-gray-400"
          />
          <YAxis
            domain={[40, "auto"]}
            tick={{ fontSize: 10, fill: "currentColor" }}
            className="text-gray-500 dark:text-gray-400"
          />
          <Tooltip
            content={({ active, payload }) => {
              if (!active || !payload || payload.length === 0) return null;
              const p = payload[0].payload as { t: number; hr: number };
              const { elapsed, hr } = formatTooltip(p);
              return (
                <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded px-2 py-1 text-xs shadow">
                  <div className="text-gray-500 dark:text-gray-400">{elapsed} in</div>
                  <div className="font-semibold text-gray-900 dark:text-gray-100">{hr} bpm</div>
                </div>
              );
            }}
          />
          <Area
            type="monotone"
            dataKey="hr"
            stroke="#ef4444"
            strokeWidth={1.2}
            fill="url(#hrGradient)"
            isAnimationActive={false}
            dot={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
