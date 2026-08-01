import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { get, post } from "./client";
import type {
  HealthResponse,
  RecoveryRow,
  ReadinessRow,
  CurrentStatusRow,
  SleepQualityRow,
  HrvTrendRow,
  CircadianHrRow,
  StressClassificationRow,
  RestingHrRow,
  DailyActivityRow,
  HeartRateZonesRow,
  StrainTrendRow,
  DataQualityRow,
  RawHeartRateRow,
  RawStepsRow,
  RawStressRow,
  RawSleepRow,
  RawSpo2Row,
  RawHrvRow,
  RawTemperatureRow,
  GoalsResponse,
  UserGoals,
  SyncLogRow,
  RingStatusResponse,
  AdminHealthResponse,
  AdminSyncLogRow,
  ClockAlertResponse,
  SyncRequestRow,
  SyncProgressResponse,
  ActivityRow,
  ActivityDetail,
  TrackpointRow,
  ActivityHrRow,
  ActivityLapRow,
  GarminUploadResponse,
} from "./types";

// ─── Health ─────────────────────────────────────────────────────────────────
export function useHealth() {
  return useQuery({ queryKey: ["health"], queryFn: () => get<HealthResponse>("/health") });
}

// ─── Readiness / Recovery / Current Status ──────────────────────────────────
export function useRecovery(days = 30) {
  return useQuery({
    queryKey: ["recovery", days],
    queryFn: () => get<RecoveryRow[]>(`/api/recovery?days=${days}`),
  });
}

export function useReadiness(days = 7) {
  return useQuery({
    queryKey: ["readiness", days],
    queryFn: () => get<ReadinessRow[]>(`/api/readiness?days=${days}`),
  });
}

export function useCurrentStatus(hours = 168) {
  return useQuery({
    queryKey: ["currentStatus", hours],
    queryFn: () => get<CurrentStatusRow[]>(`/api/current-status?hours=${hours}`),
  });
}

// ─── Sleep ──────────────────────────────────────────────────────────────────
export function useSleep(days = 30) {
  return useQuery({
    queryKey: ["sleep", days],
    queryFn: () => get<SleepQualityRow[]>(`/api/sleep?days=${days}`),
  });
}

// ─── HRV / Stress / Activity ────────────────────────────────────────────────
export function useHrvTrends(days = 60) {
  return useQuery({
    queryKey: ["hrvTrends", days],
    queryFn: () => get<HrvTrendRow[]>(`/api/hrv-trends?days=${days}`),
  });
}

export function useCircadianHr() {
  return useQuery({
    queryKey: ["circadianHr"],
    queryFn: async () => {
      const data = await get<(CircadianHrRow & { _range?: { min_day: string; max_day: string } })[]>("/api/circadian-hr");
      // Separate _range from data rows
      const range = data.find((d) => "_range" in d)?._range;
      const rows = data.filter((d) => !("_range" in d)) as CircadianHrRow[];
      return { rows, range };
    },
  });
}

export function useStress(days = 30) {
  return useQuery({
    queryKey: ["stress", days],
    queryFn: () => get<StressClassificationRow[]>(`/api/stress?days=${days}`),
  });
}

export function useRestingHr(days = 30) {
  return useQuery({
    queryKey: ["restingHr", days],
    queryFn: () => get<RestingHrRow[]>(`/api/resting-hr?days=${days}`),
  });
}

export function useDailyActivity(days = 14) {
  return useQuery({
    queryKey: ["dailyActivity", days],
    queryFn: () => get<DailyActivityRow[]>(`/api/daily-activity?days=${days}`),
  });
}

export function useHeartRateZones(days = 14) {
  return useQuery({
    queryKey: ["heartRateZones", days],
    queryFn: () => get<HeartRateZonesRow[]>(`/api/heart-rate-zones?days=${days}`),
  });
}

export function useStrainTrend(days = 14) {
  return useQuery({
    queryKey: ["strainTrend", days],
    queryFn: () => get<StrainTrendRow[]>(`/api/strain-trend?days=${days}`),
  });
}

// ─── Data Quality ───────────────────────────────────────────────────────────
export function useDataQuality(days = 7, source?: string) {
  return useQuery({
    queryKey: ["dataQuality", days, source ?? "all"],
    queryFn: () => {
      const params = new URLSearchParams({ days: String(days) });
      if (source) params.set("source", source);
      return get<DataQualityRow[]>(`/api/data-quality?${params.toString()}`);
    },
  });
}

// ─── Raw data ───────────────────────────────────────────────────────────────
export function useRawHeartRate(hours = 48, limit = 1000) {
  return useQuery({
    queryKey: ["rawHeartRate", hours, limit],
    queryFn: () => get<RawHeartRateRow[]>(`/api/raw/heart-rate?hours=${hours}&limit=${limit}`),
  });
}

export function useRawSteps(hours = 168, limit = 1000) {
  return useQuery({
    queryKey: ["rawSteps", hours, limit],
    queryFn: () => get<RawStepsRow[]>(`/api/raw/steps?hours=${hours}&limit=${limit}`),
  });
}

export function useRawStress(hours = 168, limit = 500) {
  return useQuery({
    queryKey: ["rawStress", hours, limit],
    queryFn: () => get<RawStressRow[]>(`/api/raw/stress?hours=${hours}&limit=${limit}`),
  });
}

