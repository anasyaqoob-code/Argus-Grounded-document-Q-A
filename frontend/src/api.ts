/** HTTP client for the Argus backend.
 *
 * Auth is via an HTTP-only cookie (``argus_session``) set by the auth
 * endpoints. Every request carries ``credentials: "include"`` so the
 * browser sends the cookie. The backend reads the user id from the
 * JWT — nothing client-supplied controls who you are.
 *
 * The Vite dev server proxies /api and /health to localhost:8000 (see
 * vite.config.ts) in development. In production, ``VITE_API_BASE``
 * must be set to the backend's public URL; Vite bakes it into the
 * bundle at build time. If it's missing in production, the fallback
 * is an empty string (same-origin), which fails loudly instead of
 * silently trying to reach the user's own localhost.
 */

import type {
  AnswerResponse,
  DocumentInfo,
  QueryRequest,
  SessionHistory,
  SessionInfo,
  UploadResponse,
} from "./types";

const env = (import.meta as unknown as {
  env?: { VITE_API_BASE?: string; PROD?: boolean };
}).env;

/**
 * In dev, the fallback is localhost:8000 so `npm run dev` works out of
 * the box. In production, an empty fallback means "same origin" — the
 * browser sends requests to whatever domain served the page. That fails
 * loudly if VITE_API_BASE wasn't set on Railway, which is better than
 * silently trying to reach the user's own localhost.
 */
const BASE =
  env?.VITE_API_BASE ?? (env?.PROD ? "" : "http://localhost:8000");

const API = `${BASE}/api/v1`;

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      const d = body?.detail;
      if (d && typeof d === "object" && "message" in d) {
        detail = String((d as { message: string }).message);
      } else if (typeof d === "string") {
        detail = d;
      } else {
        detail = JSON.stringify(body);
      }
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// Health
// ---------------------------------------------------------------------------
export async function health(): Promise<{ status: string; version: string }> {
  const res = await fetch(`${BASE}/health`, { credentials: "include" });
  return handle(res);
}

// ---------------------------------------------------------------------------
// Documents
// ---------------------------------------------------------------------------
export async function listDocuments(): Promise<DocumentInfo[]> {
  const res = await fetch(`${API}/documents`, { credentials: "include" });
  return handle(res);
}

export async function uploadDocument(file: File): Promise<UploadResponse> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${API}/upload`, {
    method: "POST",
    body: form,
    credentials: "include",
  });
  return handle(res);
}

export interface DeleteDocumentResult {
  ok: boolean;
  document_id: string;
  deleted_sessions: string[];
}

export async function deleteDocument(
  documentId: string,
  options: { purgeConversations?: boolean } = {},
): Promise<DeleteDocumentResult> {
  const qs = options.purgeConversations ? "?purge_conversations=true" : "";
  const resp = await fetch(`${API}/documents/${documentId}${qs}`, {
    method: "DELETE",
    credentials: "include",
  });
  if (!resp.ok) throw new Error(`Delete failed: ${resp.statusText}`);
  return resp.json();
}

// ---------------------------------------------------------------------------
// Query (non-streaming, mostly unused — kept for completeness)
// ---------------------------------------------------------------------------
export async function queryOnce(req: QueryRequest): Promise<AnswerResponse> {
  const res = await fetch(`${API}/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...req, stream: false }),
    credentials: "include",
  });
  return handle(res);
}

// ---------------------------------------------------------------------------
// Sessions
// ---------------------------------------------------------------------------
export async function listSessions(): Promise<SessionInfo[]> {
  const res = await fetch(`${API}/sessions`, { credentials: "include" });
  const body = await handle<{ sessions: SessionInfo[] }>(res);
  return body.sessions ?? [];
}

export async function getSession(id: string): Promise<SessionHistory | null> {
  const res = await fetch(`${API}/sessions/${id}`, {
    credentials: "include",
  });
  if (res.status === 404) return null;
  return handle<SessionHistory>(res);
}

export async function deleteSession(id: string): Promise<void> {
  const res = await fetch(`${API}/sessions/${id}`, {
    method: "DELETE",
    credentials: "include",
  });
  await handle(res);
}

/** Rename a session. Returns the updated row on success, null on failure. */
export async function renameSession(
  id: string,
  title: string,
): Promise<SessionInfo | null> {
  try {
    const res = await fetch(`${API}/sessions/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
      credentials: "include",
    });
    if (!res.ok) return null;
    return (await res.json()) as SessionInfo;
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Feedback
// ---------------------------------------------------------------------------
export async function setFeedback(
  messageId: number,
  rating: "up" | "down",
): Promise<void> {
  const res = await fetch(
    `${API}/feedback/${messageId}?rating=${encodeURIComponent(rating)}`,
    { method: "POST", credentials: "include" },
  );
  if (!res.ok) {
    // 204 is expected on success; 404 means the message is gone — ignore.
    if (res.status !== 204 && res.status !== 404) {
      const body = await res.text();
      throw new Error(`Feedback failed: ${res.status} ${body}`);
    }
  }
}

// ---------------------------------------------------------------------------
// Suggested questions
// ---------------------------------------------------------------------------
export async function suggestQuestions(
  documentIds?: string[],
  maxQuestions = 4,
): Promise<string[]> {
  try {
    const res = await fetch(`${API}/suggest`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        document_ids: documentIds ?? null,
        max_questions: maxQuestions,
      }),
      credentials: "include",
    });
    if (!res.ok) return [];
    const body = (await res.json()) as { questions?: string[] };
    return body.questions ?? [];
  } catch {
    return [];
  }
}

// ---------------------------------------------------------------------------
// Export
// ---------------------------------------------------------------------------
export async function exportMarkdown(sessionId: string): Promise<Blob | null> {
  const res = await fetch(`${API}/sessions/${sessionId}/export.md`, {
    credentials: "include",
  });
  if (!res.ok) return null;
  return res.blob();
}

export async function exportPdf(sessionId: string): Promise<Blob | null> {
  const res = await fetch(`${API}/sessions/${sessionId}/export.pdf`, {
    credentials: "include",
  });
  if (!res.ok) return null;
  return res.blob();
}

/** Trigger a browser download from a Blob. */
export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** Send an image for question extraction + Q/A. Returns an EventSource-
 *  style stream of events: questions, answer_start, answer_chunk,
 *  answer_done, done. */
export async function queryImage(
  file: File,
  opts: {
    sessionId?: string;
    documentIds?: string[];
    onEvent: (event: { type: string; data: unknown }) => void;
  },
): Promise<void> {
  const form = new FormData();
  form.append("file", file);
  if (opts.sessionId) form.append("session_id", opts.sessionId);
  if (opts.documentIds?.length) {
    form.append("document_ids", opts.documentIds.join(","));
  }

  const res = await fetch(`${API}/query/image`, {
    method: "POST",
    body: form,
    credentials: "include",
  });

  if (!res.ok || !res.body) {
    throw new Error(`Image query failed: ${res.status}`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // Split SSE frames on double newlines.
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";

    for (const frame of frames) {
      if (!frame.trim()) continue;
      let type = "message";
      let data = "";
      for (const line of frame.split("\n")) {
        if (line.startsWith("event: ")) type = line.slice(7).trim();
        else if (line.startsWith("data: ")) data += line.slice(6);
      }
      if (!data) continue;
      try {
        opts.onEvent({ type, data: JSON.parse(data) });
      } catch {
        // Ignore malformed frame; the next one will carry the payload.
      }
    }
  }
}

export { BASE, API };