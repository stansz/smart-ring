import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";

interface TrendChartProps {
  data: { day: string; value: number | null }[];
  title: string;
  description: string;
  color: string;
}

export function TrendChart({ data, title, description, color }: TrendChartProps) {
  const chartData = data
    .filter((d) => d.value != null)
    .map((d) => ({ day: d.day.slice(5), value: d.value as number, fullDay: d.day }))
    .sort((a, b) => a.fullDay.localeCompare(b.fullDay));

  if (chartData.length < 2) {
    return (
      <div>
        <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-2">{title}</h3>
        <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">{description}</p>
        <p className="text-sm text-gray-500 dark:text-gray-400 italic">{chartData.length === 0 ? "No data yet" : "Need more data points"}</p>
      </div>
    );
  }

  return (
    <div>
      <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-2">{title}</h3>
      <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">{description}</p>
      <div style={{ minHeight: 140 }}>
        <ResponsiveContainer width="100%" height={140}>
          <LineChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" stroke="#374151" opacity={0.3} />
            <XAxis dataKey="day" tick={{ fontSize: 9 }} interval="preserveStartEnd" />
            <YAxis tick={{ fontSize: 10 }} domain={["auto", "auto"]} />
            <Tooltip
              labelFormatter={(t: unknown, payload: any) => {
                const item = (payload as { payload?: { fullDay?: string } }[])?.[0]?.payload;
                return item?.fullDay ? new Date(item.fullDay + "T00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" }) : String(t);
              }}
              contentStyle={{ background: "#1f2937", border: "none", borderRadius: 6, fontSize: 12 }}
            />
            <Line type="monotone" dataKey="value" stroke={color} dot={false} strokeWidth={2} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
