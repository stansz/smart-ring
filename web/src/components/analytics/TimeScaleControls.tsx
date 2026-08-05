/**
 * Preset day-range selector + custom date-range picker for the Analytics tab.
 *
 * One shared window state (`{start, end}` ISO date keys) drives all trend
 * charts. Presets set the window to `[today-N, today]`; the date inputs set
 * an arbitrary window. If the current window doesn't match a preset pattern,
 * no preset button is highlighted (it's a "custom" range).
 *
 * Constraints:
 *  - `end` capped at today
 *  - `start` capped at `today - 180d` (matches the max fetch window)
 *  - `start` ≤ `end`
 */

import { todayKey, dateKey } from "../../utils/date";

const PRESETS = [3, 7, 14, 30, 90, 180] as const;
const MAX_LOOKBACK_DAYS = 180;

interface TimeScaleControlsProps {
  start: string;
  end: string;
  onChange: (start: string, end: string) => void;
}

function addDays(key: string, n: number): string {
  const d = new Date(key + "T00:00:00");
  d.setDate(d.getDate() + n);
  return dateKey(d);
}

export function TimeScaleControls({ start, end, onChange }: TimeScaleControlsProps) {
  const today = todayKey();
  const earliest = addDays(today, -MAX_LOOKBACK_DAYS);

  // Active preset: only when end=today AND span matches exactly.
  const activePreset =
    end === today
      ? PRESETS.find((p) => start === addDays(today, -p)) ?? null
      : null;

  const handlePreset = (days: number) => {
    onChange(addDays(today, -days), today);
  };

  const handleStart = (value: string) => {
    if (!value) return;
    // Clamp: start ≤ end.
    const clamped = value > end ? end : value;
    onChange(clamped, end);
  };

  const handleEnd = (value: string) => {
    if (!value) return;
    // Clamp: end ≥ start AND end ≤ today.
    let clamped = value;
    if (clamped > today) clamped = today;
    if (clamped < start) clamped = start;
    onChange(start, clamped);
  };

  return (
    <div className="flex flex-wrap items-center gap-3">
      <div className="flex space-x-1">
        {PRESETS.map((d) => (
          <button
            key={d}
            onClick={() => handlePreset(d)}
            className={`px-3 py-1 text-xs rounded transition ${
              activePreset === d
                ? "bg-blue-600 text-white"
                : "text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700"
            }`}
          >
            {d}d
          </button>
        ))}
      </div>

      <div className="flex items-center gap-1 text-xs">
        <input
          type="date"
          value={start}
          min={earliest}
          max={end}
          onChange={(e) => handleStart(e.target.value)}
          className="px-2 py-1 rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100 text-xs"
        />
        <span className="text-gray-400 dark:text-gray-500">→</span>
        <input
          type="date"
          value={end}
          min={start}
          max={today}
          onChange={(e) => handleEnd(e.target.value)}
          className="px-2 py-1 rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100 text-xs"
        />
      </div>
    </div>
  );
}
