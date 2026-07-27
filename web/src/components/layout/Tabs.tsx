type Tab = "dashboard" | "analytics" | "admin";

interface TabsProps {
  tab: Tab;
  onSwitch: (t: Tab) => void;
}

export function Tabs({ tab, onSwitch }: TabsProps) {
  const tabs: { key: Tab; label: string }[] = [
    { key: "dashboard", label: "Dashboard" },
    { key: "analytics", label: "Analytics" },
    { key: "admin", label: "Admin" },
  ];

  return (
    <>
      {/* Desktop tabs */}
      <div className="hidden sm:flex space-x-1" role="tablist">
        {tabs.map((t) => (
          <button
            key={t.key}
            role="tab"
            aria-selected={tab === t.key}
            onClick={() => onSwitch(t.key)}
            className={`px-3 py-1.5 text-sm rounded-md transition ${
              tab === t.key
                ? "bg-blue-600 text-white"
                : "text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>
      {/* Mobile dropdown */}
      <select
        value={tab}
        onChange={(e) => onSwitch(e.target.value as Tab)}
        aria-label="Select tab"
        className="sm:hidden px-3 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100"
      >
        {tabs.map((t) => (
          <option key={t.key} value={t.key}>
            {t.label}
          </option>
        ))}
      </select>
    </>
  );
}
