import {
  useActivityDetail,
  useActivityHr,
  useActivityLaps,
} from "../../api/hooks";
import { Card } from "../ui";
import { ActivityHrChart } from "./ActivityHrChart";
import { ActivityLaps } from "./ActivityLaps";

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

function formatPace(speedMps: number | null | undefined): string {
  if (!speedMps || speedMps <= 0) return "—";
  const secPerKm = 1000 / speedMps;
  const m = Math.floor(secPerKm / 60);
  const s = Math.floor(secPerKm % 60);
  return `${m}:${s.toString().padStart(2, "0")}/km`;
}

interface ActivityDetailProps {
  id: number;
}

export function ActivityDetail({ id }: ActivityDetailProps) {
  const { data: activity, isLoading: detailLoading } = useActivityDetail(id);
  const { data: hr, isLoading: hrLoading } = useActivityHr(id);
  const { data: laps } = useActivityLaps(id);

  if (detailLoading || !activity) {
    return (
      <Card className="p-6">
        <p className="text-sm text-gray-500 dark:text-gray-400">Loading…</p>
      </Card>
    );
  }

  const icon = SPORT_ICONS[activity.activity_type] || SPORT_ICONS.other;
  const startDate = new Date(activity.start_ts);
  const dateStr = startDate.toLocaleDateString(undefined, {
    weekday: "short",
    year: "numeric",
    month: "short",
    day: "numeric",
  });
  const timeStr = startDate.toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
  });

  return (
    <div className="space-y-4">
      {/* Header card */}
      <Card className="p-4 sm:p-6">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <h2 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
              <span className="mr-2">{icon}</span>
              <span className="capitalize">{activity.activity_type}</span>
            </h2>
            <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
              {dateStr} at {timeStr}
              {activity.sub_sport && activity.sub_sport !== "generic" && (
                <span className="ml-2 text-xs px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-700 capitalize">
                  {activity.sub_sport.replace(/_/g, " ")}
                </span>
              )}
            </p>
          </div>
        </div>

        {/* Headline stats grid */}
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4 mt-5">
          <Stat label="Distance" value={formatDistance(activity.distance_m)} />
          <Stat label="Duration" value={formatDuration(activity.duration_s)} />
          <Stat label="Avg HR" value={activity.avg_hr ? `${activity.avg_hr} bpm` : "—"} />
          <Stat label="Max HR" value={activity.max_hr ? `${activity.max_hr} bpm` : "—"} />
          <Stat label="↑ Elevation" value={activity.elevation_gain_m ? `${activity.elevation_gain_m} m` : "—"} />
          <Stat label="Calories" value={activity.calories ? `${activity.calories}` : "—"} />
        </div>

        {/* Secondary stats */}
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4 mt-3 pt-3 border-t border-gray-100 dark:border-gray-700">
          <Stat label="Avg Pace" value={formatPace(activity.avg_speed_mps)} />
          <Stat label="Max Pace" value={formatPace(activity.max_speed_mps)} />
          <Stat label="Avg Cadence" value={activity.avg_cadence ? `${activity.avg_cadence} spm` : "—"} />
          <Stat label="Max Cadence" value={activity.max_cadence ? `${activity.max_cadence} spm` : "—"} />
          <Stat
            label="Training Effect"
            value={
              activity.training_effect_aerobic != null
                ? `${activity.training_effect_aerobic.toFixed(1)}${
                    activity.training_effect_anaerobic != null
                      ? ` / ${activity.training_effect_anaerobic.toFixed(1)}`
                      : ""
                  }`
                : "—"
            }
          />
          <Stat
            label="Total Strides"
            value={activity.total_strides ? String(activity.total_strides) : "—"}
          />
        </div>
      </Card>

      {/* HR Chart */}
      <Card className="p-4 sm:p-6">
        <div className="flex justify-between items-baseline mb-3">
          <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300">
            Heart Rate
          </h3>
          <div className="flex gap-3 text-xs text-gray-500 dark:text-gray-400">
            <Legend color="#22c55e" label="Z1" />
            <Legend color="#84cc16" label="Z2" />
            <Legend color="#eab308" label="Z3" />
            <Legend color="#f97316" label="Z4" />
            <Legend color="#ef4444" label="Z5" />
          </div>
        </div>
        {hrLoading ? (
          <p className="text-sm text-gray-500 dark:text-gray-400 py-8 text-center">
            Loading HR…
          </p>
        ) : (
          <ActivityHrChart data={hr || []} />
        )}
      </Card>

      {/* Laps */}
      <Card className="p-4 sm:p-6">
        <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3">
          Lap Splits
        </h3>
        <ActivityLaps laps={laps || []} />
      </Card>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wide">
        {label}
      </div>
      <div className="text-base font-semibold text-gray-900 dark:text-gray-100 tabular-nums">
        {value}
      </div>
    </div>
  );
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <span className="flex items-center gap-1">
      <span
        className="inline-block w-2 h-2 rounded-full"
        style={{ backgroundColor: color }}
      />
      {label}
    </span>
  );
}
