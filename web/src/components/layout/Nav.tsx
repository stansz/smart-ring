import { useCallback, useRef, useState, type ReactNode } from "react";
import { useIsFetching, useQueryClient } from "@tanstack/react-query";
import { Tabs } from "./Tabs";
import { BatteryIndicator } from "./BatteryIndicator";
import { SensorFreshnessNav } from "./SensorFreshnessNav";
import { useRingStatus } from "../../api/hooks";
import { useRelativeTime } from "../../hooks/useRelativeTime";

type Tab = "dashboard" | "analytics" | "garmin" | "admin";

interface NavProps {
  tab: Tab;
  onTabSwitch: (t: Tab) => void;
  darkMode: boolean;
  onToggleDark: () => void;
  syncButtons?: ReactNode;
}

/** True when the app is running as an installed PWA (Android Chrome or iOS Safari). */
function isStandalonePwa(): boolean {
  if (typeof window === "undefined") return false;
  const standaloneDisplay = window.matchMedia?.("(display-mode: standalone)").matches === true;
  const iosStandalone = (window.navigator as Navigator & { standalone?: boolean }).standalone === true;
  return standaloneDisplay || iosStandalone;
}

export function Nav({ tab, onTabSwitch, darkMode, onToggleDark, syncButtons }: NavProps) {
  const { data: ring } = useRingStatus();
  const queryClient = useQueryClient();
  const isFetching = useIsFetching();
  const lastSyncIso = ring?.last_sync?.completed_at ?? null;
  const lastSyncDesktop = lastSyncIso
    ? "Last sync: " + new Date(lastSyncIso).toLocaleString()
    : "—";
  const lastSyncMobile = useRelativeTime(lastSyncIso);
  const showRefreshButton = isStandalonePwa();

  // Local "refreshing" state: holds the spinner for a minimum duration so the
  // action is perceptible. A local-API refetch often completes in <50ms, and
  // the server data is usually identical (no new sync happened), so the only
  // feedback the user gets is the spinner itself.
  const [refreshing, setRefreshing] = useState(false);
  const refreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const handleRefresh = useCallback(() => {
    setRefreshing(true);
    queryClient.invalidateQueries();
    if (refreshTimer.current) clearTimeout(refreshTimer.current);
    refreshTimer.current = setTimeout(() => setRefreshing(false), 600);
  }, [queryClient]);
  const showSpinner = refreshing || isFetching > 0;

  return (
    <nav className="bg-white dark:bg-gray-800 shadow-sm border-b border-gray-200 dark:border-gray-700 sticky top-0 z-50 [padding-top:env(safe-area-inset-top)]">
      <div className="max-w-7xl mx-auto px-3 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-12 sm:h-10">
          <div className="flex items-center space-x-2 sm:space-x-4 min-w-0">
            <h1 className="text-sm sm:text-xl font-semibold text-gray-900 dark:text-gray-100 truncate">Stan's Ring</h1>
            <Tabs tab={tab} onSwitch={onTabSwitch} />
          </div>
          <div className="flex items-center space-x-1 sm:space-x-4">
            {showRefreshButton && (
              <button
                onClick={handleRefresh}
                disabled={showSpinner}
                className="p-1.5 sm:p-1 rounded hover:bg-gray-200 dark:hover:bg-gray-700 transition disabled:opacity-50 disabled:cursor-not-allowed text-gray-700 dark:text-gray-300"
                aria-label="Refresh data"
                title="Refresh data"
              >
                <svg
                  className={showSpinner ? "animate-spin" : ""}
                  width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                  strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"
                >
                  <path d="M21 12a9 9 0 1 1-3-6.7" />
                  <polyline points="21 4 21 10 15 10" />
                </svg>
              </button>
            )}
            <button onClick={onToggleDark} className="text-lg px-2 py-1.5 sm:text-lg sm:px-1 sm:py-0.5 rounded hover:bg-gray-200 dark:hover:bg-gray-700 transition" aria-label="Toggle dark mode">
              {darkMode ? "☀️" : "🌙"}
            </button>
            <span className="hidden sm:inline text-sm text-gray-500 dark:text-gray-400">{lastSyncDesktop}</span>
          </div>
        </div>
        <div className="flex items-center justify-between h-11 sm:h-7 text-sm sm:text-xs">
          <div className="flex items-center gap-2 sm:gap-3 min-w-0">
            <BatteryIndicator />
            <SensorFreshnessNav />
          </div>
          {syncButtons && <div className="flex items-center gap-1">{syncButtons}</div>}
        </div>
        {/* Mobile-only: synced time on its own line so sensor chips don't crowd it out */}
        <div className="sm:hidden flex items-center justify-end h-5 text-xs text-gray-500 dark:text-gray-400">
          {lastSyncIso ? `Synced ${lastSyncMobile}` : "No sync yet"}
        </div>
      </div>
    </nav>
  );
}
