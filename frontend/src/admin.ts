/**
 * Admin dashboard API client.
 *
 * Wraps the /api/v1/admin/stats/* endpoints. All calls send cookies
 * (credentials: "include") because the backend gates these routes
 * behind require_admin — an unauthenticated call returns 403.
 *
 * Exports the four fetch helpers and the four response types used by
 * AdminPage.tsx.
 */

const API_BASE = "/api/v1/admin/stats";

// ---------------------------------------------------------------------------
// Types — shapes returned by the backend's admin endpoints.
// ---------------------------------------------------------------------------

export interface AdminSummary {
  total_users: number;
  total_sessions: number;
  total_messages: number;
  total_documents: number;
}

export interface TimeSeriesPoint {
  date: string;
  count: number;
}

export interface AdminTimeSeries {
  days: number;
  signups: TimeSeriesPoint[];
  logins: TimeSeriesPoint[];
  logouts: TimeSeriesPoint[];
  sessions: TimeSeriesPoint[];
}

export interface RagMetricsCounts {
  faithfulness: number;
  context_precision: number;
  latency: number;
  composite: number;
  verification: number;
}

export interface RagMetrics {
  sample_size: number;
  avg_faithfulness: number | null;
  avg_context_precision: number | null;
  avg_latency_ms: number | null;
  avg_composite: number | null;
  abstention_rate: number | null;
  verification_pass_rate: number | null;
  counts: RagMetricsCounts;
}

export interface RecentQuery {
  message_id: number;
  session_id: string;
  user_id: string;
  created_at: number;
  question_preview: string;
  faithfulness: number | null;
  context_precision: number | null;
  composite: number | null;
  abstained: boolean;
  latency_ms: number | null;
}

export interface RecentResponse {
  queries: RecentQuery[];
}

// ---------------------------------------------------------------------------
// Fetch helper
// ---------------------------------------------------------------------------

async function getJson<T>(path: string): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
  });
  if (!resp.ok) {
    let detail = `Request failed (${resp.status})`;
    try {
      const body = await resp.json();
      if (body && typeof body.detail === "string") detail = body.detail;
    } catch {
      /* keep the default message */
    }
    throw new Error(detail);
  }
  return (await resp.json()) as T;
}

// ---------------------------------------------------------------------------
// Endpoints
// ---------------------------------------------------------------------------

export function fetchSummary(days: number): Promise<AdminSummary> {
  return getJson<AdminSummary>(`/summary?days=${days}`);
}

export function fetchTimeSeries(days: number): Promise<AdminTimeSeries> {
  return getJson<AdminTimeSeries>(`/timeseries?days=${days}`);
}

export function fetchRagMetrics(days: number): Promise<RagMetrics> {
  return getJson<RagMetrics>(`/rag?days=${days}`);
}

export function fetchRecent(limit: number): Promise<RecentResponse> {
  return getJson<RecentResponse>(`/recent?limit=${limit}`);
}