/**
 * Auth context — one source of truth for "who is logged in".
 *
 * On mount, the provider hits ``GET /api/v1/auth/me``. The browser sends
 * the ``argus_session`` cookie automatically (via ``credentials: include``),
 * so if the cookie is valid the backend returns the user and the app
 * renders. If it 401s, the user is logged out and the auth screen shows.
 *
 * login / register / Google all use the same two-step pattern:
 *
 *   1. POST to the endpoint. The backend validates credentials (or the
 *      Google callback) and returns a one-time ``exchange_token`` — it
 *      does NOT set the session cookie on this response.
 *
 *   2. POST that token to ``/auth/exchange`` via fetch(). The backend
 *      sets the session cookie on THIS response, and returns the user.
 *
 * Why the two-step dance? Chrome's Bounce Tracking Mitigations delete
 * cookies set on cross-site POSTs that come from a different top-level
 * origin — which is exactly what our split-origin deploy produces. When
 * the cookie is set on a fetch() response instead, the mitigation leaves
 * it alone. See backend/app/google_auth.py for the long-form rationale.
 *
 * URL NOTE: this file hardcodes the backend origin rather than importing
 * it from ``api.ts``. The frontend and backend are on different Railway
 * hosts; any "empty fallback = same origin" would send auth requests to
 * the frontend Caddy server, which returns index.html for unknown paths.
 * Hardcoding here means an api.ts regression can't break auth.
 */

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

export interface AuthUser {
  user_id: string;
  email: string;
  is_admin?: boolean;
}

interface AuthContextValue {
  user: AuthUser | null;
  isAdmin: boolean;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

/**
 * Absolute backend URL. Do NOT derive this from import.meta.env or
 * window.location — either can resolve to the frontend host and produce
 * "same origin" requests that silently 200 with HTML.
 */
const BACKEND_ORIGIN = "https://argus-grounded-document-q-a-production.up.railway.app";
const AUTH_BASE = `${BACKEND_ORIGIN}/api/v1/auth`;

async function parseError(resp: Response): Promise<string> {
  try {
    const body = await resp.json();
    if (body && typeof body.detail === "string") return body.detail;
  } catch {
    /* fall through */
  }
  return `Request failed (${resp.status})`;
}

/**
 * Redeem a one-time exchange token for a session cookie.
 *
 * The cookie is set on THIS fetch response, not on the login/register
 * POST that produced the token. Browsers exempt fetch-initiated
 * Set-Cookie from bounce-tracking cookie clearing; navigation-initiated
 * Set-Cookie across origins is not exempt. This is the whole reason the
 * two-step flow exists.
 */
async function exchangeToken(token: string): Promise<AuthUser> {
  const resp = await fetch(`${AUTH_BASE}/exchange`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token }),
  });
  if (!resp.ok) throw new Error(await parseError(resp));
  return (await resp.json()) as AuthUser;
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const resp = await fetch(`${AUTH_BASE}/me`, {
        credentials: "include",
      });
      if (!resp.ok) {
        setUser(null);
        return;
      }
      const data = (await resp.json()) as AuthUser;
      setUser(data);
    } catch {
      setUser(null);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        await refresh();
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [refresh]);

  const login = useCallback(
    async (email: string, password: string) => {
      const resp = await fetch(`${AUTH_BASE}/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ email, password }),
      });
      if (!resp.ok) throw new Error(await parseError(resp));
      const data = (await resp.json()) as { exchange_token: string };
      setUser(await exchangeToken(data.exchange_token));
    },
    [],
  );

  const register = useCallback(
    async (email: string, password: string) => {
      const resp = await fetch(`${AUTH_BASE}/register`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ email, password }),
      });
      if (!resp.ok) throw new Error(await parseError(resp));
      const data = (await resp.json()) as { exchange_token: string };
      setUser(await exchangeToken(data.exchange_token));
    },
    [],
  );

  const logout = useCallback(async () => {
    try {
      await fetch(`${AUTH_BASE}/logout`, {
        method: "POST",
        credentials: "include",
      });
    } catch {
      /* best-effort — clearing state is what matters */
    }
    setUser(null);
  }, []);

  const isAdmin = Boolean(user?.is_admin);

  const value = useMemo<AuthContextValue>(
    () => ({ user, isAdmin, loading, login, register, logout, refresh }),
    [user, isAdmin, loading, login, register, logout, refresh],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used inside <AuthProvider>");
  }
  return ctx;
}