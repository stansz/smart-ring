import { useState } from "react";
import {
  useRingStatus, useAdminHealth, useAdminSyncLog, useClockAlert,
  useRawHeartRate, useRawSteps,
} from "../api/hooks";
import type { AdminSyncLogRow } from "../api/types";

const PER_PAGE = 8;

function SyncLogTable({ rows }: { rows: AdminSyncLogRow[] | undefined }) {
  const [page, setPage] = useState(1);
  const safe = rows || [];
  const totalPages = Math.max(1, Math.ceil(safe.length / PER_PAGE));
  const paged = safe.slice((page - 1) * PER_PAGE, page * PER_PAGE);

  const statusBadge = (status: string) => {
    const cls = status === "completed" || status === "ok"
      ? "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300"
      : status === "running"
        ? "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-300"
        : "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-300";
    return <span className={`text-xs px-2 py-0.5 rounded ${cls}`}>{status}</span>;
  };

  const fmtTime = (ts: string | null) =>
    ts ? new Date(ts).toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "—";

  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 border border-gray-100 dark:border-gray-700 mb-6">
      <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-4">Sync Log</h2>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-gray-500 dark:text-gray-400 border-b border-gray-200 dark:border-gray-700">
              <th className="pb-2 pr-4">Started</th>
              <th className="pb-2 pr-4">Completed</th>
              <th className="pb-2 pr-4">Records</th>
              <th className="pb-2 pr-4">Battery</th>
              <th className="pb-2 pr-4">Time Sync</th>
              <th className="pb-2 pr-4">Status</th>
              <th className="pb-2 pr-4">Error</th>
            </tr>
          </thead>
          <tbody>
            {paged.map((s) => (
              <tr key={s.id} className="border-b border-gray-100 dark:border-gray-700 text-gray-700 dark:text-gray-300">
                <td className="py-2 pr-4 whitespace-nowrap text-xs">{fmtTime(s.started_at)}</td>
                <td className="py-2 pr-4 whitespace-nowrap text-xs">{fmtTime(s.completed_at)}</td>
                <td className="py-2 pr-4">{s.records_synced ?? 0}</td>
                <td className="py-2 pr-4">{s.battery_pct != null ? `${s.battery_pct}%` : "—"}</td>
                <td className="py-2 pr-4">
                  <span className={s.clock_drift_ms === 1 ? "text-green-600 font-semibold" : s.clock_drift_ms === 0 ? "text-red-600 font-semibold" : "text-gray-400"}>
                    {s.clock_drift_ms === 1 ? "OK" : s.clock_drift_ms === 0 ? "No ack" : "—"}
                  </span>
                </td>
                <td className="py-2 pr-4">{statusBadge(s.status)}</td>
                <td className="py-2 pr-4 text-red-600 dark:text-red-400 text-xs">{s.error || ""}</td>
              </tr>
            ))}
            {safe.length === 0 && (
              <tr><td colSpan={7} className="py-6 text-center text-gray-500 dark:text-gray-400">No syncs yet. Ring hasn't been paired.</td></tr>
            )}
          </tbody>
        </table>
      </div>
      {safe.length > PER_PAGE && (
        <div className="flex items-center justify-between mt-4">
          <span className="text-sm text-gray-500 dark:text-gray-400">
            {(page - 1) * PER_PAGE + 1}–{Math.min(page * PER_PAGE, safe.length)} of {safe.length}
          </span>
          <div className="flex items-center gap-1">
            <button onClick={() => setPage(1)} disabled={page === 1} className="px-2 py-1 text-sm rounded border border-gray-200 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-40 text-gray-700 dark:text-gray-300">«</button>
            <button onClick={() => setPage((p) => p - 1)} disabled={page === 1} className="px-2 py-1 text-sm rounded border border-gray-200 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-40 text-gray-700 dark:text-gray-300">‹</button>
            <span className="px-3 py-1 text-sm rounded border border-blue-500 bg-blue-500 text-white font-semibold">{page}</span>
            <button onClick={() => setPage((p) => p + 1)} disabled={page === totalPages} className="px-2 py-1 text-sm rounded border border-gray-200 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-40 text-gray-700 dark:text-gray-300">›</button>
            <button onClick={() => setPage(totalPages)} disabled={page === totalPages} className="px-2 py-1 text-sm rounded border border-gray-200 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-40 text-gray-700 dark:text-gray-300">»</button>
          </div>
        </div>
      )}
    </div>
  );
}

