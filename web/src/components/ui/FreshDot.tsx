import { useFreshness } from "../../hooks/useFreshness";

interface FreshDotProps {
  /** TanStack Query's dataUpdatedAt (ms epoch), or any timestamp. */
  updatedAt?: number;
  /** Freshness window in ms (default 30s). */
  windowMs?: number;
  className?: string;
}

/**
 * Tiny pulse dot that signals "this card's data just refreshed".
 *
 * Stays mounted at 6×6px to avoid layout shift; just toggles between
 * transparent and a pulsing emerald dot. Drop next to a card title:
 *
 *   <h2>Recovery <FreshDot updatedAt={dataUpdatedAt} /></h2>
 *
 * The dot appears for 30s after each query refetch — long enough to
 * notice a sync landed, short enough not to feel stale.
 */
export function FreshDot({ updatedAt, windowMs, className = "" }: FreshDotProps) {
  const fresh = useFreshness(updatedAt, windowMs);
  return (
    <span
      className={`inline-block w-1.5 h-1.5 rounded-full transition-colors align-middle ml-1 ${
        fresh ? "bg-emerald-400 animate-pulse" : "bg-transparent"
      } ${className}`}
      title={fresh ? "Fresh data" : undefined}
      aria-hidden={!fresh}
    />
  );
}
