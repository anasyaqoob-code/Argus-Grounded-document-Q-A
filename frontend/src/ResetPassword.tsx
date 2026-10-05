/**
 * Reset-password page.
 *
 * Split layout: form on the left (glass card, subtle 3D tilt), live
 * strength meter on the right. The strength panel updates on every
 * keystroke, so the user gets feedback before hitting submit instead
 * of after.
 *
 * Reads ?token=... from the URL. On success, shows a success state
 * briefly, then redirects to /login.
 */

import React, { useMemo, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { ArgusLogo } from "./ArgusLogo";

const API_BASE = "/api/v1";

// ---------------------------------------------------------------------------
// Strength scoring.
//
// Simple heuristic: length >= 8, at least one letter, at least one
// digit, at least one symbol. Each check contributes 1 point out of 4.
// The meter reads 0..3 as Weak, 4 as Strong. No complexity beyond
// what a demo would expect — the real bar is set by the backend's
// min-length check and bcrypt itself.
// ---------------------------------------------------------------------------
interface StrengthCheck {
  id: string;
  label: string;
  pass: boolean;
}

function scorePassword(pw: string): { checks: StrengthCheck[]; score: number } {
  const checks: StrengthCheck[] = [
    { id: "len", label: "At least 8 characters", pass: pw.length >= 8 },
    { id: "alpha", label: "Contains a letter", pass: /[A-Za-z]/.test(pw) },
    { id: "num", label: "Contains a number", pass: /\d/.test(pw) },
    { id: "sym", label: "Contains a symbol", pass: /[^A-Za-z0-9]/.test(pw) },
  ];
  const score = checks.filter((c) => c.pass).length;
  return { checks, score };
}

function strengthLabel(score: number, pw: string): string {
  if (!pw) return "—";
  if (score <= 1) return "Weak";
  if (score === 2) return "Fair";
  if (score === 3) return "Good";
  return "Strong";
}

export function ResetPassword() {
  const [params] = useSearchParams();
  const token = params.get("token") || "";
  const navigate = useNavigate();

  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const { checks, score } = useMemo(() => scorePassword(password), [password]);
  const match = password.length > 0 && password === confirm;

  // Left card tilt. Right panel is static.
  const cardRef = useRef<HTMLDivElement | null>(null);
  const [tilt, setTilt] = useState({ x: 0, y: 0 });

  function onMove(e: React.MouseEvent<HTMLDivElement>) {
    const el = cardRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const cx = rect.left + rect.width / 2;
    const cy = rect.top + rect.height / 2;
    const dx = (e.clientX - cx) / (rect.width / 2);
    const dy = (e.clientY - cy) / (rect.height / 2);
    setTilt({
      x: Math.max(-1, Math.min(1, -dy)) * 3,
      y: Math.max(-1, Math.min(1, dx)) * 3,
    });
  }

  function onLeave() {
    setTilt({ x: 0, y: 0 });
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    if (!token) {
      setError("This reset link is missing its token. Request a new one.");
      return;
    }
    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }
    if (password !== confirm) {
      setError("Passwords do not match.");
      return;
    }

    setSubmitting(true);
    try {
      const res = await fetch(`${API_BASE}/auth/reset-password`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ token, new_password: password }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.detail || "Reset failed. Request a new link.");
      }
      setDone(true);
      window.setTimeout(() => {
        navigate("/login?reset=1", { replace: true });
      }, 1400);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setSubmitting(false);
    }
  }

  return (
    <div className="rp-page">
      <div className="rp-bg" aria-hidden="true" />

      <Link to="/login" className="rp-back">
        <span aria-hidden="true">←</span> Back to sign in
      </Link>

      <div className="rp-stage">
        {/* ---------------- Left: the form ---------------- */}
        <div
          ref={cardRef}
          className="rp-card"
          onMouseMove={onMove}
          onMouseLeave={onLeave}
          style={{
            transform: `perspective(1400px) rotateX(${tilt.x}deg) rotateY(${tilt.y}deg)`,
          }}
        >
          <div className="rp-card-mark">
            <ArgusLogo size={36} idSuffix="rp-brand" />
            <div className="rp-card-brand-text">
              <span className="rp-card-brand-title">Argus</span>
            </div>
          </div>

          {done ? (
            <>
              <h1 className="rp-title">Password updated</h1>
              <p className="rp-sub">Redirecting you to sign in…</p>
              <div className="rp-success">
                <div className="rp-success-glyph" aria-hidden="true">✓</div>
                <p className="rp-success-text">
                  Your password has been reset. Use the new one the next
                  time you sign in.
                </p>
              </div>
            </>
          ) : (
            <>
              <h1 className="rp-title">New password</h1>
              <p className="rp-sub">Choose something strong.</p>

              <form onSubmit={onSubmit} className="rp-form">
                <label className="rp-field">
                  <span className="rp-label">New password</span>
                  <input
                    type="password"
                    autoComplete="new-password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="at least 8 characters"
                    disabled={submitting}
                    required
                    minLength={8}
                  />
                </label>

                <label className="rp-field">
                  <span className="rp-label">Confirm password</span>
                  <input
                    type="password"
                    autoComplete="new-password"
                    value={confirm}
                    onChange={(e) => setConfirm(e.target.value)}
                    placeholder="re-enter password"
                    disabled={submitting}
                    required
                  />
                  {confirm.length > 0 && !match && (
                    <span className="rp-hint rp-hint-bad">
                      Passwords don't match yet.
                    </span>
                  )}
                </label>

                {error && <div className="rp-error">{error}</div>}

                <button
                  type="submit"
                  className="rp-submit"
                  disabled={submitting}
                >
                  {submitting ? "Updating…" : "Update password"}
                </button>
              </form>

              {!token && (
                <p className="rp-footnote" style={{ marginTop: 14 }}>
                  Need a new link?{" "}
                  <Link to="/forgot-password" className="rp-link">
                    Request one
                  </Link>
                </p>
              )}
            </>
          )}
        </div>

        {/* ---------------- Right: strength meter ---------------- */}
        {!done && (
          <aside className="rp-meter" aria-hidden="true">
            <div className="rp-meter-head">
              <span className="rp-meter-label">Strength</span>
              <span
                className={
                  "rp-meter-value" +
                  (score >= 4
                    ? " strong"
                    : score === 3
                      ? " good"
                      : score === 2
                        ? " fair"
                        : score >= 1
                          ? " weak"
                          : "")
                }
              >
                {strengthLabel(score, password)}
              </span>
            </div>

            <div className="rp-meter-bars">
              {[0, 1, 2, 3].map((i) => (
                <div
                  key={i}
                  className={
                    "rp-meter-bar" + (i < score ? " filled" : "")
                  }
                  data-tier={i}
                />
              ))}
            </div>

            <ul className="rp-meter-checks">
              {checks.map((c) => (
                <li
                  key={c.id}
                  className={"rp-meter-check" + (c.pass ? " passed" : "")}
                >
                  <span className="rp-meter-check-dot" />
                  <span className="rp-meter-check-label">{c.label}</span>
                </li>
              ))}
            </ul>

            {password.length >= 8 && score < 3 && (
              <p className="rp-meter-hint">
                Adding numbers or symbols makes it stronger.
              </p>
            )}
            {score >= 4 && (
              <p className="rp-meter-hint rp-meter-hint-good">
                Looks good. You can update whenever you're ready.
              </p>
            )}
          </aside>
        )}
      </div>
    </div>
  );
}