export function AdminTab() {
  const { data: ring } = useRingStatus();
  const { data: health } = useAdminHealth();
  const { data: syncLog } = useAdminSyncLog(500);
  const { data: clock } = useClockAlert();
  const { data: rawHr } = useRawHeartRate(720, 2000);
  const { data: rawSteps } = useRawSteps(720, 2000);

  return (
    <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      {/* Ring status cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-5 border border-gray-100 dark:border-gray-700">
          <p className="text-sm font-medium text-gray-500 dark:text-gray-400">Battery</p>
          <p className="text-3xl font-bold text-gray-900 dark:text-gray-100 mt-1">
            {ring?.ring?.battery_pct != null ? <>{ring.ring.battery_pct}<span className="text-base text-gray-500 dark:text-gray-400">%</span></> : "—"}
          </p>
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
            {ring?.ring?.ts ? `As of ${new Date(ring.ring.ts).toLocaleString()}` : "No data yet — ring not synced"}
          </p>
        </div>
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-5 border border-gray-100 dark:border-gray-700">
          <p className="text-sm font-medium text-gray-500 dark:text-gray-400">Firmware</p>
          <p className="text-2xl font-bold text-gray-900 dark:text-gray-100 mt-1">{ring?.ring?.firmware_version || "—"}</p>
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">From device info read</p>
        </div>
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-5 border border-gray-100 dark:border-gray-700">
          <p className="text-sm font-medium text-gray-500 dark:text-gray-400">Last Sync</p>
          <p className="text-2xl font-bold text-gray-900 dark:text-gray-100 mt-1">
            {ring?.last_sync?.completed_at ? new Date(ring.last_sync.completed_at).toLocaleString() : "Never"}
          </p>
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
            {ring?.last_sync?.records_synced != null ? `${ring.last_sync.records_synced} records` : ""}
          </p>
        </div>
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-5 border border-gray-100 dark:border-gray-700">
          <p className="text-sm font-medium text-gray-500 dark:text-gray-400">DB Status</p>
          <p className={`text-2xl font-bold mt-1 ${health?.db === "connected" ? "text-green-600" : "text-red-600"}`}>
            {health?.db === "connected" ? "OK" : "DOWN"}
          </p>
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">{health?.container_host ? `host: ${health.container_host}` : ""}</p>
        </div>
      </div>

      {/* System Health */}
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 border border-gray-100 dark:border-gray-700 mb-6">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-4">System Health</h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
          <div><p className="text-gray-500 dark:text-gray-400">Database</p><p className="font-semibold text-green-600">{health?.db || "—"}</p></div>
          <div><p className="text-gray-500 dark:text-gray-400">Ring status rows</p><p className="font-semibold">{health?.ring_status_rows ?? "—"}</p></div>
          <div><p className="text-gray-500 dark:text-gray-400">Sync log rows</p><p className="font-semibold">{health?.sync_log_rows ?? "—"}</p></div>
          <div><p className="text-gray-500 dark:text-gray-400">Container</p><p className="font-semibold text-sm">{health?.container_host ?? "—"}</p></div>
        </div>
      </div>

      {/* Clock alert */}
      {clock && (clock.future_rows > 0) && (
        <div className="bg-amber-50 dark:bg-amber-900/20 rounded-lg shadow p-4 border border-amber-200 dark:border-amber-800 mb-6">
          <p className="text-sm text-amber-800 dark:text-amber-300">
            ⚠️ {clock.future_rows} future record(s) detected ({clock.future_hr} HR). Ring clock may be ahead.
          </p>
        </div>
      )}

      {/* Sync Log */}
      <SyncLogTable rows={syncLog} />

      {/* Raw Data Tables: HR Log + Steps Log */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-6 mb-8">
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 border border-gray-100 dark:border-gray-700">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-4">
            Heart Rate Log
            <span className="text-sm font-normal text-gray-500 dark:text-gray-400 ml-2">{rawHr?.length || 0} records</span>
          </h2>
          <div className="overflow-y-auto" style={{ maxHeight: 300 }}>
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-white dark:bg-gray-800">
                <tr className="text-left text-gray-500 dark:text-gray-400 border-b border-gray-200 dark:border-gray-700">
                  <th className="pb-2 pr-4">Time (local)</th>
                  <th className="pb-2 pr-4">BPM</th>
                </tr>
              </thead>
              <tbody className="text-gray-700 dark:text-gray-300">
                {rawHr?.slice(0, 200).map((r, i) => (
                  <tr key={i} className="border-b border-gray-100 dark:border-gray-700">
                    <td className="py-1.5 text-xs">{new Date(r.ts).toLocaleString()}</td>
                    <td className="py-1.5 font-mono">{r.bpm}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 border border-gray-100 dark:border-gray-700">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-4">
            Steps Log
            <span className="text-sm font-normal text-gray-500 dark:text-gray-400 ml-2">{rawSteps?.length || 0} records</span>
          </h2>
          <div className="overflow-y-auto" style={{ maxHeight: 300 }}>
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-white dark:bg-gray-800">
                <tr className="text-left text-gray-500 dark:text-gray-400 border-b border-gray-200 dark:border-gray-700">
                  <th className="pb-2 pr-4">Time (local)</th>
                  <th className="pb-2 pr-4">Steps</th>
                  <th className="pb-2 pr-4">Cal</th>
                  <th className="pb-2 pr-4">Dist</th>
                </tr>
              </thead>
              <tbody className="text-gray-700 dark:text-gray-300">
                {rawSteps?.slice(0, 200).map((r, i) => (
                  <tr key={i} className="border-b border-gray-100 dark:border-gray-700">
                    <td className="py-1.5 text-xs">{new Date(r.ts).toLocaleString()}</td>
                    <td className="py-1.5 font-mono">{r.steps}</td>
                    <td className="py-1.5 font-mono">{r.calories ?? "—"}</td>
                    <td className="py-1.5 font-mono">{r.distance ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </main>
  );
}
