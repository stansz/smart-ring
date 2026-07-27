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
