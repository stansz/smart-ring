interface ErrorBannerProps {
  error: string | null;
  onDismiss: () => void;
}

export function ErrorBanner({ error, onDismiss }: ErrorBannerProps) {
  if (!error) return null;
  return (
    <div
      onClick={onDismiss}
      className="bg-red-50 dark:bg-red-900/30 border-b border-red-200 dark:border-red-800 text-red-700 dark:text-red-400 text-sm px-4 py-2 text-center cursor-pointer"
    >
      <span>{error}</span>
      <span className="ml-2 opacity-50 text-xs">(click to dismiss)</span>
    </div>
  );
}

export function SyncButtons({ busy, startSync, handleCancel, progress }: {
  busy: boolean;
  startSync: () => void;
  handleCancel: () => void;
  progress?: { current_step?: string | null };
}) {
  const status = progress?.current_step || (busy ? "..." : null);
  return (
    <div className="flex items-center gap-1">
      <button
        onClick={startSync}
        disabled={busy}
        className={`px-3 py-1.5 text-xs sm:px-2 sm:py-0.5 rounded inline-flex items-center gap-1 ${busy ? "bg-gray-300 dark:bg-gray-600 cursor-not-allowed" : "bg-blue-600 text-white hover:bg-blue-700"}`}
      >
        {busy && (
          <svg className="animate-spin h-3 w-3" viewBox="0 0 24 24" fill="none">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
        )}
        <span>{busy ? (status || "...") : "Sync"}</span>
      </button>
      {busy && (
        <button onClick={handleCancel} className="px-3 py-1.5 text-xs sm:px-2 sm:py-0.5 bg-red-600 text-white rounded hover:bg-red-700">
          Cancel
        </button>
      )}
    </div>
  );
}
