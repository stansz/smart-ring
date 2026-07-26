import { useState, useCallback } from "react";
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
  const [tab, setTab] = useState<Tab>("dashboard");
  const { darkMode, toggle: toggleDark } = useTheme();
  const { selectedKey, isToday, prevDay, nextDay, goToday, formatSelectedDate } = useSelectedDate();
  const { busy, error: syncError, dismissError, startSync, handleCancel, progress } = useSyncPolling();
  const { phase, error: bleError, complete, dismiss, sync: syncFromPhone } = useRingSync();

  const onTabSwitch = useCallback((t: Tab) => setTab(t), []);

  const syncButtons = (
    <div className="flex items-center gap-1">
      <button
        onClick={syncFromPhone}
        disabled={!!phase || busy}
        className="px-2 py-0.5 text-xs bg-green-600 text-white rounded disabled:bg-gray-300 dark:disabled:bg-gray-600"
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
