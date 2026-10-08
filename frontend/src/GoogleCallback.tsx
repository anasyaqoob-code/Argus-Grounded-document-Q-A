import React, { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { API } from "./api";
import { useAuth } from "./AuthContext";

/**
 * Frontend side of the Google OAuth handoff.
 *
 * The backend no longer sets the session cookie on the /callback
 * redirect (Chrome's bounce-tracking mitigations delete cookies set
 * on domains that only appear as redirect hops). Instead, the backend
 * redirects here with a one-time `?token=...`, and we POST it to
 * /auth/exchange via fetch. The cookie is set on THAT response — a
 * fetch response, not a navigation — so it survives.
 *
 * On success we refresh AuthContext (populating `user`) and navigate
 * to /app. On failure we show the error inline with a link back to
 * /login.
 */
export function GoogleCallback() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { refresh } = useAuth();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const token = params.get("token");
    if (!token) {
      setError("Missing token");
      return;
    }

    let cancelled = false;

    (async () => {
      try {
        const resp = await fetch(`${API}/auth/exchange`, {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ token }),
        });
        if (!resp.ok) {
          const body = await resp.text().catch(() => "");
          throw new Error(`Exchange failed (${resp.status}): ${body}`);
        }
        if (cancelled) return;
        await refresh();
        if (cancelled) return;
        navigate("/app", { replace: true });
      } catch (e: unknown) {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : "Exchange failed");
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [params, navigate, refresh]);

  return (
    <div className="auth-shell auth-shell-split">
      <div className="auth-bg" aria-hidden="true" />
      <div className="auth-grid">
        <div className="auth-pane auth-pane-form">
          {error ? (
            <div className="auth-error">
              Sign-in failed: {error}. <a href="/login">Back to login</a>
            </div>
          ) : (
            <div className="auth-loading">Signing you in…</div>
          )}
        </div>
      </div>
    </div>
  );
}