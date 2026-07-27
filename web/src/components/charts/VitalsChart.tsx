import { useRawHeartRate, useRawSpo2 } from "../../api/hooks";
import { Skeleton, Card } from "../ui";
import { todayKey, dayKeyFromTs, dateKey } from "../../utils/date";
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
} from "recharts";

interface VitalsChartProps {
  hours?: number;
  selectedKey: string;
}

export function VitalsChart({ hours = 48, selectedKey }: VitalsChartProps) {
  const { data: hr, isLoading } = useRawHeartRate(hours, 500);
  const { data: spo2 } = useRawSpo2(hours, 200);

  // Filter for selected day + aggregate by hour (matches legacy renderVitalsChart)
  const byHour: Record<number, { hr: number[]; spo2: number[] }> = {};
  for (let h = 0; h < 24; h++) byHour[h] = { hr: [], spo2: [] };
  for (const r of hr || []) {
    if (dayKeyFromTs(r.ts) !== selectedKey) continue;
    const h = new Date(r.ts).getHours();
    if (byHour[h]) byHour[h].hr.push(r.bpm);
  }
  for (const s of spo2 || []) {
    if (dayKeyFromTs(s.ts) !== selectedKey) continue;
    const h = new Date(s.ts).getHours();
    if (byHour[h]) byHour[h].spo2.push(s.spo2_pct);
  }

  const chartData = Array.from({ length: 24 }, (_, h) => {
    const hrs = byHour[h].hr;
    const sps = byHour[h].spo2;
    return {
      hour: h,
      label: `${String(h).padStart(2, "0")}:00`,
      hr: hrs.length ? hrs.reduce((a, b) => a + b, 0) / hrs.length : null,
      spo2: sps.length ? sps.reduce((a, b) => a + b, 0) / sps.length : null,
    };
  });

  // Latest SpO2 for summary
  const spo2Today = chartData.filter((d) => d.spo2 != null);
  const spo2Latest = spo2Today.length > 0 ? Math.round(spo2Today[spo2Today.length - 1].spo2!) : null;

  const today = todayKey();
  const yesterdayDate = new Date();
  yesterdayDate.setDate(yesterdayDate.getDate() - 1);
  const yesterday = dateKey(yesterdayDate);
  let dateLabel: string;
  if (selectedKey === today) dateLabel = "Today";
  else if (selectedKey === yesterday) dateLabel = "Yesterday";
  else dateLabel = new Date(selectedKey + "T00:00").toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
  const subtitle = `${dateLabel} — hourly averages`;

  if (isLoading && chartData.every((d) => d.hr == null && d.spo2 == null)) {
    return <Card className="p-6"><Skeleton className="h-56" /></Card>;
  }

  return (
    <Card className="p-6">
      <div className="flex justify-between items-baseline mb-1">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">Vitals</h2>
        {selectedKey !== today && (
          <span className="text-xs text-gray-500 dark:text-gray-400">{new Date(selectedKey + "T00:00").toLocaleDateString()}</span>
        )}
      </div>
      <p className="text-xs text-gray-500 dark:text-gray-400 mb-3">{subtitle}</p>
      <div style={{ minHeight: 120 }}>
        <ResponsiveContainer width="100%" height={165}>
          <LineChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" stroke="#374151" opacity={0.3} />
            <XAxis dataKey="hour" tick={{ fontSize: 10 }} ticks={[0, 6, 12, 18, 23]}
              tickFormatter={(h: unknown) => `${h}:00`} />
            <YAxis yAxisId="hr" domain={[40, 160]} tick={{ fontSize: 10 }} stroke="#3b82f6" />
            <YAxis yAxisId="spo2" orientation="right" domain={[88, 100]} tick={{ fontSize: 10 }} stroke="#14b8a6" />
            <Tooltip
              labelFormatter={(h: unknown) => `${String(h).padStart(2, "0")}:00 — hourly avg`}
              contentStyle={{ background: "#1f2937", border: "none", borderRadius: 6, fontSize: 12 }}
            />
            <Line yAxisId="hr" type="monotone" dataKey="hr" stroke="#3b82f6" dot={false} name="HR" connectNulls />
            <Line yAxisId="spo2" type="monotone" dataKey="spo2" stroke="#14b8a6" dot={false} name="SpO₂" connectNulls />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div className="border-t border-gray-100 dark:border-gray-700 pt-3 grid grid-cols-2 gap-2 text-xs">
        <div className="text-center">
          <p className="text-gray-500 dark:text-gray-400">🩸 SpO₂</p>
          <p className="font-bold text-sm mt-0.5 text-teal-500 dark:text-teal-400">{spo2Latest != null ? `${spo2Latest}%` : "—"}</p>
        </div>
        <div className="text-center">
          <p className="text-gray-500 dark:text-gray-400">Avg HR</p>
          <p className="font-bold text-sm mt-0.5 text-blue-600">
            {(chartData.filter((d) => d.hr != null).length > 0)
              ? `${Math.round(chartData.filter((d) => d.hr != null).reduce((a, b) => a + b.hr!, 0) / chartData.filter((d) => d.hr != null).length)} bpm`
              : "—"}
          </p>
        </div>
      </div>
    </Card>
  );
}
