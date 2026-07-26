import { useRawHeartRate, useRawSteps } from "../../api/hooks";

export function RawTables() {
  const { data: hr } = useRawHeartRate(24, 50);
  const { data: steps } = useRawSteps(168, 50);

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 mb-8">
      {/* Heart Rate */}
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow border border-gray-100 dark:border-gray-700 p-6">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-3">Recent HR</h2>
        <div className="overflow-x-auto max-h-64 overflow-y-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-gray-500 dark:text-gray-400 border-b border-gray-200 dark:border-gray-700 sticky top-0 bg-white dark:bg-gray-800">
              <tr><th className="pb-2">Time</th><th className="pb-2">BPM</th></tr>
            </thead>
            <tbody>
              {hr?.map((r, i) => (
                <tr key={i} className="border-b border-gray-100 dark:border-gray-700/50">
                  <td className="py-1.5 text-gray-600 dark:text-gray-300">{new Date(r.ts).toLocaleTimeString()}</td>
                  <td className="py-1.5 font-mono text-gray-900 dark:text-gray-100">{r.bpm}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Steps */}
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow border border-gray-100 dark:border-gray-700 p-6">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-3">Recent Steps</h2>
        <div className="overflow-x-auto max-h-64 overflow-y-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-gray-500 dark:text-gray-400 border-b border-gray-200 dark:border-gray-700 sticky top-0 bg-white dark:bg-gray-800">
              <tr><th className="pb-2">Time</th><th className="pb-2">Steps</th><th className="pb-2">Distance</th></tr>
            </thead>
            <tbody>
              {steps?.map((r, i) => (
                <tr key={i} className="border-b border-gray-100 dark:border-gray-700/50">
                  <td className="py-1.5 text-gray-600 dark:text-gray-300">{new Date(r.ts).toLocaleTimeString()}</td>
                  <td className="py-1.5 font-mono text-gray-900 dark:text-gray-100">{r.steps}</td>
                  <td className="py-1.5 font-mono text-gray-900 dark:text-gray-100">{r.distance ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
