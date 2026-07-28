import { useEffect, useRef, useState } from "react";

// easeOutCubic: fast attack, gentle settle. Feels responsive without dragging.
const easeOutCubic = (t: number) => 1 - Math.pow(1 - t, 3);

/**
 * Animate a number from its previous value to a new target using requestAnimationFrame.
 *
 * - On mount: animates 0 → target (gives cards an entrance feel as they load).
 * - On target change: animates from the current displayed value (which may be
 *   mid-animation) to the new target — so rapid data updates look continuous.
 * - Cancels the RAF on unmount or target change (no leaked frames).
 *
 * Returns the currently-displayed (animated) value. The consumer is expected
 * to format it (round, fixed decimals, locale string, suffix, etc).
 */
export function useCountUp(target: number, durationMs = 700): number {
  const [display, setDisplay] = useState(0);
  // Mirror of `display` that stays current across animation frames without
  // re-triggering the effect (avoids stale-closure when target changes mid-flight).
  const displayRef = useRef(0);

  useEffect(() => {
    const from = displayRef.current;
    if (from === target) return;

    const start = performance.now();
    let rafId: number;

    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / durationMs);
      const value = from + (target - from) * easeOutCubic(t);
      displayRef.current = value;
      setDisplay(value);
      if (t < 1) {
        rafId = requestAnimationFrame(tick);
      }
    };

    rafId = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafId);
  }, [target, durationMs]);

  return display;
}
