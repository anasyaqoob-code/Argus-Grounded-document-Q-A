/**
 * Auth page — login and register in a single screen.
 *
 * Split layout: form on the left, a live agent-trace preview on the
 * right. The preview cycles through the four visible pipeline stages
 * AND rotates through a small set of sample Q&A pairs so the visitor
 * sees a different answer each cycle.
 *
 * The preview card responds to the cursor with a subtle mousemove tilt
 * — the same 3D behavior as the landing-page hero artifact, so the two
 * pages feel like the same product.
 *
 * On success, navigates to /app (or back to wherever the user was
 * trying to go, if RequireAuth stashed a `from` in location state).
 *
 * Also hosts the two entry points for alternate auth paths:
 *   - "Forgot password?" → /forgot-password (email-based reset)
 *   - "Continue with Google" → /api/v1/auth/google/start (OAuth)
 */

import React, { useEffect, useState } from "react";
import { useNavigate, useLocation, Link } from "react-router-dom";

import { useAuth } from "./AuthContext";
import { ArgusLogo } from "./ArgusLogo";

const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "";

type Mode = "login" | "register";

// ---------------------------------------------------------------------------
// Sample Q&A pairs shown in the preview card. Each cycle the preview
// rotates to the next one. The document is the same across all of them
// (audit_Q3.pdf) so the card stays visually consistent — but the
// question and answer change so a visitor who lingers sees variety.
// ---------------------------------------------------------------------------
const PREVIEW_QA = [
  {
    question: "What does the audit say about our Q3 spend?",
    answer: (
      <>
        The Q3 audit flags $412K in unapproved vendor spend, with the
        largest variance in cloud infrastructure — 38% over the
        pre-approved ceiling{" "}
        <span className="auth-preview-cite">[S1]</span>.
      </>
    ),
    source: "audit_Q3.pdf · p.4",
  },
  {
    question: "Which vendor had the largest variance?",
    answer: (
      <>
        Cloud infrastructure had the largest variance — 38% over its
        pre-approved ceiling, driven by unapproved scaling{" "}
        <span className="auth-preview-cite">[S2]</span>.
      </>
    ),
    source: "audit_Q3.pdf · p.6",
  },
  {
    question: "Did the audit pass or fail?",
    answer: (
      <>
        The audit passed overall, but with two material findings:
        unapproved vendor spend and a documentation gap in cloud
        procurement <span className="auth-preview-cite">[S3]</span>.
      </>
    ),
    source: "audit_Q3.pdf · p.1",
  },
] as const;

// ---------------------------------------------------------------------------
// Preview stage sequence — mirrors the real pipeline, condensed to four
// stages the visitor can read at a glance.
// ---------------------------------------------------------------------------
const PREVIEW_STAGES = [
  {
    state: "UNDERSTAND",
    running: "Resolving pronouns in your question…",
    done: "Rewrote into a standalone question",
  },
  {
    state: "SEARCH",
    running: "Querying the vector store…",
    done: "Retrieved 6 chunks from 2 documents",
  },
  {
    state: "EVALUATE",
    running: "Checking if the context is sufficient…",
    done: "Context sufficient — proceeding",
  },
  {
    state: "VERIFY",
    running: "Validating each citation against its source…",
    done: "Coverage 83% · passed",
  },
] as const;

const STAGE_RUNNING_MS = 900;
const LOOP_HOLD_MS = 2600;
const LOOP_START_DELAY_MS = 400;
const FULL_CYCLE_MS =
  LOOP_START_DELAY_MS +
  PREVIEW_STAGES.length * STAGE_RUNNING_MS +
  LOOP_HOLD_MS;

