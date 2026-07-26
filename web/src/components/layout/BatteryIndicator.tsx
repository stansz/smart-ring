import { useRingStatus } from "../../api/hooks";

function BatterySVG({ pct }: { pct: number }) {
  const fillWidth = Math.round((pct * 14) / 100);
  return (
    <svg className="w-4 h-3" viewBox="0 0 24 24" fill="currentColor">
      <rect x="1" y="5" width="18" height="14" rx="2" fill="none" stroke="currentColor" strokeWidth="2" />
      <rect x="20" y="9" width="2" height="6" rx="1" fill="currentColor" />
      <rect x="3" y="7" width={fillWidth} height="10" rx="1" fill="currentColor" />
    </svg>
  );
}

function batteryColor(pct: number): string {
  if (pct >= 50) return "text-green-600 dark:text-green-400";
  if (pct >= 20) return "text-amber-600 dark:text-amber-400";
  return "text-red-500 dark:text-red-400";
}

export function BatteryIndicator() {
  const { data } = useRingStatus();
  const pct = data?.ring?.battery_pct;
  if (pct == null) return null;

  return (
    <span className={`flex items-center gap-1 text-xs ${batteryColor(pct)}`}>
      <BatterySVG pct={pct} />
      <span>{pct}%</span>
    </span>
  );
}
