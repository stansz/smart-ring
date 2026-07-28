import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import { useCircadianHr } from "../../api/hooks";
import { Skeleton, Card } from "../ui";

export function CircadianChart() {
  const { data, isLoading } = useCircadianHr();

  // Aggregate all days into 24 hourly buckets (matches legacy renderCircadianLine)
  const byHour: Record<number, { sum: number; n: number }> = {};
  for (let h = 0; h < 24; h++) byHour[h] = { sum: 0, n: 0 };
  for (const r of data?.rows || []) {
    if (r.avg_hr != null) {
      byHour[r.hour].sum += r.avg_hr;
      byHour[r.hour].n += 1;
    }
  }

  const chartData = Array.from({ length: 24 }, (_, h) => ({
    hour: h,
    label: `${h}:00`,
    avg: byHour[h].n > 0 ? byHour[h].sum / byHour[h].n : null,
  }));

  const range = data?.range;
  const fmtDay = (d: string) => new Date(d + "T00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" });
  const subtitle = range?.min_day ? `${fmtDay(range.min_day)} – ${fmtDay(range.max_day)} — hourly average by time of day` : "Hourly average by time of day";

  const vals = chartData.map((d) => d.avg).filter((v): v is number => v != null);
  const circMin = vals.length > 0 ? Math.round(Math.min(...vals)) : null;
  const circMax = vals.length > 0 ? Math.round(Math.max(...vals)) : null;
  const circAvg = vals.length > 0 ? Math.round(vals.reduce((a, b) => a + b, 0) / vals.length) : null;

  if (isLoading && chartData.every((d) => d.avg == null)) {
    return <Card className="p-6"><Skeleton className="h-56" /></Card>;
  }

  return (
    <Card className="p-6">
      <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-1">Circadian HR Pattern</h2>
      <p className="text-xs text-gray-500 dark:text-gray-400 mb-3">{subtitle}</p>
      <div style={{ minHeight: 160 }}>
        <ResponsiveContainer width="100%" height={160}>
          <AreaChart data={chartData}>
            <defs>
              <linearGradient id="circGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#8b5cf6" stopOpacity={0.6} />
                <stop offset="95%" stopColor="#8b5cf6" stopOpacity={0.05} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#374151" opacity={0.3} />
            <XAxis dataKey="hour" tick={{ fontSize: 10 }} ticks={[0, 3, 6, 9, 12, 15, 18, 21]}
              tickFormatter={(h: unknown) => `${h}:00`} />
            <YAxis domain={["dataMin - 5", "dataMax + 5"]} tick={{ fontSize: 10 }} tickFormatter={(v: number) => String(Math.round(v))} />
            <Tooltip
              labelFormatter={(h: unknown) => `${String(h).padStart(2, "0")}:00 — hourly avg`}
              contentStyle={{ background: "#1f2937", border: "none", borderRadius: 6, fontSize: 12 }}
            />
            <Area type="monotone" dataKey="avg" stroke="#3b82f6" fill="url(#circGrad)" dot={{ r: 2.5, fill: "#3b82f6" }} name="HR" connectNulls />
          </AreaChart>
        </ResponsiveContainer>
      </div>
      <div className="border-t border-gray-100 dark:border-gray-700 pt-3 grid grid-cols-3 gap-2 text-xs">
        <div className="text-center">
          <p className="text-gray-500 dark:text-gray-400">Min HR</p>
          <p className="font-bold text-sm mt-0.5 text-blue-600">{circMin != null ? `${circMin} bpm` : "—"}</p>
        </div>
        <div className="text-center">
          <p className="text-gray-500 dark:text-gray-400">Max HR</p>
          <p className="font-bold text-sm mt-0.5 text-orange-500 dark:text-orange-400">{circMax != null ? `${circMax} bpm` : "—"}</p>
        </div>
        <div className="text-center relative group">
          <p className="text-gray-500 dark:text-gray-400">Avg HR <span className="cursor-help text-gray-300 dark:text-gray-600">ⓘ</span></p>
          <p className="font-bold text-sm mt-0.5 text-teal-500 dark:text-teal-400">{circAvg != null ? `${circAvg} bpm` : "—"}</p>
          <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 w-64 px-3 py-2 bg-gray-800 dark:bg-gray-700 text-white text-xs rounded-lg opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none z-10 leading-relaxed">
            Your heart rate mapped across a 24-hour clock. The dip at night reflects deep sleep (better recovery). A flatter line can indicate stress, overtraining, or poor sleep quality.
          </div>
        </div>
      </div>
    </Card>
  );
}
