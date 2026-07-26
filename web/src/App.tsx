import { useState, useEffect, useCallback } from "react";
import { Nav } from "./components/layout/Nav";
import { DashboardTab } from "./tabs/DashboardTab";
import { AnalyticsTab } from "./tabs/AnalyticsTab";
import { AdminTab } from "./tabs/AdminTab";
import { ErrorBanner, SyncButtons } from "./components/sync/SyncButton";
import { SyncProgressDialog, SyncToast } from "./components/ble/SyncProgressDialog";
import { useTheme } from "./hooks/useTheme";
import { useSelectedDate } from "./hooks/useSelectedDate";
import { useSyncPolling } from "./hooks/useSyncPolling";
import { useRingSync } from "./hooks/useRingSync";

type Tab = "dashboard" | "analytics" | "admin";

function App() {
  const [tab, setTab] = useState<Tab>(() => {
    if (typeof window === "undefined") return "dashboard";
    const h = window.location.hash.replace("#", "");
    return h === "analytics" || h === "admin" ? h : "dashboard";
  });
  const { darkMode, toggle: toggleDark } = useTheme();
  const { selectedKey, isToday, prevDay, nextDay, goToday, formatSelectedDate } = useSelectedDate();
  const { busy, error: syncError, dismissError, startSync, handleCancel, progress } = useSyncPolling();
  const { phase, error: bleError, complete, dismiss, sync: syncFromPhone } = useRingSync();

  const onTabSwitch = useCallback((t: Tab) => setTab(t), []);

  // Sync URL hash so PWA shortcuts (#analytics) and browser back/forward work.
  useEffect(() => {
    const hash = tab === "dashboard" ? "" : `#${tab}`;
    if (window.location.hash !== hash) {
      window.history.replaceState(null, "", hash ? `/static/${hash}` : "/static/");
    }
  }, [tab]);

  const syncButtons = (
    <div className="flex items-center gap-1">
      <button
        onClick={syncFromPhone}
        disabled={!!phase || busy}
        className="px-3 py-1.5 text-xs sm:px-2 sm:py-0.5 bg-green-600 text-white rounded disabled:bg-gray-300 dark:disabled:bg-gray-600"
      >
        📱 BLE
      </button>
      <SyncButtons busy={busy} startSync={startSync} handleCancel={handleCancel} progress={progress} />
    </div>
  );

  return (
    <div className="bg-gray-50 dark:bg-gray-900 min-h-screen">
      <ErrorBanner error={syncError} onDismiss={dismissError} />
      <SyncProgressDialog phase={phase} onDismiss={dismiss} />
      <SyncToast message={complete ? bleError! : (bleError && !phase ? bleError : "")} onDismiss={dismiss} />
      <Nav
        tab={tab} onTabSwitch={onTabSwitch} darkMode={darkMode} onToggleDark={toggleDark}
        syncButtons={syncButtons}
      />
      {tab === "dashboard" && (
        <DashboardTab
          selectedKey={selectedKey}
          isToday={isToday}
          prevDay={prevDay}
          nextDay={nextDay}
          goToday={goToday}
          formatSelectedDate={formatSelectedDate}
          darkMode={darkMode}
        />
      )}
      {tab === "analytics" && <AnalyticsTab />}
      {tab === "admin" && <AdminTab />}
    </div>
  );
}

export default App;
