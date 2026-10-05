/** SSE parser for /api/v1/query/stream. */

export type SseEventType = "step" | "token" | "final" | "error" | "done";

export interface SseEvent {
  type: SseEventType;
  data: unknown;
}

export async function streamQuery(
  url: string,
  body: unknown,
  onEvent: (ev: SseEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(url, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
  credentials: "include",
});

  if (!res.ok || !res.body) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = j.detail?.message ?? j.detail ?? detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";

    for (const frame of frames) {
      if (!frame.trim()) continue;
      const dataLines: string[] = [];
      for (const raw of frame.split("\n")) {
        const line = raw.trimStart();
        if (line.startsWith("data:")) {
          dataLines.push(line.slice(5).trimStart());
        }
      }
      if (!dataLines.length) continue;

      let parsed: unknown;
      try {
        parsed = JSON.parse(dataLines.join("\n"));
      } catch {
        continue;
      }

      const env = parsed as { type?: string; data?: unknown };
      const t = env.type;

      if (t === "done") {
        onEvent({ type: "done", data: null });
        return;
      }
      if (t === "step" || t === "token" || t === "final" || t === "error") {
        onEvent({ type: t, data: env.data });
      }
    }
  }
}