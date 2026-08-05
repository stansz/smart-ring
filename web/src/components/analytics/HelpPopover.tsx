/**
 * Collapsible methodology reference for the Analytics tab.
 *
 * Replaces the always-visible DataPipeline table + Research References block
 * that used to live inline on the page. The information is still there, but
 * tucked behind a `<details>` expander so it doesn't compete with the trends.
 *
 * Uses native `<details><summary>` (matches the "How this works" expanders
 * previously in ScoreCards) — zero custom state, zero deps.
 */

const PIPELINE_ROWS: [string, string, string, string, string][] = [
  ["Heart Rate", "Ring measured", "BPM from PPG sensor", "Resting HR (overnight avg), Circadian HR", "raw_heart_rate"],
  ["SpO₂", "Ring measured", "Blood oxygen %", "Daily avg trend", "raw_spo2"],
  ["Skin Temp", "Ring measured", "°C from sensor", "Overnight temp drop (for sleep context)", "raw_temperature"],
  ["Steps", "Ring measured", "Step count, calories, distance", "Daily total (server-computed)", "daily_activity"],
  ["HRV", "Ring computed", "Composite ms value (single byte)", "Recovery score — z-score vs 7-day baseline (Plews/Altini)", "raw_hrv → daily_recovery"],
  ["Sleep", "Ring computed", "Deep/REM/light/awake stages", "Sleep quality score — 5-component formula (Ohayon 2004)", "raw_sleep → sleep_quality"],
  ["Stress", "Ring computed", "0-99 scale (unknown algorithm)", "Classification — Garmin/Firstbeat thresholds + weighted daily score", "raw_stress → stress_classification"],
  ["Cardio Load / Strain", "Server computed", "5-min HR samples", "Edwards TRIMP strain (0-21), load labels, ACWR (Gabbett 2016)", "heart_rate_zones → strain_trend"],
];

const SOURCE_BADGE: Record<string, string> = {
  "Ring measured": "bg-green-100 dark:bg-green-900 text-green-700 dark:text-green-300",
  "Ring computed": "bg-amber-100 dark:bg-amber-900 text-amber-700 dark:text-amber-300",
  "Server computed": "bg-amber-100 dark:bg-amber-900 text-amber-700 dark:text-amber-300",
};

export function HelpPopover() {
  return (
    <details className="bg-white dark:bg-gray-800 rounded-lg shadow border border-gray-100 dark:border-gray-700 mb-8">
      <summary className="cursor-pointer px-6 py-3 text-sm text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-100 transition">
        ⓘ Data pipeline & research references
      </summary>

      <div className="px-6 pb-6 space-y-6 border-t border-gray-100 dark:border-gray-700 pt-4">
        {/* Pipeline table */}
        <div>
          <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-2">Data pipeline</h3>
          <p className="text-xs text-gray-500 dark:text-gray-400 mb-3">
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
                {PIPELINE_ROWS.map(([metric, source, ring, we, table]) => (
                  <tr key={metric} className="border-b border-gray-100 dark:border-gray-700">
                    <td className="py-2 pr-4 font-medium">{metric}</td>
                    <td className="py-2 pr-4">
                      <span className={`text-xs px-2 py-0.5 rounded ${SOURCE_BADGE[source] ?? ""}`}>
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

        {/* Research citations */}
        <div>
          <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-2">Research references</h3>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs text-gray-600 dark:text-gray-400">
            <div>
              <p className="font-semibold text-gray-700 dark:text-gray-300">Sleep Quality</p>
              <p>Ohayon, M. M., et al. (2004). "Meta-analysis of quantitative sleep parameters." <em>Sleep</em>, 27(7), 1255-1273. (3,327 citations)</p>
            </div>
            <div>
              <p className="font-semibold text-gray-700 dark:text-gray-300">HRV Recovery</p>
              <p>Plews, D. J., et al. (2017). "Monitoring training with HRV." <em>Frontiers in Physiology</em>. Altini, M. (2021). <em>Sensors</em>, 21(7). (9M measurements)</p>
            </div>
            <div>
              <p className="font-semibold text-gray-700 dark:text-gray-300">Stress Classification</p>
              <p>Garmin/Firstbeat thresholds (0-25/26-50/51-75/76-100). <em>Frontiers in Physiology</em>, 2025, for circadian stress patterns.</p>
            </div>
            <div>
              <p className="font-semibold text-gray-700 dark:text-gray-300">Trapezoidal Scoring</p>
              <p>Inspired by Oura's reverse-engineered algorithms (Chheda). R²=0.846 correlation with Oura sleep scores.</p>
            </div>
            <div>
              <p className="font-semibold text-gray-700 dark:text-gray-300">Training Load & ACWR</p>
              <p>Gabbett, T. J. (2016). "The training-injury paradox: acute:chronic workload ratios." <em>Br J Sports Med</em>, 50(5), 273-275. Edwards TRIMP methodology for cardiovascular strain (0-21).</p>
            </div>
          </div>
        </div>
      </div>
    </details>
  );
}