export function AuthPage() {
  const { login, register } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const isRegister = mode === "register";

  const redirectTo =
    (location.state as { from?: string } | null)?.from ?? "/app";

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    if (!email.trim() || !password) {
      setError("Email and password are required.");
      return;
    }
    if (isRegister && password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }
    if (isRegister && password !== confirm) {
      setError("Passwords do not match.");
      return;
    }

    setSubmitting(true);
    try {
      if (isRegister) {
        await register(email.trim(), password);
      } else {
        await login(email.trim(), password);
      }
      navigate(redirectTo, { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setSubmitting(false);
    }
  }

  function switchMode(next: Mode) {
    setMode(next);
    setError(null);
    setPassword("");
    setConfirm("");
  }

  return (
    <div className="auth-shell auth-shell-split">
      <div className="auth-bg" aria-hidden="true" />

      <Link to="/" className="auth-back" aria-label="Back to landing page">
        <span aria-hidden="true">←</span> Argus
      </Link>

      <div className="auth-grid">
        {/* ---------------- Left: form ---------------- */}
        <div className="auth-pane auth-pane-form">
          <div className="auth-brand">
            <ArgusLogo size={52} idSuffix="auth-brand" />
            <div className="auth-brand-text">
              <h1 className="auth-brand-title">Argus</h1>
              <p className="auth-brand-sub">Grounded document Q&amp;A</p>
            </div>
          </div>

          <div className="auth-tabs" role="tablist">
            <button
              type="button"
              role="tab"
              aria-selected={!isRegister}
              className={`auth-tab${!isRegister ? " active" : ""}`}
              onClick={() => switchMode("login")}
            >
              Log in
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={isRegister}
              className={`auth-tab${isRegister ? " active" : ""}`}
              onClick={() => switchMode("register")}
            >
              Sign up
            </button>
          </div>

          <p className="auth-lede">
            {isRegister
              ? "Create an account to start asking questions about your documents."
              : "Welcome back. Sign in to continue."}
          </p>

          <form onSubmit={onSubmit} className="auth-form">
            <label className="auth-field">
              <span className="auth-label">Email</span>
              <input
                type="email"
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
                disabled={submitting}
                required
              />
            </label>

            <label className="auth-field">
              <span className="auth-label">Password</span>
              <input
                type="password"
                autoComplete={isRegister ? "new-password" : "current-password"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder={isRegister ? "at least 8 characters" : "••••••••"}
                disabled={submitting}
                required
                minLength={isRegister ? 8 : undefined}
              />
            </label>

            {!isRegister && (
              <div style={{ textAlign: "right", marginTop: -6 }}>
                <Link
                  to="/forgot-password"
                  className="auth-link"
                  style={{ fontSize: "0.8rem" }}
                >
                  Forgot password?
                </Link>
              </div>
            )}

            {isRegister && (
              <label className="auth-field">
                <span className="auth-label">Confirm password</span>
                <input
                  type="password"
                  autoComplete="new-password"
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                  placeholder="re-enter password"
                  disabled={submitting}
                  required
                />
              </label>
            )}

            {error && <div className="auth-error">{error}</div>}

            <button
              type="submit"
              className="btn primary auth-submit"
              disabled={submitting}
            >
              {submitting
                ? isRegister
                  ? "Creating account…"
                  : "Signing in…"
                : isRegister
                  ? "Create account"
                  : "Sign in"}
            </button>
          </form>

          <div className="auth-or-divider">
            <span>or</span>
          </div>

          <a href={`${API_BASE}/api/v1/auth/google/start`} className="auth-google-btn">
            <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
              <path fill="#4285F4" d="M17.64 9.2c0-.63-.06-1.25-.16-1.84H9v3.49h4.84a4.14 4.14 0 0 1-1.8 2.71v2.26h2.91c1.7-1.57 2.69-3.88 2.69-6.62z"/>
              <path fill="#34A853" d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.91-2.26c-.81.54-1.85.86-3.05.86-2.34 0-4.32-1.58-5.03-3.71H.96v2.33A9 9 0 0 0 9 18z"/>
              <path fill="#FBBC05" d="M3.97 10.71a5.4 5.4 0 0 1 0-3.42V4.96H.96a9 9 0 0 0 0 8.08l3.01-2.33z"/>
              <path fill="#EA4335" d="M9 3.58c1.32 0 2.5.45 3.44 1.35l2.58-2.58C13.46.89 11.42 0 9 0A9 9 0 0 0 .96 4.96l3.01 2.33C4.68 5.16 6.66 3.58 9 3.58z"/>
            </svg>
            Continue with Google
          </a>

          <div className="auth-trust">
            <span className="auth-trust-pill">Grounded</span>
            <span className="auth-trust-pill">Cited by page</span>
            <span className="auth-trust-pill">Abstains when unsure</span>
          </div>

          <p className="auth-footnote">
            {isRegister
              ? "Already have an account? "
              : "Don't have an account yet? "}
            <button
              type="button"
              className="auth-link"
              onClick={() => switchMode(isRegister ? "login" : "register")}
            >
              {isRegister ? "Log in" : "Sign up"}
            </button>
          </p>
        </div>

        {/* ---------------- Right: live preview ---------------- */}
        <div className="auth-pane auth-pane-preview" aria-hidden="true">
          <AgentPreview />
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// useTilt — mousemove 3D rotation for the preview card.
//
// Writes rotateX/rotateY into CSS custom properties that the card's
// transform reads. Skipped on touch devices (hover doesn't exist there)
// and coalesced with requestAnimationFrame so rapid mousemoves only
// trigger one transform write per frame.
//
// Matches the landing-page hero artifact's behavior — same math, same
// maxDeg range, so the two pages feel consistent.
// ---------------------------------------------------------------------------
function useTilt(maxDeg = 6) {
  const ref = React.useRef<HTMLDivElement | null>(null);

  React.useEffect(() => {
    const el = ref.current;
    if (!el) return;

    if (typeof window === "undefined") return;
    if (window.matchMedia("(hover: none)").matches) return;

    let raf = 0;

    const onMove = (e: MouseEvent) => {
      const rect = el.getBoundingClientRect();
      const cx = rect.left + rect.width / 2;
      const cy = rect.top + rect.height / 2;
      const dx = (e.clientX - cx) / (rect.width / 2);
      const dy = (e.clientY - cy) / (rect.height / 2);
      const rx = Math.max(-1, Math.min(1, -dy)) * maxDeg;
      const ry = Math.max(-1, Math.min(1, dx)) * maxDeg;

      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => {
        el.style.setProperty("--auth-tilt-x", `${rx.toFixed(2)}deg`);
        el.style.setProperty("--auth-tilt-y", `${ry.toFixed(2)}deg`);
      });
    };

    const onLeave = () => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => {
        el.style.setProperty("--auth-tilt-x", "0deg");
        el.style.setProperty("--auth-tilt-y", "0deg");
      });
    };

    el.addEventListener("mousemove", onMove);
    el.addEventListener("mouseleave", onLeave);
    return () => {
      cancelAnimationFrame(raf);
      el.removeEventListener("mousemove", onMove);
      el.removeEventListener("mouseleave", onLeave);
    };
  }, [maxDeg]);

  return ref;
}

// ---------------------------------------------------------------------------
// AgentPreview — a live, looping view of the pipeline running, with a
// rotating set of sample Q&A pairs and a subtle mousemove tilt.
// ---------------------------------------------------------------------------
function AgentPreview() {
  const [activeStage, setActiveStage] = React.useState(-1);
  const [qaIndex, setQaIndex] = React.useState(0);
  const tiltRef = useTilt(6);

  // Trace animation.
  useEffect(() => {
    let cancelled = false;
    let timeoutId: number | undefined;

    const sequence: number[] = [
      -1,
      ...PREVIEW_STAGES.map((_, i) => i),
      PREVIEW_STAGES.length,
    ];

    let stepIndex = 0;

    const advance = () => {
      if (cancelled) return;

      if (stepIndex >= sequence.length) {
        stepIndex = 0;
      }

      const stage = sequence[stepIndex];
      setActiveStage(stage);

      let nextDelay = STAGE_RUNNING_MS;
      if (stage === -1) {
        nextDelay = LOOP_START_DELAY_MS;
      } else if (stage === PREVIEW_STAGES.length) {
        nextDelay = LOOP_HOLD_MS;
      }

      stepIndex += 1;
      timeoutId = window.setTimeout(advance, nextDelay);
    };

    timeoutId = window.setTimeout(advance, LOOP_START_DELAY_MS);

    return () => {
      cancelled = true;
      if (timeoutId !== undefined) window.clearTimeout(timeoutId);
    };
  }, []);

  // QA rotation — advance to the next question after every full trace cycle.
  useEffect(() => {
    const t = window.setInterval(() => {
      setQaIndex((prev) => (prev + 1) % PREVIEW_QA.length);
    }, FULL_CYCLE_MS);
    return () => window.clearInterval(t);
  }, []);

  const qa = PREVIEW_QA[qaIndex];

  return (
    <div className="auth-preview">
      <div className="auth-preview-glow" />

      <div ref={tiltRef} className="auth-preview-card">
        <div className="auth-preview-header">
          <ArgusLogo size={18} idSuffix="auth-preview" />
          <span className="auth-preview-doc">audit_Q3.pdf</span>
          <span className="auth-preview-badge">cited</span>
        </div>

        <div className="auth-preview-q">
          <span className="auth-preview-q-label">Q</span>
          {qa.question}
        </div>

        <div className="auth-preview-a">
          <p>{qa.answer}</p>
        </div>

        <div className="auth-preview-pills">
          <span className="auth-preview-pill">{qa.source}</span>
        </div>

        <div className="auth-preview-trace">
          <div className="auth-preview-trace-head">
            <span className="auth-preview-trace-dot" />
            Agent trace
          </div>
          <div className="auth-preview-trace-rows">
            {PREVIEW_STAGES.map((stage, i) => {
              const isComplete = i < activeStage;
              const isRunning = i === activeStage;
              const isIdle = !isComplete && !isRunning;
              return (
                <div
                  key={stage.state}
                  className={
                    "auth-preview-row" +
                    (isComplete ? " complete" : "") +
                    (isRunning ? " running" : "") +
                    (isIdle ? " idle" : "")
                  }
                >
                  <span className="auth-preview-row-dot" />
                  <span className="auth-preview-row-state">{stage.state}</span>
                  <span className="auth-preview-row-msg">
                    {isComplete
                      ? stage.done
                      : isRunning
                        ? stage.running
                        : "\u00A0"}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}