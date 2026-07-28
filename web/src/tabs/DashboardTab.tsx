import { DateNav } from "../components/layout/DateNav";
import { DayRing } from "../components/charts/DayRing";
import { VitalsChart } from "../components/charts/VitalsChart";
import { CircadianChart } from "../components/charts/CircadianChart";
import { ReadinessHero } from "../components/cards/ReadinessHero";
import { CurrentStatusPanel } from "../components/cards/CurrentStatusPanel";
import { RecoveryCard } from "../components/cards/RecoveryCard";
import { CardioLoadCard } from "../components/cards/CardioLoadCard";
import { SleepSection } from "../components/cards/SleepSection";
import { DataQualityBanner } from "../components/cards/DataQuality";
import { Skeleton, Card, FreshDot } from "../components/ui";
import { useDailyActivity, useRawSleep } from "../api/hooks";

interface DashboardTabProps {
  selectedKey: string; isToday: boolean;
  prevDay: () => void; nextDay: () => void; goToday: () => void;
  formatSelectedDate: () => string; darkMode: boolean;
}

export function DashboardTab({
  selectedKey, isToday, prevDay, nextDay, goToday, formatSelectedDate, darkMode,
}: DashboardTabProps) {
  const { data: dailyData, dataUpdatedAt: dailyUpdatedAt, isLoading } = useDailyActivity(60);
  const { data: rawSleep } = useRawSleep(720, 1000);

  const dayRow = dailyData?.find((r) => r.day === selectedKey);
  const daySleep = rawSleep?.filter((s) => s.day === selectedKey && s.start_ts) || [];

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
            <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-1 self-start">Activity<FreshDot updatedAt={dailyUpdatedAt} /></h2>
            <DayRing row={dayRow} sleepStages={daySleep} darkMode={darkMode} dayKey={selectedKey} />
          </div>
          <ReadinessHero selectedKey={selectedKey} />
        </div>
      </Card>

      {/* 2. Current Status */}
      <CurrentStatusPanel selectedKey={selectedKey} isToday={isToday} />

      {/* 3. 2-col grid: Recovery + Cardio Load + Sleep + Vitals + Circadian */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-6 mb-8">
        <RecoveryCard selectedKey={selectedKey} />
        <CardioLoadCard selectedKey={selectedKey} />
        <SleepSection selectedKey={selectedKey} />
        <VitalsChart hours={48} selectedKey={selectedKey} />
        <CircadianChart />
      </div>
    </main>
  );
}
