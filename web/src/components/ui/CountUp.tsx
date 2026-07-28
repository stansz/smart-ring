import { useCountUp } from "../../hooks/useCountUp";

interface CountUpProps {
  /** Target value. Pass null/undefined to render the placeholder ("—"). */
  value: number | null | undefined;
  /** Animation duration in ms (default 700). */
  durationMs?: number;
  /** Format the animated number for display. Default: round to integer. */
  format?: (n: number) => string;
  className?: string;
}

/**
 * Animated number display. Wraps useCountUp so consumers can drop a live
 * counter anywhere a static number used to live:
 *
 *   <CountUp value={score} />                                    // "78"
 *   <CountUp value={hrvAvg} format={(n) => `${Math.round(n)}ms`} />  // "42ms"
 *   <CountUp value={steps} format={(n) => Math.round(n).toLocaleString()} />
 *
 * When value is null/undefined, renders "—" with no animation.
 */
export function CountUp({ value, durationMs, format, className }: CountUpProps) {
  const display = useCountUp(value ?? 0, durationMs);
  if (value == null) return <span className={className}>—</span>;
  const text = format ? format(display) : Math.round(display).toString();
  return <span className={className}>{text}</span>;
}
