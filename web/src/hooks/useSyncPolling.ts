import { useState, useEffect, useCallback, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { queueSync, cancelSync } from "../api/client";
import { useSyncProgress, useSyncRequests } from "../api/hooks";

export function useSyncPolling() {
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const { data: progress } = useSyncProgress();
  const { data: requests } = useSyncRequests(5);

  const active = requests?.some((r) => r.status === "pending" || r.status === "running");

  useEffect(() => {
    setBusy(!!active);
  }, [active]);

  const startSync = useCallback(async () => {
    try {
      setError(null);
      await queueSync();
      setBusy(true);
    } catch (e: any) {
      setError(e.message || "Sync queue failed");
    }
  }, []);

  const handleCancel = useCallback(async () => {
    try {
      await cancelSync();
      setBusy(false);
    } catch (e: any) {
      setError(e.message || "Cancel failed");
    }
  }, []);

  // Poll while busy
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  useEffect(() => {
    if (busy) {
      pollRef.current = setInterval(() => {
        queryClient.invalidateQueries({ queryKey: ["syncProgress"] });
        queryClient.invalidateQueries({ queryKey: ["syncRequests"] });
      }, 3000);
      return () => { if (pollRef.current) clearInterval(pollRef.current); };
    }
  }, [busy, queryClient]);

  // Auto-refresh on sync complete
  const wasBusy = useRef(busy);
  useEffect(() => {
    if (wasBusy.current && !busy) {
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      queryClient.invalidateQueries({ queryKey: ["readiness"] });
      queryClient.invalidateQueries({ queryKey: ["currentStatus"] });
      queryClient.invalidateQueries({ queryKey: ["dailyActivity"] });
      queryClient.invalidateQueries({ queryKey: ["circadianHr"] });
      queryClient.invalidateQueries({ queryKey: ["sleep"] });
    }
    wasBusy.current = busy;
  }, [busy, queryClient]);

  return { busy, error, dismissError: () => setError(null), startSync, handleCancel, progress } as const;
}
