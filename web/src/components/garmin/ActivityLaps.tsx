import type { ActivityLapRow } from "../../api/types";

function formatDuration(s: number | null | undefined): string {
  if (s == null) return "—";
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${sec.toString().padStart(2, "0")}`;
}

function formatDistance(m: number | null | undefined): string {
  if (m == null) return "—";
  if (m >= 1000) return `${(m / 1000).toFixed(2)} km`;
  return `${m} m`;
}

function formatPace(speedMps: number | null | undefined): string {
  if (!speedMps || speedMps <= 0) return "—";
  const secPerKm = 1000 / speedMps;
  const m = Math.floor(secPerKm / 60);
  const s = Math.floor(secPerKm % 60);
  return `${m}:${s.toString().padStart(2, "0")}/km`;
}

interface ActivityLapsProps {
  laps: ActivityLapRow[];
}

export function ActivityLaps({ laps }: ActivityLapsProps) {
  if (laps.length === 0) {
    return (
      <p className="text-sm text-gray-500 dark:text-gray-400 italic">
        No lap data
      </p>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-gray-500 dark:text-gray-400 border-b border-gray-200 dark:border-gray-700">
            <th className="py-2 px-2 font-medium">#</th>
            <th className="py-2 px-2 font-medium text-right">Duration</th>
            <th className="py-2 px-2 font-medium text-right">Distance</th>
            <th className="py-2 px-2 font-medium text-right hidden sm:table-cell">Pace</th>
            <th className="py-2 px-2 font-medium text-right">Avg HR</th>
            <th className="py-2 px-2 font-medium text-right hidden sm:table-cell">Max HR</th>
            <th className="py-2 px-2 font-medium text-right hidden md:table-cell">Cal</th>
            <th className="py-2 px-2 font-medium text-right hidden md:table-cell">↑m</th>
          </tr>
        </thead>
        <tbody>
          {laps.map((lap) => (
            <tr
              key={lap.lap_index}
              className="border-b border-gray-100 dark:border-gray-800"
            >
              <td className="py-2 px-2 text-gray-500 dark:text-gray-400 tabular-nums">
                {lap.lap_index + 1}
              </td>
              <td className="py-2 px-2 text-right tabular-nums text-gray-700 dark:text-gray-300">
                {formatDuration(lap.duration_s)}
              </td>
              <td className="py-2 px-2 text-right tabular-nums text-gray-700 dark:text-gray-300">
                {formatDistance(lap.distance_m)}
              </td>
              <td className="py-2 px-2 text-right tabular-nums text-gray-700 dark:text-gray-300 hidden sm:table-cell">
                {formatPace(lap.avg_speed_mps)}
              </td>
              <td className="py-2 px-2 text-right tabular-nums text-gray-700 dark:text-gray-300">
                {lap.avg_hr ?? "—"}
              </td>
              <td className="py-2 px-2 text-right tabular-nums text-gray-700 dark:text-gray-300 hidden sm:table-cell">
                {lap.max_hr ?? "—"}
              </td>
              <td className="py-2 px-2 text-right tabular-nums text-gray-700 dark:text-gray-300 hidden md:table-cell">
                {lap.calories ?? "—"}
              </td>
              <td className="py-2 px-2 text-right tabular-nums text-gray-700 dark:text-gray-300 hidden md:table-cell">
                {lap.elevation_gain_m ?? "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
