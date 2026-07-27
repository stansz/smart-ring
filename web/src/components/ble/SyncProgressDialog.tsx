import { useEffect } from "react";

interface SyncProgressDialogProps {
  phase: string | null;
  onDismiss: () => void;
}

export function SyncProgressDialog({ phase, onDismiss }: SyncProgressDialogProps) {
  // Escape dismisses (calls onDismiss, which is safe to call mid-sync — it
  // only clears toast state, not the phase).
  useEffect(() => {
    if (!phase) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onDismiss();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [phase, onDismiss]);

  if (!phase) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Ring sync in progress"
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/60"
    >
      <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-2xl p-8 max-w-sm w-[90%] text-center">
        <div className="animate-spin rounded-full h-12 w-12 border-4 border-gray-200 dark:border-gray-600 border-t-blue-600 mx-auto mb-5" />
        <p className="text-lg font-semibold text-gray-900 dark:text-gray-100">{phase}</p>
        <p className="text-xs text-gray-500 dark:text-gray-400 mt-3">Keep this screen on</p>
      </div>
    </div>
  );
}

interface SyncToastProps {
  message: string;
  success?: boolean;
  onDismiss: () => void;
}

export function SyncToast({ message, success = false, onDismiss }: SyncToastProps) {
  // Auto-dismiss after 5 seconds.
  useEffect(() => {
    if (!message) return;
    const timer = setTimeout(onDismiss, 5000);
    return () => clearTimeout(timer);
  }, [message, onDismiss]);

  if (!message) return null;

  return (
    <div
      role="status"
      className={`fixed bottom-4 right-4 z-50 px-4 py-3 rounded-lg shadow-lg text-white text-sm cursor-pointer ${
        success ? "bg-emerald-600" : "bg-rose-600"
      }`}
      onClick={onDismiss}
    >
      {message}
    </div>
  );
}
