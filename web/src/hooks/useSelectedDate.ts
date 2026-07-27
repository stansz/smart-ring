import { useState, useCallback, useMemo } from "react";
import { dateKey } from "../utils/date";

export function useSelectedDate() {
  const [selectedDate, setSelectedDate] = useState(() => new Date());

  const todayKey = dateKey(new Date());
  const selectedKey = useMemo(() => dateKey(selectedDate), [selectedDate]);
  const isToday = selectedKey === todayKey;

  const prevDay = useCallback(() => {
    setSelectedDate((d) => {
      const n = new Date(d);
      n.setDate(n.getDate() - 1);
      return n;
    });
  }, []);

  const nextDay = useCallback(() => {
    setSelectedDate((d) => {
      if (dateKey(d) === dateKey(new Date())) return d; // don't go past today
      const n = new Date(d);
      n.setDate(n.getDate() + 1);
      return n;
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
