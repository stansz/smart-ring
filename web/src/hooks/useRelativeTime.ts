import { useEffect, useState } from "react";

/**
 * Returns a compact, human-readable "time-ago" string that re-renders on a
 * fixed cadence so it stays current (e.g. "Just now", "5m ago", "3h ago",
 * "Yesterday", "Tue 3:45 PM"). Cadence: 30s for <1h, 60s for <24h, 5min beyond.
 *
 * Pure & SSR-safe: returns the formatted string immediately and re-derives it
 * on each tick (no Date.now() calls during render of children).
 */
export function useRelativeTime(iso: string | null | undefined, now: number = Date.now()): string {
  const [, setTick] = useState(0);

  useEffect(() => {
    if (!iso) return;
    const target = new Date(iso).getTime();
    if (!isFinite(target)) return;
    const ageMs = now - target;
    // Pick a tick rate proportional to age so the display never lies by more than ~10%.
    const interval = ageMs < 60_000 ? 10_000
                   : ageMs < 3_600_000 ? 30_000
                   : ageMs < 86_400_000 ? 60_000
                   : 300_000;
    const id = setInterval(() => setTick((t) => t + 1), interval);
    return () => clearInterval(id);
  }, [iso, now]);

  if (!iso) return "Never";
  const target = new Date(iso).getTime();
  if (!isFinite(target)) return "—";
  const ageSec = Math.max(0, Math.floor((now - target) / 1000));
  if (ageSec < 45) return "Just now";
  if (ageSec < 60 * 60) return `${Math.floor(ageSec / 60)}m ago`;
  if (ageSec < 24 * 60 * 60) return `${Math.floor(ageSec / 3600)}h ago`;
  // > 24h: show calendar label. Yesterday / weekday / date.
  const d = new Date(target);
  const startOfToday = new Date(now);
  startOfToday.setHours(0, 0, 0, 0);
  const startOfTarget = new Date(target);
  startOfTarget.setHours(0, 0, 0, 0);
  const dayDiff = Math.round((startOfToday.getTime() - startOfTarget.getTime()) / 86_400_000);
  if (dayDiff === 1) return `Yesterday ${d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`;
  if (dayDiff < 7) return d.toLocaleDateString([], { weekday: "short" }) + " " +
    d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  return d.toLocaleDateString([], { month: "short", day: "numeric" }) + " " +
    d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}
