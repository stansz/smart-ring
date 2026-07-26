import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from "recharts";
import { useSleep } from "../../api/hooks";

const COLORS = { deep: "#4338ca", rem: "#a855f7", light: "#60a5fa", awake: "#fb923c" };

export function SleepDonut() {
  const { data } = useSleep(14);

  const latest = data?.[0];
  if (!latest) return null;

  const donutData = [
    { name: "Deep", value: latest.deep_min, color: COLORS.deep },
    { name: "REM", value: latest.rem_min, color: COLORS.rem },
    { name: "Light", value: latest.light_min, color: COLORS.light },
    { name: "Awake", value: latest.awake_min, color: COLORS.awake },
  ].filter((d) => d.value > 0);

  const total = donutData.reduce((a, b) => a + b.value, 0);

  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow border border-gray-100 dark:border-gray-700 p-6 mb-8">
      <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-3">Sleep</h2>
      <div className="flex items-center gap-6">
        <div style={{ width: 180, height: 180 }}>
          <ResponsiveContainer>
            <PieChart>
              <Pie data={donutData} dataKey="value" innerRadius={40} outerRadius={80} paddingAngle={2}>
                {donutData.map((d) => (
                  <Cell key={d.name} fill={d.color} />
                ))}
              </Pie>
              <Tooltip
                contentStyle={{ background: "#1f2937", border: "none", borderRadius: 6, fontSize: 12 }}
              />
            </PieChart>
          </ResponsiveContainer>
        </div>
        <div className="text-sm space-y-2">
          <p className="font-semibold text-gray-900 dark:text-gray-100">
            {latest.score != null ? `Score: ${latest.score}` : "No score"}
          </p>
          <p className="text-gray-500 dark:text-gray-400">Total: {total}m</p>
          {donutData.map((d) => (
            <div key={d.name} className="flex items-center gap-2">
              <span className="w-3 h-3 rounded-full" style={{ background: d.color }} />
              <span className="text-gray-600 dark:text-gray-300">{d.name}: {d.value}m</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
