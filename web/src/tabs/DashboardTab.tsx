import { DateNav } from "../components/layout/DateNav";
import { DayRing } from "../components/charts/DayRing";
import { VitalsChart } from "../components/charts/VitalsChart";
import { CircadianChart } from "../components/charts/CircadianChart";
import { ReadinessHero } from "../components/cards/ReadinessHero";
import { CurrentStatusPanel } from "../components/cards/CurrentStatusPanel";
import { RecoveryCard } from "../components/cards/RecoveryCard";
import { SleepSection } from "../components/cards/SleepSection";
import { DataQualityBanner } from "../components/cards/DataQuality";
import { Skeleton, Card } from "../components/ui";
import { useDailyActivity, useRawSleep, useHeartRateZones, useStrainTrend } from "../api/hooks";

interface DashboardTabProps {
  selectedKey: string; isToday: boolean;
  prevDay: () => void; nextDay: () => void; goToday: () => void;
  formatSelectedDate: () => string; darkMode: boolean;
}

export function DashboardTab({
  selectedKey, isToday, prevDay, nextDay, goToday, formatSelectedDate, darkMode,
}: DashboardTabProps) {
  const { data: dailyData, isLoading } = useDailyActivity(60);
  const { data: rawSleep } = useRawSleep(720, 1000);
  const { data: zoneData } = useHeartRateZones(60);
  const { data: strainTrendData } = useStrainTrend(60);

  const dayRow = dailyData?.find((r) => r.day === selectedKey);
  const daySleep = rawSleep?.filter((s) => s.day === selectedKey && s.start_ts) || [];
  const zoneRow = zoneData?.find((r) => r.day === selectedKey);
  const trendRow = strainTrendData?.find((r) => r.day === selectedKey);

  const labelColors: Record<string, string> = {
    rest: "bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300",
    light: "bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300",
    moderate: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300",
    hard: "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300",
    very_hard: "bg-rose-100 text-rose-700 dark:bg-rose-900/40 dark:text-rose-300",
  };

  const trendArrows: Record<string, { symbol: string; text: string; color: string }> = {
    increasing: { symbol: "↗", text: "increasing", color: "text-amber-600 dark:text-amber-400" },
    decreasing: { symbol: "↘", text: "decreasing", color: "text-blue-600 dark:text-blue-400" },
    stable: { symbol: "→", text: "stable", color: "text-gray-500 dark:text-gray-400" },
  };

  if (isLoading && !dayRow) {
    return (
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <DateNav isToday={isToday} prevDay={prevDay} nextDay={nextDay} goToday={goToday} formatSelectedDate={formatSelectedDate} />
        <Card className="mb-8 p-6"><div className="grid grid-cols-1 lg:grid-cols-2 gap-6"><Skeleton className="h-64" /><Skeleton className="h-64" /></div></Card>
        <Card className="mb-8 p-6"><Skeleton className="h-32" /></Card>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-6 mb-8">
          <Skeleton className="h-48" /><Skeleton className="h-48" />
          <Skeleton className="h-56" /><Skeleton className="h-56" />
        </div>
      </main>
    );
  }

  return (
    <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      <DateNav isToday={isToday} prevDay={prevDay} nextDay={nextDay} goToday={goToday} formatSelectedDate={formatSelectedDate} />
      {isToday && <DataQualityBanner />}

      {/* 1. Hero: DayRing + Readiness */}
      <Card className="mb-8">
        <div className="grid grid-cols-1 lg:grid-cols-2 divide-y lg:divide-y-0 lg:divide-x divide-gray-100 dark:divide-gray-700">
          <div className="px-6 py-4 flex flex-col items-center">
            <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-1 self-start">Activity</h2>
            <DayRing row={dayRow} sleepStages={daySleep} darkMode={darkMode} dayKey={selectedKey} />
            {zoneRow && (
              <div className="mt-3 w-full max-w-xs text-center text-sm text-gray-600 dark:text-gray-400">
                <div className="flex items-center justify-center gap-2 mb-1">
                  <span className="font-semibold text-blue-600 dark:text-blue-400">
                    Strain: {Number(zoneRow.strain_score).toFixed(1)} / 21
                  </span>
                  {trendRow && (
                    <span className={`px-2 py-0.5 rounded-full text-xs font-medium uppercase ${labelColors[trendRow.load_label] || "bg-gray-100 text-gray-700"}`}>
                      {trendRow.load_label.replace("_", " ")}
                    </span>
                  )}
                </div>
                <div className="flex items-center justify-center gap-2 text-xs">
                  <span>Cardio Load Time: <strong className="text-gray-900 dark:text-gray-100">{zoneRow.elevated_min}m</strong></span>
                  {trendRow && trendArrows[trendRow.trend_direction] && (
                    <>
                      <span>·</span>
                      <span className={trendArrows[trendRow.trend_direction].color}>
                        {trendArrows[trendRow.trend_direction].symbol} {trendArrows[trendRow.trend_direction].text}
                      </span>
                    </>
                  )}
                </div>
              </div>
            )}
          </div>
          <ReadinessHero selectedKey={selectedKey} />
        </div>
      </Card>

      {/* 2. Current Status */}
      <CurrentStatusPanel selectedKey={selectedKey} isToday={isToday} />

      {/* 3. 2-col grid: Recovery + Sleep + Vitals + Circadian */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-6 mb-8">
        <RecoveryCard selectedKey={selectedKey} />
        <SleepSection selectedKey={selectedKey} />
        <VitalsChart hours={48} selectedKey={selectedKey} />
        <CircadianChart />
      </div>
    </main>
  );
}
