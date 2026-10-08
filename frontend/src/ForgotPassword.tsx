/**
 * Forgot-password page.
 *
 * Visual concept: a single glass card floating over the app's ambient
 * background, tilted very slightly on Y, with a slowly oscillating
 * Argus mark at the top. Behind the card, a rotating conic-gradient
 * ring gives the impression of an aurora slowly circling the panel.
 * Mouse hover straightens the tilt; mouse leave restores it.
 *
 * The whole page reads as one artifact — not a utility screen bolted
 * onto the auth flow, but the same visual language as the login card
 * and the reset-password page.
 */

import React, { useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { ArgusLogo } from "./ArgusLogo";

const API_BASE = "https://argus-grounded-document-q-a-production.up.railway.app/api/v1";

export function ForgotPassword() {
  const navigate = useNavigate();

  const [email, setEmail] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sentTo, setSentTo] = useState("");

  // Mousemove tilt — subtle, capped at 4 degrees.
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
      x: Math.max(-1, Math.min(1, -dy)) * 4,
      y: Math.max(-1, Math.min(1, dx)) * 4,
    });
  }

  function onLeave() {
    setTilt({ x: 0, y: 0 });
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    const trimmed = email.trim();
    if (!trimmed) {
      setError("Please enter your email.");
      return;
    }

    setSubmitting(true);
    try {
      const res = await fetch(`${API_BASE}/auth/forgot-password`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ email: trimmed }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || "Something went wrong");
      }
      setSentTo(trimmed);
      setDone(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="fp-page">
      <div className="fp-bg" aria-hidden="true" />

      <Link to="/login" className="fp-back">
        <span aria-hidden="true">←</span> Back to sign in
      </Link>

      <div className="fp-stage">
        <div className="fp-aurora" aria-hidden="true" />

        <div
          ref={cardRef}
          className="fp-card"
          onMouseMove={onMove}
          onMouseLeave={onLeave}
          style={{
            transform: `perspective(1400px) rotateX(${tilt.x}deg) rotateY(${tilt.y}deg)`,
          }}
        >
          <div className="fp-card-mark" aria-hidden="true">
            <div className="argus-3d-wrap" style={{ width: 44, height: 44 }}>
              <div
                className="argus-3d-scene"
                style={{ ["--argus-spin-duration" as any]: "22s" }}
              >
                <div className="argus-3d-face">
                  <ArgusLogo size={44} idSuffix="fp-mark-a" />
                </div>
                <div className="argus-3d-face argus-3d-back">
                  <ArgusLogo size={44} idSuffix="fp-mark-b" />
                </div>
              </div>
            </div>
          </div>

          <h1 className="fp-title">Reset password</h1>
          <p className="fp-sub">We'll email you a reset link.</p>

          {done ? (
            <div className="fp-success">
              <div className="fp-success-glyph" aria-hidden="true">✉</div>
              <p className="fp-success-text">
                If an account exists for <strong>{sentTo}</strong>, we've
                sent a reset link. Check your inbox — the link expires in
                30&nbsp;minutes.
              </p>
              <button
                type="button"
                className="fp-link"
                onClick={() => {
                  setDone(false);
                  setEmail("");
                  setSentTo("");
                }}
              >
                Use a different email
              </button>
            </div>
          ) : (
            <form onSubmit={onSubmit} className="fp-form">
              <label className="fp-field">
                <span className="fp-label">Email</span>
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

              {error && <div className="fp-error">{error}</div>}

              <button
                type="submit"
                className="fp-submit"
                disabled={submitting}
              >
                {submitting ? "Sending…" : "Send reset link"}
              </button>
            </form>
          )}
        </div>

        <p className="fp-footnote">
          Remembered it?{" "}
          <button
            type="button"
            className="fp-link"
            onClick={() => navigate("/login")}
          >
            Sign in
          </button>
        </p>
      </div>
    </div>
  );
}