/**
 * Local-day utilities.
 *
 * The DB stores TIMESTAMPTZ (UTC instants). The frontend must group by *local*
 * calendar day. Using `new Date().toISOString().slice(0,10)` gives the **UTC**
 * day — wrong after ~5pm Pacific (flips to "tomorrow" early). Using
 * `r.ts.slice(0,10)` on a TIMESTAMPTZ string reads the UTC date portion, which
 * disagrees with `new Date(r.ts).getHours()` (local) near midnight.
 *
 * These helpers convert instants to the LOCAL day uniformly.
 */

/** Format a Date as local YYYY-MM-DD. */
export function dateKey(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** Today's local day key. */
export function todayKey(): string {
  return dateKey(new Date());
}

/** Convert a UTC ISO timestamp string to the LOCAL day key it falls on. */
export function dayKeyFromTs(ts: string): string {
  return dateKey(new Date(ts));
}

/**
 * Bucket raw timestamped rows by local day, averaging the given numeric field.
 *
 * Uses `dayKeyFromTs` so rows near midnight land on the correct local day —
 * the old `r.ts.slice(0, 10)` pattern was wrong after ~5pm Pacific (it returns
 * the UTC date, which flips ahead of the local date).
 *
 * Returns one `{day, value}` per day that has at least one valid sample,
 * sorted ascending by day. Rows with null / non-finite values are skipped.
 */
export function aggregateByDay<T extends { ts: string }>(
  rows: T[] | undefined | null,
  valueKey: keyof T,
): { day: string; value: number }[] {
  if (!rows) return [];
  const map = new Map<string, { sum: number; n: number }>();
  for (const r of rows) {
    const v = r[valueKey];
    if (typeof v !== "number" || !Number.isFinite(v as number)) continue;
    const day = dayKeyFromTs(r.ts);
    const bucket = map.get(day) ?? { sum: 0, n: 0 };
    bucket.sum += v as number;
    bucket.n += 1;
    map.set(day, bucket);
  }
  return [...map.entries()]
    .map(([day, { sum, n }]) => ({ day, value: sum / n }))
    .sort((a, b) => a.day.localeCompare(b.day));
}

/**
 * Bucket raw timestamped rows by local hour, averaging or summing the given numeric field.
 *
 * Returns one `{day, value}` per hour that has at least one valid sample,
 * sorted ascending. The `day` field contains an ISO timestamp truncated to
 * the hour (e.g., "2024-01-15T14:00:00") so the chart can display hour labels.
 * Rows with null / non-finite values are skipped.
 *
 * @param mode "avg" (default) for instantaneous measurements like HR, temp
 *             "sum" for cumulative measurements like steps
 */
export function aggregateByHour<T extends { ts: string }>(
  rows: T[] | undefined | null,
  valueKey: keyof T,
  mode: "avg" | "sum" = "avg",
): { day: string; value: number }[] {
  if (!rows) return [];
  const map = new Map<string, { sum: number; n: number }>();
  for (const r of rows) {
    const v = r[valueKey];
    if (typeof v !== "number" || !Number.isFinite(v as number)) continue;
    const d = new Date(r.ts);
    // Truncate to hour in local time
    d.setMinutes(0, 0, 0);
    const hourKey = d.toISOString();
    const bucket = map.get(hourKey) ?? { sum: 0, n: 0 };
    bucket.sum += v as number;
    bucket.n += 1;
    map.set(hourKey, bucket);
  }
  return [...map.entries()]
    .map(([day, { sum, n }]) => ({ day, value: mode === "sum" ? sum : sum / n }))
    .sort((a, b) => a.day.localeCompare(b.day));
}
