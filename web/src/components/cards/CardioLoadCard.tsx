import { useMemo } from "react";
import { LineChart, Line, ResponsiveContainer } from "recharts";
import { useHeartRateZones, useStrainTrend } from "../../api/hooks";
import { CountUp, FreshDot, Skeleton } from "../ui";

interface CardioLoadCardProps {
  selectedKey: string;
}

const LABEL_COLORS: Record<string, string> = {
  rest: "bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300",
  light: "bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300",
  moderate: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300",
  hard: "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300",
  very_hard: "bg-rose-100 text-rose-700 dark:bg-rose-900/40 dark:text-rose-300",
};

const TREND_ARROWS: Record<string, { symbol: string; text: string; color: string }> = {
  increasing: { symbol: "↗", text: "increasing", color: "text-amber-600 dark:text-amber-400" },
  decreasing: { symbol: "↘", text: "decreasing", color: "text-blue-600 dark:text-blue-400" },
  stable: { symbol: "→", text: "stable", color: "text-gray-500 dark:text-gray-400" },
};

// Zone bar colors (Z1 light → Z5 intense)
const ZONE_COLORS: Record<string, string> = {
  z1: "bg-cyan-300 dark:bg-cyan-600",
  z2: "bg-blue-400 dark:bg-blue-500",
  z3: "bg-emerald-400 dark:bg-emerald-500",
  z4: "bg-amber-400 dark:bg-amber-500",
  z5: "bg-rose-400 dark:bg-rose-500",
};

