/**
 * Pure math helpers for the DayRing SVG — extracted from legacy renderDayRing().
 * Polar coordinates, arc paths, and timestamp-to-day-minute conversion.
 */

/** Convert polar coords (cx, cy, radius, degrees from top/12-o'clock) to SVG x,y. */
export function polar(cx: number, cy: number, r: number, deg: number): [number, number] {
  const a = ((deg - 90) * Math.PI) / 180;
  return [cx + r * Math.cos(a), cy + r * Math.sin(a)];
}

/** SVG arc path for a filled circular segment between inner and outer radii. */
export function arc(
  cx: number, cy: number, rOut: number, rIn: number,
  startDeg: number, endDeg: number,
): string {
  const [x1, y1] = polar(cx, cy, rOut, startDeg);
  const [x2, y2] = polar(cx, cy, rOut, endDeg);
  const [x3, y3] = polar(cx, cy, rIn, endDeg);
  const [x4, y4] = polar(cx, cy, rIn, startDeg);
  const large = endDeg - startDeg <= 180 ? 0 : 1;
  return `M ${x1.toFixed(2)} ${y1.toFixed(2)} `
    + `A ${rOut} ${rOut} 0 ${large} 1 ${x2.toFixed(2)} ${y2.toFixed(2)} `
    + `L ${x3.toFixed(2)} ${y3.toFixed(2)} `
    + `A ${rIn} ${rIn} 0 ${large} 0 ${x4.toFixed(2)} ${y4.toFixed(2)} Z`;
}

/** Convert a timestamp and dayKey to minutes-of-day (0–1440+ for overnight spans). */
export function tsToDayMinutes(ts: string, dayKey: string): number {
  const d = new Date(ts);
  let mins = d.getHours() * 60 + d.getMinutes();
  const tsDate = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  if (tsDate !== dayKey) {
    // If ts is the next day, keep going past 1440; if previous day, wrap negative.
    const diffMs = d.getTime() - new Date(dayKey + "T00:00").getTime();
    mins = diffMs / 60000;
  }
  return mins;
}
