interface DateNavProps {
  isToday: boolean;
  prevDay: () => void;
  nextDay: () => void;
  goToday: () => void;
  formatSelectedDate: () => string;
}

export function DateNav({ isToday, prevDay, nextDay, goToday, formatSelectedDate }: DateNavProps) {
  return (
    <div className="flex items-center justify-center gap-4 mb-6">
      <button
        onClick={prevDay}
        className="px-4 py-2.5 sm:px-3 sm:py-1.5 rounded-lg bg-white dark:bg-gray-800 shadow border border-gray-100 dark:border-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition"
      >
        <span className="text-lg">←</span>
      </button>
      <div className="text-center min-w-0 flex-1">
        <p className="text-lg font-semibold text-gray-900 dark:text-gray-100">{formatSelectedDate()}</p>
        {!isToday && (
          <button onClick={goToday} className="text-xs text-blue-600 hover:underline">
            Jump to today
          </button>
        )}
      </div>
      <button
        onClick={nextDay}
        disabled={isToday}
        className="px-4 py-2.5 sm:px-3 sm:py-1.5 rounded-lg bg-white dark:bg-gray-800 shadow border border-gray-100 dark:border-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-30 disabled:cursor-not-allowed transition"
      >
        <span className="text-lg">→</span>
      </button>
    </div>
  );
}