export function CardioLoadCard({ selectedKey }: CardioLoadCardProps) {
  const { data: zoneData, dataUpdatedAt, isLoading, isError, refetch } = useHeartRateZones(30);
  const { data: strainTrendData } = useStrainTrend(30);

  const zoneRow = zoneData?.find((r) => r.day === selectedKey);
  const trendRow = strainTrendData?.find((r) => r.day === selectedKey);

  // 7-day sparkline ending on selectedKey
  const sparklineData = useMemo(() => {
    if (!strainTrendData || strainTrendData.length === 0) return [];
    const idx = strainTrendData.findIndex((r) => r.day === selectedKey);
    const endIdx = idx !== -1 ? idx : strainTrendData.length - 1;
    const startIdx = Math.max(0, endIdx - 6);
    return strainTrendData.slice(startIdx, endIdx + 1).map((r) => ({
      day: r.day.slice(5),
      strain: Number(r.strain_today),
    }));
  }, [strainTrendData, selectedKey]);

  // Zone stacked bar segments
  const zones = zoneRow
    ? [
        { key: "z1", min: zoneRow.zone1_min },
        { key: "z2", min: zoneRow.zone2_min },
        { key: "z3", min: zoneRow.zone3_min },
        { key: "z4", min: zoneRow.zone4_min },
        { key: "z5", min: zoneRow.zone5_min },
      ]
    : [];
  const totalZoneMin = zones.reduce((s, z) => s + (z.min || 0), 0);

  const acwrVal = trendRow?.acwr ?? null;
  let acwrBand = "";
  let acwrColor = "";
  if (acwrVal !== null) {
    if (acwrVal >= 0.8 && acwrVal <= 1.3) {
      acwrBand = "Sweet Spot";
      acwrColor = "text-emerald-600 dark:text-emerald-400";
    } else if (acwrVal > 1.3) {
      acwrBand = acwrVal > 1.5 ? "Danger Zone" : "High Load";
      acwrColor = "text-amber-600 dark:text-amber-400";
    } else {
      acwrBand = "Low Load";
      acwrColor = "text-gray-500 dark:text-gray-400";
    }
  }

  if (isLoading) {
    return (
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 border border-gray-100 dark:border-gray-700">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-4">❤️ Cardio Load</h2>
        <Skeleton className="h-32" />
      </div>
    );
  }

  if (isError) {
    return (
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 border border-gray-100 dark:border-gray-700">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-4">❤️ Cardio Load</h2>
        <p className="text-sm text-rose-500">Failed to load cardio data.</p>
        <button onClick={() => refetch()} className="text-xs text-blue-600 mt-2 underline">Retry</button>
      </div>
    );
  }

  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 border border-gray-100 dark:border-gray-700 flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">❤️ Cardio Load<FreshDot updatedAt={dataUpdatedAt} /></h2>
        {trendRow && (
          <span className={`px-2 py-0.5 rounded-full text-xs font-medium uppercase ${LABEL_COLORS[trendRow.load_label] || "bg-gray-100 text-gray-700"}`}>
            {trendRow.load_label.replace("_", " ")}
          </span>
        )}
      </div>

      {!zoneRow ? (
        <div className="flex-1 flex items-center justify-center py-8">
          <p className="text-sm text-gray-500 dark:text-gray-400">No HR data for this day</p>
        </div>
      ) : (
        <>
          {/* Hero: strain number + trend */}
          <div className="flex items-baseline gap-3 mb-4">
            <p className="text-4xl font-bold text-blue-600 dark:text-blue-400">
              <CountUp
                value={zoneRow ? Number(zoneRow.strain_score) : null}
                format={(n) => n.toFixed(1)}
              />
            </p>
            <span className="text-sm text-gray-500 dark:text-gray-400">/ 21</span>
            {trendRow && TREND_ARROWS[trendRow.trend_direction] && (
              <span className={`text-sm ${TREND_ARROWS[trendRow.trend_direction].color}`}>
                {TREND_ARROWS[trendRow.trend_direction].symbol} {TREND_ARROWS[trendRow.trend_direction].text}
              </span>
            )}
          </div>

          {/* Zone stacked bar */}
          <div className="mb-2">
            {totalZoneMin > 0 ? (
              <div className="flex w-full h-3 rounded-full overflow-hidden bg-gray-100 dark:bg-gray-700">
                {zones.filter((z) => z.min > 0).map((z) => (
                  <div
                    key={z.key}
                    className={ZONE_COLORS[z.key]}
                    style={{ width: `${(z.min / totalZoneMin) * 100}%` }}
                    title={`Z${z.key.slice(1)}: ${z.min}m`}
                  />
                ))}
              </div>
            ) : (
              <div className="flex w-full h-3 rounded-full bg-gray-100 dark:bg-gray-700 items-center justify-center">
                <span className="text-[10px] text-gray-500 dark:text-gray-400">Rest day</span>
              </div>
            )}
          </div>

          {/* Zone caption */}
          <div className="text-xs text-gray-500 dark:text-gray-400 mb-4">
            Cardio Load Time: <strong className="text-gray-700 dark:text-gray-300">{zoneRow.elevated_min}m</strong>
            {zoneRow.peak_zone > 0 && (
              <> · Peak: <strong className="text-gray-700 dark:text-gray-300">Z{zoneRow.peak_zone}</strong></>
            )}
          </div>

          {/* Sparkline + ACWR */}
          <div className="flex items-end justify-between gap-4">
            {sparklineData.length > 1 && (
              <div className="flex-1 h-10">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={sparklineData} margin={{ top: 2, right: 2, bottom: 2, left: 2 }}>
                    <Line type="monotone" dataKey="strain" stroke="#3b82f6" strokeWidth={2} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            )}
            <div className="text-right text-xs">
              {acwrVal !== null ? (
                <>
                  <p className="text-gray-500 dark:text-gray-400">ACWR</p>
                  <p className={`font-semibold ${acwrColor}`}>{acwrVal}</p>
                  <p className={`text-[10px] ${acwrColor}`}>{acwrBand}</p>
                </>
              ) : (
                <>
                  <p className="text-gray-500 dark:text-gray-400">ACWR</p>
                  <p className="italic text-gray-500 dark:text-gray-400 text-[10px]">Building baseline…</p>
                </>
              )}
            </div>
          </div>
        </>
      )}

      {/* Footer */}
      <div className="mt-auto pt-4 border-t border-gray-100 dark:border-gray-700">
        <p className="text-xs text-gray-500 dark:text-gray-400 leading-relaxed">
          Cardiovascular load from HR zones (Edwards TRIMP, 0–21). Walking stays low — it's movement, not cardio work. Lights up on sustained elevated HR.
        </p>
      </div>
    </div>
  );
}
