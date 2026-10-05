/**
 * Auth context — one source of truth for "who is logged in".
 *
 * On mount, the provider hits ``GET /api/v1/auth/me``. The browser sends
 * the ``argus_session`` cookie automatically (via ``credentials: include``),
 * so if the cookie is valid the backend returns the user and the app
 * renders. If it 401s, the user is logged out and the auth screen shows.
 *
 * ``login`` and ``register`` hit their endpoints, and on success the
 * server sets the cookie and returns the user. We store that in state;
 * subsequent requests carry the cookie without any further work.
 *
 * ``logout`` clears the cookie server-side and resets state.
 *
 * The ``is_admin`` flag rides along on the user object returned by the
 * backend. Admin-gated UI reads ``isAdmin`` from this context rather
 * than poking at ``user`` directly, so the field stays swappable.
 */

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

import { API } from "./api";

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

const AUTH_BASE = `${API}/auth`;

async function parseError(resp: Response): Promise<string> {
  try {
    const body = await resp.json();
    if (body && typeof body.detail === "string") return body.detail;
  } catch {
    /* fall through */
  }
  return `Request failed (${resp.status})`;
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
      const data = (await resp.json()) as AuthUser;
      setUser(data);
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
      const data = (await resp.json()) as AuthUser;
      setUser(data);
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