export function useRawSleep(hours = 168, limit = 200) {
  return useQuery({
    queryKey: ["rawSleep", hours, limit],
    queryFn: () => get<RawSleepRow[]>(`/api/raw/sleep?hours=${hours}&limit=${limit}`),
  });
}

export function useRawSpo2(hours = 168, limit = 200) {
  return useQuery({
    queryKey: ["rawSpo2", hours, limit],
    queryFn: () => get<RawSpo2Row[]>(`/api/raw/spo2?hours=${hours}&limit=${limit}`),
  });
}

export function useRawHrv(hours = 168, limit = 500) {
  return useQuery({
    queryKey: ["rawHrv", hours, limit],
    queryFn: () => get<RawHrvRow[]>(`/api/raw/hrv?hours=${hours}&limit=${limit}`),
  });
}

export function useRawTemperature(hours = 48, limit = 1000) {
  return useQuery({
    queryKey: ["rawTemperature", hours, limit],
    queryFn: () => get<RawTemperatureRow[]>(`/api/raw/temperature?hours=${hours}&limit=${limit}`),
  });
}

// ─── Goals ──────────────────────────────────────────────────────────────────
export function useGoals() {
  return useQuery({
    queryKey: ["goals"],
    queryFn: () => get<GoalsResponse>("/api/goals"),
  });
}

// User-set goals (the user's own targets, NOT the firmware ring_goals).
export function useUserGoals() {
  return useQuery({
    queryKey: ["userGoals"],
    queryFn: () => get<UserGoals>("/api/user-goals"),
    staleTime: 60_000,  // rarely changes — 1 min stale time
  });
}

export function useUpdateUserGoal() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (update: Partial<UserGoals>) =>
      post<{ updated: number }>("/api/user-goals", update),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["userGoals"] });
    },
  });
}

// ─── Sync log ───────────────────────────────────────────────────────────────
export function useSyncLog(limit = 50) {
  return useQuery({
    queryKey: ["syncLog", limit],
    queryFn: () => get<SyncLogRow[]>(`/api/sync-log?limit=${limit}`),
  });
}

// ─── Admin ──────────────────────────────────────────────────────────────────
export function useRingStatus() {
  return useQuery({
    queryKey: ["ringStatus"],
    queryFn: () => get<RingStatusResponse>("/api/admin/ring-status"),
  });
}

export function useAdminHealth() {
  return useQuery({
    queryKey: ["adminHealth"],
    queryFn: () => get<AdminHealthResponse>("/api/admin/health"),
  });
}

export function useAdminSyncLog(limit = 50) {
  return useQuery({
    queryKey: ["adminSyncLog", limit],
    queryFn: () => get<AdminSyncLogRow[]>(`/api/admin/sync-log?limit=${limit}`),
  });
}

export function useClockAlert() {
  return useQuery({
    queryKey: ["clockAlert"],
    queryFn: () => get<ClockAlertResponse>("/api/admin/clock-alert"),
  });
}

export function useSyncRequests(limit = 20) {
  return useQuery({
    queryKey: ["syncRequests", limit],
    queryFn: () => get<SyncRequestRow[]>(`/api/admin/sync-requests?limit=${limit}`),
  });
}

export function useSyncProgress() {
  return useQuery({
    queryKey: ["syncProgress"],
    queryFn: () => get<SyncProgressResponse>("/api/admin/sync-progress"),
  });
}

// ─── Garmin Activities ─────────────────────────────────────────────────────
export function useActivities(days = 365, sport?: string, limit = 30) {
  const params = new URLSearchParams({
    days: String(days),
    limit: String(limit),
  });
  if (sport) params.set("sport", sport);
  return useQuery({
    queryKey: ["activities", days, sport ?? "all", limit],
    queryFn: () => get<ActivityRow[]>(`/api/activities?${params.toString()}`),
  });
}

export function useActivityDetail(id: number | null) {
  return useQuery({
    queryKey: ["activity", id],
    queryFn: () => get<ActivityDetail>(`/api/activities/${id}`),
    enabled: id !== null,
  });
}

export function useActivityTrackpoints(id: number | null, maxPoints = 5000) {
  return useQuery({
    queryKey: ["activityTrackpoints", id, maxPoints],
    queryFn: () =>
      get<TrackpointRow[]>(
        `/api/activities/${id}/trackpoints?max_points=${maxPoints}`,
      ),
    enabled: id !== null,
  });
}

export function useActivityHr(id: number | null, maxPoints = 5000) {
  return useQuery({
    queryKey: ["activityHr", id, maxPoints],
    queryFn: () =>
      get<ActivityHrRow[]>(`/api/activities/${id}/hr?max_points=${maxPoints}`),
    enabled: id !== null,
  });
}

export function useActivityLaps(id: number | null) {
  return useQuery({
    queryKey: ["activityLaps", id],
    queryFn: () => get<ActivityLapRow[]>(`/api/activities/${id}/laps`),
    enabled: id !== null,
  });
}

export function useGarminUpload() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (data: { files: File[]; paths: string[] }) => {
      const formData = new FormData();
      for (const file of data.files) {
        formData.append("files", file);
      }
      formData.append("paths", JSON.stringify(data.paths));
      const res = await fetch("/api/admin/garmin-upload", {
        method: "POST",
        body: formData,
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(`${res.status} ${res.statusText}: ${text}`);
      }
      return res.json() as Promise<GarminUploadResponse>;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["activities"] });
      queryClient.invalidateQueries({ queryKey: ["adminHealth"] });
    },
  });
}
