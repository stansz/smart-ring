import { useEffect, useState } from "react";

/**
 * Returns true when `updatedAt` is within `windowMs` of the current time.
 *
 * Use this to surface "fresh data just arrived" indicators on cards whose
 * underlying query just refetched. The flip-back to false happens at the
 * exact moment the window expires (single setTimeout, no polling).
 *
 * Pass TanStack Query's `dataUpdatedAt` (ms epoch) directly.
 */
export function useFreshness(updatedAt: number | undefined, windowMs = 30_000): boolean {
  const [fresh, setFresh] = useState(false);

  useEffect(() => {
    if (updatedAt == null) {
      setFresh(false);
      return;
    }
    const age = Date.now() - updatedAt;
    if (age >= windowMs) {
      setFresh(false);
      return;
    }
    setFresh(true);
    const id = setTimeout(() => setFresh(false), windowMs - age);
    return () => clearTimeout(id);
  }, [updatedAt, windowMs]);

  return fresh;
}
