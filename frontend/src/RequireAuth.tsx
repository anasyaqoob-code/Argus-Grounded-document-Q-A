/**
 * Route guard — renders children only if the user is authenticated.
 *
 * While the auth check is in flight (``loading === true``), renders a
 * placeholder so the user doesn't see a flash of the login page before
 * the session resolves. If loading finishes and there's no user, redirects
 * to /login with the current path preserved so we can send them back after
 * they sign in.
 */

import React from "react";
import { Navigate, useLocation } from "react-router-dom";

import { useAuth } from "./AuthContext";

export function RequireAuth({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  const location = useLocation();

  if (loading) {
    return (
      <div className="auth-shell">
        <div className="auth-loading">Loading…</div>
      </div>
    );
  }

  if (!user) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }

  return <>{children}</>;
}