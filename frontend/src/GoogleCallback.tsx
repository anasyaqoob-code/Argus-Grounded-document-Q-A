import React, { useEffect } from "react";
import { useNavigate } from "react-router-dom";

import { useAuth } from "./AuthContext";

/**
 * Google's OAuth flow lands here. The backend already exchanged the
 * code, set the session cookie, and redirected — so this component
 * mostly just refreshes the auth context and pushes to /app.
 *
 * If we reach this route without a cookie (something failed on the
 * backend), we fall back to /login with an error.
 */
export function GoogleCallback() {
  const { refresh } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        if (refresh) await refresh();
      } catch {
        /* ignore */
      }
      if (!cancelled) navigate("/app", { replace: true });
    })();
    return () => {
      cancelled = true;
    };
  }, [navigate, refresh]);

  return (
    <div className="auth-shell auth-shell-split">
      <div className="auth-bg" aria-hidden="true" />
      <div className="auth-grid">
        <div className="auth-pane auth-pane-form">
          <div className="auth-loading">Signing you in…</div>
        </div>
      </div>
    </div>
  );
}