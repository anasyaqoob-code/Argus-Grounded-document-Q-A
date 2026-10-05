/**
 * Admin dashboard — product analytics + RAG system evaluation.
 *
 * Route: /admin (behind RequireAuth, plus an in-page isAdmin check).
 *
 * Four sections:
 *   1. Summary cards      — totals scoped to the selected time range
 *   2. Time series        — signups, logins, sessions per day (Recharts)
 *   3. RAG health         — flat tile row, matching the summary cards
 *   4. Recent queries     — a table of the last N assistant turns
 *
 * All data comes from /api/v1/admin/stats/*. The backend enforces
 * admin-only access; this page additionally renders a 403 view for
 * logged-in non-admins so the UI matches the API contract.
 */

import React from "react";
import { Link } from "react-router-dom";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { useAuth } from "./AuthContext";
import {
  AdminSummary,
  AdminTimeSeries,
  RagMetrics,
  RecentQuery,
  fetchRagMetrics,
  fetchRecent,
  fetchSummary,
  fetchTimeSeries,
} from "./admin";

// Range options. 0 = lifetime (no cutoff). The backend accepts days=0
// and returns all-time aggregates.
const RANGES = [7, 30, 90, 0] as const;
type RangeDays = (typeof RANGES)[number];

export function AdminPage() {
  const { isAdmin, loading: authLoading } = useAuth();

  const [days, setDays] = React.useState<RangeDays>(30);

  const [summary, setSummary] = React.useState<AdminSummary | null>(null);
  const [series, setSeries] = React.useState<AdminTimeSeries | null>(null);
  const [rag, setRag] = React.useState<RagMetrics | null>(null);
  const [recent, setRecent] = React.useState<RecentQuery[]>([]);

  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  // Allow window scroll while this page is mounted. The app shell sets
  // html, body { overflow: hidden } so only .messages scrolls — but the
  // admin page is a long document and needs the whole window to scroll,
  // same as the landing page.
  React.useEffect(() => {
    document.body.classList.add("lp-scroll");
    return () => {
      document.body.classList.remove("lp-scroll");
    };
  }, []);

  React.useEffect(() => {
    if (authLoading) return;
    if (!isAdmin) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const [s, t, r, rec] = await Promise.all([
          fetchSummary(days),
          fetchTimeSeries(days),
          fetchRagMetrics(days),
          fetchRecent(50),
        ]);
        if (cancelled) return;
        setSummary(s);
        setSeries(t);
        setRag(r);
        setRecent(rec.queries);
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : "Failed to load");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [days, isAdmin, authLoading]);

  if (authLoading) {
    return <AdminShell><div className="ad-muted">Loading…</div></AdminShell>;
  }

  if (!isAdmin) {
    return (
      <AdminShell>
        <div className="ad-forbidden">
          <h1>Not authorized</h1>
          <p>This page is restricted to administrators.</p>
          <Link to="/app" className="ad-back">← Back to app</Link>
        </div>
      </AdminShell>
    );
  }

  const rangeLabel = days === 0 ? "Lifetime" : `Last ${days} days`;

  return (
    <AdminShell>
      <header className="ad-header">
        <div>
          <h1 className="ad-title">Admin</h1>
          <p className="ad-sub">
            Product analytics and RAG system evaluation.
          </p>
        </div>
        <div className="ad-range">
          {RANGES.map((r) => (
            <button
              key={r}
              className={`ad-range-btn${r === days ? " active" : ""}`}
              onClick={() => setDays(r)}
            >
              {r === 0 ? "All" : `${r}d`}
            </button>
          ))}
        </div>
      </header>

      {error && <div className="ad-error">{error}</div>}

      {/* Row 1 — summary cards (scoped to the selected range) */}
      <section className="ad-section">
        <div className="ad-section-header">
          <h2 className="ad-section-title">
            Summary
            <span className="ad-section-range"> · {rangeLabel}</span>
          </h2>
        </div>
        <div className="ad-cards">
          <StatCard label="Users" value={summary?.total_users} />
          <StatCard label="Sessions" value={summary?.total_sessions} />
          <StatCard label="Messages" value={summary?.total_messages} />
          <StatCard label="Documents" value={summary?.total_documents} />
        </div>
      </section>

      {/* Row 2 — auth time series */}
      <section className="ad-section">
        <h2 className="ad-section-title">Signups &amp; logins</h2>
        <div className="ad-chart">
          <ResponsiveContainer width="100%" height={280}>
            <LineChart data={mergeSeries(series)}>
              <CartesianGrid strokeDasharray="3 3" stroke="#2a2a3a" />
              <XAxis dataKey="date" stroke="#888" fontSize={12} />
              <YAxis stroke="#888" fontSize={12} allowDecimals={false} />
              <Tooltip
                contentStyle={{
                  background: "#1a1a2a",
                  border: "1px solid #333",
                  borderRadius: 8,
                }}
              />
              <Legend />
              <Line type="monotone" dataKey="signups" stroke="#a78bfa" strokeWidth={2} dot={false} />
              <Line type="monotone" dataKey="logins" stroke="#22d3ee" strokeWidth={2} dot={false} />
              <Line type="monotone" dataKey="sessions" stroke="#f472b6" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </section>

      {/* Row 3 — RAG health (flat tile row, matches the summary cards) */}
      <section className="ad-section">
        <h2 className="ad-section-title">
          RAG health
          <span className="ad-section-range"> · {rangeLabel}</span>
        </h2>
        <div className="ad-rag">
          <Metric
            label="Faithfulness"
            value={fmtPct(rag?.avg_faithfulness)}
            hint={rag ? `${rag.counts.faithfulness} samples` : undefined}
          />
          <Metric
            label="Context precision"
            value={fmtPct(rag?.avg_context_precision)}
            hint={rag ? `${rag.counts.context_precision} samples` : undefined}
          />
          <Metric
            label="Verification pass"
            value={fmtPct(rag?.verification_pass_rate)}
            hint={rag ? `${rag.counts.verification} samples` : undefined}
          />
          <Metric
            label="Abstention rate"
            value={fmtPct(rag?.abstention_rate)}
            hint={rag ? `${rag.sample_size} queries` : undefined}
          />
          <Metric
            label="Avg composite"
            value={fmtPct(rag?.avg_composite)}
            hint={rag ? `${rag.counts.composite} samples` : undefined}
          />
          <Metric
            label="Avg latency"
            value={fmtMs(rag?.avg_latency_ms)}
            hint={rag ? `${rag.counts.latency} samples` : undefined}
          />
        </div>
        {rag && rag.sample_size === 0 && (
          <p className="ad-muted ad-empty">
            No evaluation data yet for this range. Send a query through the
            app and this panel will populate.
          </p>
        )}
      </section>

      {/* Row 4 — recent queries */}
      <section className="ad-section">
        <h2 className="ad-section-title">Recent queries</h2>
        <div className="ad-table-wrap">
          <table className="ad-table">
            <thead>
              <tr>
                <th>When</th>
                <th>Question</th>
                <th>Faithfulness</th>
                <th>Precision</th>
                <th>Composite</th>
                <th>Latency</th>
                <th>Abstained</th>
              </tr>
            </thead>
            <tbody>
              {recent.length === 0 && (
                <tr>
                  <td colSpan={7} className="ad-muted">
                    No queries recorded yet.
                  </td>
                </tr>
              )}
              {recent.map((q) => (
                <tr key={q.message_id}>
                  <td className="ad-cell-mono">{fmtDate(q.created_at)}</td>
                  <td className="ad-cell-question">{q.question_preview || "—"}</td>
                  <td>{fmtPct(q.faithfulness)}</td>
                  <td>{fmtPct(q.context_precision)}</td>
                  <td className="ad-cell-strong">{fmtPct(q.composite)}</td>
                  <td className="ad-cell-mono">{fmtMs(q.latency_ms)}</td>
                  <td>{q.abstained ? "yes" : "no"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </AdminShell>
  );
}

// ---------------------------------------------------------------------------
// Layout shell
// ---------------------------------------------------------------------------
function AdminShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="ad">
      <nav className="ad-nav">
        <Link to="/" className="ad-nav-brand">Argus</Link>
        <span className="ad-nav-sep">/</span>
        <span className="ad-nav-current">Admin</span>
        <Link to="/app" className="ad-nav-back">Back to app →</Link>
      </nav>
      <main className="ad-main">{children}</main>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Small presentational pieces
// ---------------------------------------------------------------------------
function StatCard({ label, value }: { label: string; value?: number }) {
  return (
    <div className="ad-card">
      <div className="ad-card-value">{value ?? "—"}</div>
      <div className="ad-card-label">{label}</div>
    </div>
  );
}

function Metric({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="ad-metric">
      <div className="ad-metric-value">{value}</div>
      <div className="ad-metric-label">{label}</div>
      {hint && <div className="ad-metric-hint">{hint}</div>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------
function fmtPct(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return `${Math.round(v * 100)}%`;
}

function fmtMs(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  if (v < 1000) return `${Math.round(v)} ms`;
  return `${(v / 1000).toFixed(2)} s`;
}

function fmtDate(ts: number): string {
  const d = new Date(ts * 1000);
  const now = new Date();
  const sameDay = d.toDateString() === now.toDateString();
  if (sameDay) {
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }
  return d.toLocaleDateString([], { month: "short", day: "numeric" });
}

/**
 * Merge the four per-day series into one array keyed by date, so the
 * Recharts LineChart gets a single `data` prop. Days missing from any
 * series default to 0 — that's what we want in a chart.
 */
function mergeSeries(s: AdminTimeSeries | null) {
  if (!s) return [];
  const byDate: Record<string, { date: string; signups: number; logins: number; sessions: number }> = {};
  const touch = (d: string) => {
    if (!byDate[d]) byDate[d] = { date: d, signups: 0, logins: 0, sessions: 0 };
    return byDate[d];
  };
  const signups = Array.isArray(s.signups) ? s.signups : [];
  const logins = Array.isArray(s.logins) ? s.logins : [];
  const sessions = Array.isArray(s.sessions) ? s.sessions : [];
  for (const p of signups) touch(p.date).signups = p.count;
  for (const p of logins) touch(p.date).logins = p.count;
  for (const p of sessions) touch(p.date).sessions = p.count;
  return Object.values(byDate).sort((a, b) => a.date.localeCompare(b.date));
}