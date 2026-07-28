import { useEffect, useRef, useState } from "react";
import { useDailyActivity, useSleep, useUserGoals, useUpdateUserGoal } from "../../api/hooks";
import { Card, CountUp, FreshDot, Skeleton } from "../ui";

interface GoalsCardProps {
  selectedKey: string;
}

/** Format minutes as "Xh Ym" (e.g., 480 → "8h 0m", 432 → "7h 12m"). */
function fmtHours(min: number): string {
  const h = Math.floor(min / 60);
  const m = Math.round(min % 60);
  return `${h}h ${m}m`;
}

/**
 * One row in the goals card: label, current/goal, progress bar, editable goal.
 *
 * Edit UX: click ✏️ → text input appears pre-filled with current goal →
 * Enter or blur saves (validated >0), Escape cancels. The mutation invalidates
 * the useUserGoals query so the new value flows back via React Query.
 */
function GoalRow({
  label,
  current,
  goal,
  formatValue,
  onSaveGoal,
  updatedAt,
}: {
  label: string;
  current: number;
  goal: number;
  formatValue: (n: number) => string;
  onSaveGoal: (n: number) => void;
  updatedAt?: number;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(String(goal));
  const inputRef = useRef<HTMLInputElement>(null);

  // Keep draft in sync when the goal prop changes (e.g., after mutation lands)
  useEffect(() => { setDraft(String(goal)); }, [goal]);
  useEffect(() => {
    if (editing) inputRef.current?.select();
  }, [editing]);

  const safeGoal = Math.max(1, goal);
  const rawPct = (current / safeGoal) * 100;
  const pct = Math.min(100, rawPct);
  const achieved = rawPct >= 100;

  const commit = () => {
    const n = parseInt(draft, 10);
    if (Number.isFinite(n) && n > 0 && n !== goal) onSaveGoal(n);
    setEditing(false);
  };

  return (
    <div className="mb-4 last:mb-0">
      <div className="flex items-baseline justify-between mb-1.5">
        <span className="text-sm text-gray-600 dark:text-gray-400">{label}</span>
        <span className="text-sm font-medium" title="Edit goal">
          {editing ? (
            <span className="inline-flex items-center gap-1">
              <input
                ref={inputRef}
                type="number"
                min={1}
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onBlur={commit}
                onKeyDown={(e) => {
                  if (e.key === "Enter") commit();
                  if (e.key === "Escape") { setDraft(String(goal)); setEditing(false); }
                }}
                className="w-20 px-1.5 py-0.5 text-sm border border-gray-300 dark:border-gray-600 rounded bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100"
              />
              <span className="text-xs text-gray-400">↵ save</span>
            </span>
          ) : (
            <span
              className="cursor-pointer hover:text-gray-700 dark:hover:text-gray-200 inline-flex items-center gap-1"
              onClick={() => setEditing(true)}
            >
              <CountUp value={current} format={formatValue} className={achieved ? "text-emerald-600 dark:text-emerald-400" : ""} />
              <span className="text-gray-400 dark:text-gray-500 font-normal">/ {formatValue(goal)}</span>
              <span className="ml-0.5 text-gray-300 dark:text-gray-600 select-none hover:text-gray-500 dark:hover:text-gray-300" aria-label="Edit goal">✏️</span>
              <FreshDot updatedAt={updatedAt} />
            </span>
          )}
        </span>
      </div>
      <div className="flex w-full h-2.5 rounded-full overflow-hidden bg-gray-100 dark:bg-gray-700">
        <div
          className={`transition-[width] duration-500 ease-out ${
            achieved ? "bg-emerald-400" : "bg-blue-400 dark:bg-blue-500"
          }`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="flex justify-between mt-0.5">
        <span className="text-[10px] text-gray-400 dark:text-gray-500">
          {achieved ? "✓ goal hit" : `${Math.round(rawPct)}%`}
        </span>
      </div>
    </div>
  );
}

export function GoalsCard({ selectedKey }: GoalsCardProps) {
  const { data: goals, isLoading: goalsLoading } = useUserGoals();
  const { data: daily, dataUpdatedAt: dailyUpdatedAt } = useDailyActivity(60);
  const { data: sleep, dataUpdatedAt: sleepUpdatedAt } = useSleep(30);
  const updateGoal = useUpdateUserGoal();

  const dayRow = daily?.find((r) => r.day === selectedKey);
  const sleepRow = sleep?.find((r) => r.day === selectedKey);

  const stepsToday = dayRow?.steps_total ?? 0;
  const sleepMinToday = sleepRow?.total_sleep_minutes ?? 0;

  if (goalsLoading) {
    return (
      <Card className="p-6">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-4">🎯 Daily Targets</h2>
        <Skeleton className="h-24" />
      </Card>
    );
  }

  return (
    <Card className="p-6">
      <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-4">
        🎯 Daily Targets
        <FreshDot updatedAt={Math.max(dailyUpdatedAt ?? 0, sleepUpdatedAt ?? 0)} />
      </h2>
      <GoalRow
        label="Steps"
        current={stepsToday}
        goal={goals?.steps_goal ?? 5000}
        formatValue={(n) => Math.round(n).toLocaleString()}
        onSaveGoal={(n) => updateGoal.mutate({ steps_goal: n })}
        updatedAt={dailyUpdatedAt}
      />
      <GoalRow
        label="Sleep"
        current={sleepMinToday}
        goal={goals?.sleep_min_goal ?? 480}
        formatValue={fmtHours}
        onSaveGoal={(n) => updateGoal.mutate({ sleep_min_goal: n })}
        updatedAt={sleepUpdatedAt}
      />
      <p className="mt-3 pt-3 border-t border-gray-100 dark:border-gray-700 text-xs text-gray-500 dark:text-gray-400 leading-relaxed">
        Your own targets — click ✏️ to edit. Stored server-side, independent of the ring's firmware defaults.
      </p>
    </Card>
  );
}
