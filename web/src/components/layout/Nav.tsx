import type { ReactNode } from "react";
import { Tabs } from "./Tabs";
import { BatteryIndicator } from "./BatteryIndicator";
import { useRingStatus } from "../../api/hooks";

type Tab = "dashboard" | "analytics" | "admin";

interface NavProps {
  tab: Tab;
  onTabSwitch: (t: Tab) => void;
  darkMode: boolean;
  onToggleDark: () => void;
  syncButtons?: ReactNode;
}

export function Nav({ tab, onTabSwitch, darkMode, onToggleDark, syncButtons }: NavProps) {
  const { data: ring } = useRingStatus();
  const lastSync = ring?.last_sync?.completed_at
    ? "Last sync: " + new Date(ring.last_sync.completed_at).toLocaleString()
    : "—";

  return (
    <nav className="bg-white dark:bg-gray-800 shadow-sm border-b border-gray-200 dark:border-gray-700 sticky top-0 z-50 [padding-top:env(safe-area-inset-top)]">
      <div className="max-w-7xl mx-auto px-3 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-12 sm:h-12">
          <div className="flex items-center space-x-2 sm:space-x-4 min-w-0">
            <h1 className="text-sm sm:text-xl font-semibold text-gray-900 dark:text-gray-100 truncate">Stan's Ring</h1>
            <Tabs tab={tab} onSwitch={onTabSwitch} />
          </div>
          <div className="flex items-center space-x-1 sm:space-x-4">
            <button onClick={onToggleDark} className="text-lg px-2 py-1.5 sm:text-lg sm:px-1 sm:py-0.5 rounded hover:bg-gray-200 dark:hover:bg-gray-700 transition" aria-label="Toggle dark mode">
              {darkMode ? "☀️" : "🌙"}
            </button>
            <span className="hidden sm:inline text-sm text-gray-500 dark:text-gray-400">{lastSync}</span>
          </div>
        </div>
        <div className="flex items-center justify-between h-11 sm:h-7 text-sm sm:text-xs">
          <BatteryIndicator />
          {syncButtons && <div className="flex items-center gap-1">{syncButtons}</div>}
        </div>
      </div>
    </nav>
  );
}
