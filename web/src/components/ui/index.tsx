import type { ReactNode } from "react";

export function Skeleton({ className = "" }: { className?: string }) {
  return (
    <div className={`animate-pulse bg-gray-200 dark:bg-gray-700 rounded ${className}`} />
  );
}

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <div className={`bg-white dark:bg-gray-800 rounded-lg shadow border border-gray-100 dark:border-gray-700 ${className}`}>
      {children}
    </div>
  );
}

export function EmptyState({ message = "No data yet" }: { message?: string }) {
  return (
    <div className="text-center py-12 text-gray-400 dark:text-gray-500">
      <p className="text-lg">{message}</p>
    </div>
  );
}
