import { useState } from "react";
import { useActivities } from "../../api/hooks";
import type { ActivityRow } from "../../api/types";
import { Card } from "../ui";

const SPORT_FILTERS = ["all", "walking", "running", "cycling", "other"] as const;
type SportFilter = (typeof SPORT_FILTERS)[number];

const SPORT_ICONS: Record<string, string> = {
  walking: "🚶",
  running: "🏃",
  cycling: "🚴",
  swimming: "🏊",
  hiking: "🥾",
  skiing: "⛷️",
  strength_training: "🏋️",
  yoga: "🧘",
  other: "ⓘ",
};

function formatDuration(s: number | null | undefined): string {
  if (!s) return "—";
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${sec}s`;
  return `${sec}s`;
}

function formatDistance(m: number | null | undefined): string {
  if (m == null) return "—";
  if (m >= 1000) return `${(m / 1000).toFixed(2)} km`;
  return `${m} m`;
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

interface ActivitiesListProps {
  selectedId: number | null;
  onSelect: (id: number) => void;
}

export function ActivitiesList({ selectedId, onSelect }: ActivitiesListProps) {
  const [sport, setSport] = useState<SportFilter>("all");
  const { data: activities, isLoading } = useActivities(
    365,
    sport === "all" ? undefined : sport,
    30,
  );

  return (
    <Card className="p-4 sm:p-6">
      <div className="flex flex-wrap justify-between items-center mb-4 gap-2">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
          Activities
        </h2>
        <div className="flex flex-wrap gap-1">
          {SPORT_FILTERS.map((s) => (
            <button
              key={s}
              onClick={() => setSport(s)}
              className={`px-2.5 py-1 text-xs rounded capitalize transition ${
                sport === s
                  ? "bg-blue-600 text-white"
                  : "text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700"
              }`}
            >
              {s}
            </button>
          ))}
        </div>
      </div>

      {isLoading && (
        <p className="text-sm text-gray-500 dark:text-gray-400 py-8 text-center">
          Loading…
        </p>
      )}

      {!isLoading && activities && activities.length === 0 && (
        <div className="py-12 text-center">
          <p className="text-sm text-gray-500 dark:text-gray-400">
            No activities ingested yet. Use the upload button above to import
            FIT files from your watch&apos;s USB drive.
          </p>
        </div>
      )}

      {activities && activities.length > 0 && (
        <div className="overflow-x-auto -mx-4 sm:mx-0">
          <table className="min-w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-gray-500 dark:text-gray-400 border-b border-gray-200 dark:border-gray-700">
                <th className="py-2 px-2 font-medium">Sport</th>
                <th className="py-2 px-2 font-medium">Date</th>
                <th className="py-2 px-2 font-medium text-right">Distance</th>
                <th className="py-2 px-2 font-medium text-right">Duration</th>
                <th className="py-2 px-2 font-medium text-right hidden sm:table-cell">Avg HR</th>
                <th className="py-2 px-2 font-medium text-right hidden sm:table-cell">Max HR</th>
                <th className="py-2 px-2 font-medium text-right hidden md:table-cell">↑m</th>
                <th className="py-2 px-2 font-medium text-right hidden md:table-cell">TE</th>
              </tr>
            </thead>
            <tbody>
              {activities.map((a: ActivityRow) => (
                <tr
                  key={a.id}
                  onClick={() => onSelect(a.id)}
                  className={`cursor-pointer border-b border-gray-100 dark:border-gray-800 transition ${
                    selectedId === a.id
                      ? "bg-blue-50 dark:bg-blue-900/30"
                      : "hover:bg-gray-50 dark:hover:bg-gray-800/50"
                  }`}
                >
                  <td className="py-2 px-2 whitespace-nowrap">
                    <span className="mr-1.5">
                      {SPORT_ICONS[a.activity_type] || SPORT_ICONS.other}
                    </span>
                    <span className="text-gray-700 dark:text-gray-300 capitalize">
                      {a.activity_type}
                    </span>
                  </td>
                  <td className="py-2 px-2 text-gray-600 dark:text-gray-400 whitespace-nowrap">
                    {formatDate(a.start_ts)}
                  </td>
                  <td className="py-2 px-2 text-right tabular-nums text-gray-700 dark:text-gray-300 whitespace-nowrap">
                    {formatDistance(a.distance_m)}
                  </td>
                  <td className="py-2 px-2 text-right tabular-nums text-gray-700 dark:text-gray-300 whitespace-nowrap">
                    {formatDuration(a.duration_s)}
                  </td>
                  <td className="py-2 px-2 text-right tabular-nums text-gray-700 dark:text-gray-300 hidden sm:table-cell">
                    {a.avg_hr ?? "—"}
                  </td>
                  <td className="py-2 px-2 text-right tabular-nums text-gray-700 dark:text-gray-300 hidden sm:table-cell">
                    {a.max_hr ?? "—"}
                  </td>
                  <td className="py-2 px-2 text-right tabular-nums text-gray-700 dark:text-gray-300 hidden md:table-cell">
                    {a.elevation_gain_m ?? "—"}
                  </td>
                  <td className="py-2 px-2 text-right tabular-nums text-gray-700 dark:text-gray-300 hidden md:table-cell">
                    {a.training_effect_aerobic?.toFixed(1) ?? "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {activities && activities.length > 0 && (
        <p className="mt-3 text-xs text-gray-400 dark:text-gray-500">
          {activities.length} activit{activities.length === 1 ? "y" : "ies"} •
          Click a row for HR chart + lap splits
        </p>
      )}
    </Card>
  );
}
