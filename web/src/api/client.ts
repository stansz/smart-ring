const BASE = ""; // relative — all API routes are same-origin

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    throw new Error(`${res.status} ${res.statusText} from ${path}`);
  }
  return res.json();
}

export function get<T>(path: string): Promise<T> {
  return request<T>(path);
}

export function post<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

// ─── Admin actions ──────────────────────────────────────────────────────────
import type { CancelSyncResponse, QueueSyncResponse } from "./types";

export function queueSync(by = "admin-ui"): Promise<QueueSyncResponse> {
  return post<QueueSyncResponse>("/api/admin/sync", { requested_by: by });
}

export function cancelSync(): Promise<CancelSyncResponse> {
  return post<CancelSyncResponse>("/api/admin/cancel-sync", {});
}
