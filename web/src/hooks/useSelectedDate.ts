import { useState, useCallback, useMemo } from "react";

function dateKey(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export function useSelectedDate() {
  const [selectedDate, setSelectedDate] = useState(() => new Date());

  const todayKey = dateKey(new Date());
  const selectedKey = useMemo(() => dateKey(selectedDate), [selectedDate]);
  const isToday = selectedKey === todayKey;

  const prevDay = useCallback(() => {
    setSelectedDate((d) => new Date(d.getTime() - 86_400_000));
  }, []);

  const nextDay = useCallback(() => {
    setSelectedDate((d) => {
      if (dateKey(d) === dateKey(new Date())) return d; // don't go past today
      return new Date(d.getTime() + 86_400_000);
    });
  }, []);

  const goToday = useCallback(() => setSelectedDate(new Date()), []);

  const formatSelectedDate = useCallback((): string => {
    if (isToday) return "Today";
    const yesterday = new Date();
    yesterday.setDate(yesterday.getDate() - 1);
    if (dateKey(selectedDate) === dateKey(yesterday)) return "Yesterday";
    return selectedDate.toLocaleDateString(undefined, {
      weekday: "short",
      month: "short",
      day: "numeric",
    });
  }, [selectedDate, isToday]);

  return { selectedDate, selectedKey, isToday, prevDay, nextDay, goToday, formatSelectedDate } as const;
}
