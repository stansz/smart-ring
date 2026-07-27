export function DataPipeline() {
  const rows = [
    ["Heart Rate", "Ring measured", "BPM from PPG sensor", "Resting HR (overnight avg), Circadian HR", "raw_heart_rate"],
    ["SpO₂", "Ring measured", "Blood oxygen %", "—", "raw_spo2"],
    ["Skin Temp", "Ring measured", "°C from sensor", "Overnight temp drop (for sleep context)", "raw_temperature"],
    ["Steps", "Ring measured", "Step count, calories, distance", "Active time (≥150 steps/15min)", "raw_steps"],
    ["HRV", "Ring computed", "Composite ms value (single byte)", "Recovery score — z-score vs 7-day baseline (Plews/Altini)", "raw_hrv → daily_recovery"],
    ["Sleep", "Ring computed", "Deep/REM/light/awake stages", "Sleep quality score — 5-component formula (Ohayon 2004)", "raw_sleep → sleep_quality"],
    ["Stress", "Ring computed", "0-99 scale (unknown algorithm)", "Classification — Garmin/Firstbeat thresholds + weighted daily score", "raw_stress → stress_classification"],
    ["Cardio Load / Strain", "Server computed", "5-min HR samples", "Edwards TRIMP strain (0-21), load labels, ACWR (Gabbett 2016)", "heart_rate_zones → strain_trend"],
  ];

  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 border border-gray-100 dark:border-gray-700 mb-8">
      <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-4">Data Pipeline</h2>
      <p className="text-xs text-gray-500 dark:text-gray-400 mb-4">
        The ring's firmware computes some values internally; our analytics layer adds validated health scores on top.
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-gray-500 dark:text-gray-400 border-b border-gray-200 dark:border-gray-700">
              <th className="pb-2 pr-4">Metric</th>
              <th className="pb-2 pr-4">Source</th>
              <th className="pb-2 pr-4">Ring Computes</th>
              <th className="pb-2 pr-4">We Compute</th>
              <th className="pb-2 pr-4">Table</th>
            </tr>
          </thead>
          <tbody className="text-gray-700 dark:text-gray-300">
            {rows.map(([metric, source, ring, we, table]) => (
              <tr key={metric} className="border-b border-gray-100 dark:border-gray-700">
                <td className="py-2 pr-4 font-medium">{metric}</td>
                <td className="py-2 pr-4">
                  <span className={`text-xs px-2 py-0.5 rounded ${source === "Ring measured" ? "bg-green-100 dark:bg-green-900 text-green-700 dark:text-green-300" : "bg-amber-100 dark:bg-amber-900 text-amber-700 dark:text-amber-300"}`}>
                    {source}
                  </span>
                </td>
                <td className="py-2 pr-4">{ring}</td>
                <td className="py-2 pr-4">{we}</td>
                <td className="py-2 pr-4 font-mono text-xs">{table}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
