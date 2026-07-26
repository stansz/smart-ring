interface SyncProgressDialogProps {
  phase: string | null;
  onDismiss: () => void;
}

export function SyncProgressDialog({ phase, onDismiss }: SyncProgressDialogProps) {
  if (!phase) return null;

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/60" onClick={onDismiss}>
      <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-2xl p-8 max-w-sm w-[90%] text-center" onClick={(e) => e.stopPropagation()}>
        <div className="animate-spin rounded-full h-12 w-12 border-4 border-gray-200 dark:border-gray-600 border-t-blue-600 mx-auto mb-5" />
        <p className="text-lg font-semibold text-gray-900 dark:text-gray-100">{phase}</p>
        <p className="text-xs text-gray-400 dark:text-gray-500 mt-3">Keep this screen on</p>
      </div>
    </div>
  );
}

interface SyncToastProps {
  message: string;
  onDismiss: () => void;
}

export function SyncToast({ message, onDismiss }: SyncToastProps) {
  if (!message) return null;

  return (
    <div
      className="fixed bottom-4 right-4 z-50 px-4 py-3 rounded-lg shadow-lg text-white text-sm cursor-pointer bg-blue-600"
      onClick={onDismiss}
    >
      {message}
    </div>
  );
}
