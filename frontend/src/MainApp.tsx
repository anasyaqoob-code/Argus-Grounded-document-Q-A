/** The authenticated Argus app — same code as before, now behind a route guard. */

import React, { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  API,
  deleteDocument,
  deleteSession,
  downloadBlob,
  exportMarkdown,
  exportPdf,
  getSession,
  health,
  listDocuments,
  listSessions,
  queryImage,
  renameSession,
  setFeedback as apiSetFeedback,
  suggestQuestions,
  uploadDocument,
} from "./api";
import {
  AgentSettingsPanel,
  BrandHeader,
  ChatHeader,
  ChatPanel,
  DocumentList,
  HeroEmptyState,
  IndexStatsExpander,
  SessionList,
} from "./components";
import { useAuth } from "./AuthContext";
import { streamQuery, type SseEvent } from "./sse";
import { useSpeech } from "./useVoice";
import {
  DEFAULT_AGENT_SETTINGS,
  type ActivityStep,
  type AgentSettings,
  type ChatMessage,
  type Citation,
  type DocumentInfo,
  type ImageBatch,
  type SessionInfo,
  type SourcePreview,
} from "./types";

function uid(): string {
  return Math.random().toString(36).slice(2, 10);
}

const SETTINGS_KEY = "argus.settings";
const SHOW_ACTIVITY_KEY = "argus.showActivity";
const SHOW_SOURCES_KEY = "argus.showSources";
const SIDEBAR_COLLAPSED_KEY = "argus.sidebarCollapsed";

function loadSettings(): AgentSettings {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY);
    if (!raw) return { ...DEFAULT_AGENT_SETTINGS };

    const parsed = JSON.parse(raw) as Partial<AgentSettings>;
    const merged: AgentSettings = { ...DEFAULT_AGENT_SETTINGS };
    const writable = merged as unknown as Record<string, unknown>;

    for (const key of Object.keys(
      DEFAULT_AGENT_SETTINGS,
    ) as (keyof AgentSettings)[]) {
      const candidate = parsed[key];
      if (candidate !== undefined && typeof candidate === typeof merged[key]) {
        writable[key] = candidate;
      }
    }
    return merged;
  } catch {
    /* ignore */
  }
  return { ...DEFAULT_AGENT_SETTINGS };
}

function saveSettings(s: AgentSettings): void {
  try {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(s));
  } catch {
    /* ignore */
  }
}

export function MainApp() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const [version, setVersion] = useState<string>();
  const [error, setError] = useState<string | null>(null);

  const [docs, setDocs] = useState<DocumentInfo[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);
  const [processing, setProcessing] = useState(false);

  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | undefined>();

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [busy, setBusy] = useState(false);

  const [feedback, setFeedback] = useState<Record<number, "up" | "down">>({});
  const [suggested, setSuggested] = useState<string[]>([]);

  const [settings, setSettings] = useState<AgentSettings>(() => loadSettings());
  const [showActivity, setShowActivity] = useState<boolean>(() => {
    try {
      return localStorage.getItem(SHOW_ACTIVITY_KEY) !== "false";
    } catch {
      return true;
    }
  });
  const [showSources, setShowSources] = useState<boolean>(() => {
    try {
      return localStorage.getItem(SHOW_SOURCES_KEY) !== "false";
    } catch {
      return true;
    }
  });
  const [sidebarCollapsed, setSidebarCollapsed] = useState<boolean>(() => {
    try {
      return localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === "true";
    } catch {
      return false;
    }
  });

  const speech = useSpeech();

  useEffect(() => saveSettings(settings), [settings]);
  useEffect(() => {
    try {
      localStorage.setItem(SHOW_ACTIVITY_KEY, String(showActivity));
    } catch {
      /* ignore */
    }
  }, [showActivity]);
  useEffect(() => {
    try {
      localStorage.setItem(SHOW_SOURCES_KEY, String(showSources));
    } catch {
      /* ignore */
    }
  }, [showSources]);
  useEffect(() => {
    try {
      localStorage.setItem(SIDEBAR_COLLAPSED_KEY, String(sidebarCollapsed));
    } catch {
      /* ignore */
    }
  }, [sidebarCollapsed]);

  useEffect(() => {
    function onMove(e: MouseEvent) {
      const root = document.documentElement;
      const x = (e.clientX / window.innerWidth - 0.5) * 2;
      const y = (e.clientY / window.innerHeight - 0.5) * 2;
      root.style.setProperty("--mx", x.toFixed(3));
      root.style.setProperty("--my", y.toFixed(3));
    }
    window.addEventListener("mousemove", onMove, { passive: true });
    return () => window.removeEventListener("mousemove", onMove);
  }, []);

  const readyDocs = docs.filter((d) => d.status === "ready");
  const hasReadyDocs = readyDocs.length > 0;

  useEffect(() => {
    setSelected((prev) => {
      const next = new Set(prev);
      let changed = false;
      for (const d of docs) {
        if (d.status === "ready" && !next.has(d.document_id)) {
          next.add(d.document_id);
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, [docs]);

  const refreshDocs = useCallback(async (): Promise<DocumentInfo[]> => {
    try {
      const fresh = await listDocuments();
      setDocs(fresh);
      return fresh;
    } catch (e) {
      setError(String(e));
      return [];
    }
  }, []);

  const refreshSessions = useCallback(async () => {
    try {
      setSessions(await listSessions());
    } catch (e) {
      setError(String(e));
    }
  }, []);

  useEffect(() => {
    health()
      .then((h) => setVersion(h.version))
      .catch(() => setVersion(undefined));
    refreshDocs();
    refreshSessions();
  }, [refreshDocs, refreshSessions]);

  function toggleDoc(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function handlePickFiles(files: File[]) {
    setPendingFiles((prev) => [...prev, ...files]);
  }

  async function handleProcess() {
    if (pendingFiles.length === 0) return;
    setProcessing(true);
    setError(null);

    const failed: string[] = [];
    for (const f of pendingFiles) {
      try {
        const resp = await uploadDocument(f);
        if (resp.status === "failed") {
          failed.push(`${f.name}: ${resp.message}`);
        }
      } catch (e) {
        failed.push(`${f.name}: ${String(e)}`);
      }
    }

    setPendingFiles([]);

    let fresh: DocumentInfo[] = [];
    try {
      fresh = await listDocuments();
    } catch (e) {
      setError(String(e));
      setProcessing(false);
      return;
    }
    setDocs(fresh);

    setSelected((prev) => {
      const next = new Set(prev);
      for (const d of fresh) {
        if (d.status === "ready") next.add(d.document_id);
      }
      return next;
    });

    const freshReadyIds = fresh
      .filter((d) => d.status === "ready")
      .map((d) => d.document_id);
    if (freshReadyIds.length > 0) {
      try {
        const qs = await suggestQuestions(freshReadyIds, 4);
        setSuggested(qs);
      } catch {
        /* suggestions optional */
      }
    }

    setProcessing(false);

    if (failed.length > 0) {
      setError(`Some files failed to index:\n${failed.join("\n")}`);
    }
  }

  async function handleDeleteDoc(id: string) {
    const doc = docs.find((d) => d.document_id === id);
    const filename = doc?.filename ?? "this document";

    const purge = confirm(
      `Delete "${filename}"?\n\n` +
        `Click OK to also delete every conversation that cited this ` +
        `document. Click Cancel to keep conversations and delete only ` +
        `the document from retrieval.`,
    );

    try {
      const result = await deleteDocument(id, {
        purgeConversations: purge,
      });
      setSelected((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
      await refreshDocs();
      await refreshSessions();

      if (activeSessionId && result.deleted_sessions.includes(activeSessionId)) {
        setActiveSessionId(undefined);
        setMessages([]);
      }

      if (result.deleted_sessions.length > 0) {
        setError(
          `Deleted "${filename}" and ${result.deleted_sessions.length} ` +
            `conversation${result.deleted_sessions.length === 1 ? "" : "s"}.`,
        );
      }
    } catch (e) {
      setError(String(e));
    }
  }

  async function handleClearAllDocs() {
    const purge = confirm(
      "Delete every indexed document?\n\n" +
        "Click OK to also delete every conversation that cited any of " +
        "them. Click Cancel to keep conversations and delete only the " +
        "documents from retrieval.",
    );
    try {
      for (const d of docs) {
        await deleteDocument(d.document_id, { purgeConversations: purge });
      }
      setSelected(new Set());
      setSuggested([]);
      setActiveSessionId(undefined);
      setMessages([]);
      await refreshDocs();
      await refreshSessions();
    } catch (e) {
      setError(String(e));
    }
  }

  async function handleSelectSession(id: string) {
    setActiveSessionId(id);

    const history = await getSession(id);
    if (!history) {
      setMessages([]);
      return;
    }

    const restored: ChatMessage[] = [];
    const batches = new Map<string, ImageBatch>();

    for (const m of history.messages) {
      const meta = m.metadata as {
        sources?: SourcePreview[];
        trace?: ActivityStep[];
        citations?: Citation[];
        abstained?: boolean;
        insufficient_evidence?: boolean;
        image_upload?: boolean;
        image_id?: string;
        image_url?: string;
        image_answer?: boolean;
        question_id?: number;
        question_text?: string;
        not_covered?: boolean;
      };

      if (meta.image_upload && meta.image_id && meta.image_url) {
        let batch = batches.get(meta.image_id);
        if (!batch) {
          batch = {
            imageId: meta.image_id,
            imageUrl: meta.image_url,
            items: [],
          };
          batches.set(meta.image_id, batch);
          restored.push({
            id: uid(),
            messageId: m.message_id,
            role: "assistant",
            content: "",
            streaming: false,
            batch,
          });
        }
        continue;
      }

      if (meta.image_answer && meta.image_id) {
        const batch = batches.get(meta.image_id);
        if (batch) {
          const citations: SourcePreview[] = (meta.citations ?? []).map(
            (c) => ({
              source: c.filename,
              page: c.page ?? "?",
              preview: c.quote ?? "",
            }),
          );
          batch.items.push({
            id: meta.question_id ?? batch.items.length + 1,
            question: meta.question_text ?? "",
            answer: m.content,
            citations,
            notCovered: Boolean(meta.not_covered),
            streaming: false,
          });
        }
        continue;
      }

      restored.push({
        id: uid(),
        messageId: m.message_id,
        role: m.role,
        content: m.content,
        sources: meta.sources,
        trace: meta.trace,
        citations: meta.citations,
        abstained: meta.abstained ?? meta.insufficient_evidence,
        streaming: false,
      });
    }

    for (const batch of batches.values()) {
      batch.items.sort((a, b) => a.id - b.id);
    }

    setMessages(restored);
  }

  function handleNewSession() {
    setActiveSessionId(undefined);
    setMessages([]);
    if (!hasReadyDocs) setSuggested([]);
  }

  async function handleDeleteSession(id: string) {
    try {
      await deleteSession(id);
      if (activeSessionId === id) {
        setActiveSessionId(undefined);
        setMessages([]);
      }
      await refreshSessions();
    } catch (e) {
      setError(String(e));
    }
  }

  async function handleRenameSession(id: string, title: string) {
    setSessions((prev) =>
      prev.map((s) => (s.session_id === id ? { ...s, title } : s)),
    );
    try {
      const updated = await renameSession(id, title);
      if (updated) {
        setSessions((prev) =>
          prev.map((s) =>
            s.session_id === id ? { ...s, title: updated.title } : s,
          ),
        );
      } else {
        await refreshSessions();
      }
    } catch (e) {
      setError(String(e));
      await refreshSessions();
    }
  }

  async function handleFeedback(messageId: number, rating: "up" | "down") {
    setFeedback((prev) => ({ ...prev, [messageId]: rating }));
    try {
      await apiSetFeedback(messageId, rating);
    } catch {
      /* best-effort */
    }
  }

  async function handleRegenerate() {
    if (messages.length < 2) return;

    let idx = -1;
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === "user") {
        idx = i;
        break;
      }
    }
    if (idx === -1) return;

    const lastUser = messages[idx];
    setMessages((msgs) => msgs.slice(0, idx));
    await handleSend(lastUser.content);
  }

  async function handleExportMarkdown() {
    if (!activeSessionId) {
      setError("Start a conversation first — nothing to export yet.");
      return;
    }
    const blob = await exportMarkdown(activeSessionId);
    if (blob) {
      downloadBlob(blob, `argus-${activeSessionId.slice(0, 8)}.md`);
    } else {
      setError("Export failed — session not found.");
    }
  }

  async function handleExportPdf() {
    if (!activeSessionId) {
      setError("Start a conversation first — nothing to export yet.");
      return;
    }
    const blob = await exportPdf(activeSessionId);
    if (blob) {
      downloadBlob(blob, `argus-${activeSessionId.slice(0, 8)}.pdf`);
    } else {
      setError("Export failed — session not found.");
    }
  }

  async function handleImageQuery(file: File) {
    if (!hasReadyDocs) {
      setError("Upload and process at least one document before asking.");
      return;
    }

    setBusy(true);
    setError(null);

    const docIds =
      selected.size > 0
        ? Array.from(selected)
        : readyDocs.map((d) => d.document_id);

    const batchMessageId = uid();
    const placeholder: ImageBatch = {
      imageId: "",
      imageUrl: "",
      items: [],
    };
    setMessages((m) => [
      ...m,
      {
        id: batchMessageId,
        role: "assistant",
        content: "",
        streaming: true,
        batch: placeholder,
      },
    ]);

    try {
      await queryImage(file, {
        sessionId: activeSessionId,
        documentIds: docIds,
        onEvent: (ev) => {
          if (ev.type === "questions") {
            const d = ev.data as {
              questions: string[];
              image_url?: string;
              message_id?: number;
            };
            setMessages((msgs) =>
              msgs.map((msg) => {
                if (msg.id !== batchMessageId || !msg.batch) return msg;
                return {
                  ...msg,
                  messageId: d.message_id ?? msg.messageId,
                  batch: {
                    ...msg.batch,
                    imageUrl: d.image_url ?? msg.batch.imageUrl,
                    items: d.questions.map((text, i) => ({
                      id: i + 1,
                      question: text,
                      answer: "",
                      citations: [],
                      notCovered: false,
                      streaming: true,
                    })),
                  },
                };
              }),
            );
          } else if (ev.type === "answer_start") {
            const id = (ev.data as { id: number }).id;
            setMessages((msgs) =>
              msgs.map((msg) => {
                if (msg.id !== batchMessageId || !msg.batch) return msg;
                return {
                  ...msg,
                  batch: {
                    ...msg.batch,
                    items: msg.batch.items.map((it) =>
                      it.id === id ? { ...it, streaming: true } : it,
                    ),
                  },
                };
              }),
            );
          } else if (ev.type === "answer_done") {
            const d = ev.data as {
              id: number;
              answer: string;
              citations?: Array<{
                filename?: string;
                page?: number | string | null;
                quote?: string;
              }>;
              not_covered: boolean;
            };
            const citations: SourcePreview[] = (d.citations ?? []).map(
              (c) => ({
                source: c.filename ?? "?",
                page: c.page ?? "?",
                preview: c.quote ?? "",
              }),
            );
            setMessages((msgs) =>
              msgs.map((msg) => {
                if (msg.id !== batchMessageId || !msg.batch) return msg;
                return {
                  ...msg,
                  batch: {
                    ...msg.batch,
                    items: msg.batch.items.map((it) =>
                      it.id === d.id
                        ? {
                            ...it,
                            answer: d.answer,
                            citations,
                            notCovered: d.not_covered,
                            streaming: false,
                          }
                        : it,
                    ),
                  },
                };
              }),
            );
          } else if (ev.type === "done") {
            setMessages((msgs) =>
              msgs.map((msg) => {
                if (msg.id !== batchMessageId || !msg.batch) return msg;
                return {
                  ...msg,
                  streaming: false,
                  batch: {
                    ...msg.batch,
                    items: msg.batch.items.map((it) => ({
                      ...it,
                      streaming: false,
                    })),
                  },
                };
              }),
            );
          }
        },
      });
    } catch (e) {
      setError(String(e));
      setMessages((msgs) =>
        msgs.filter((msg) => msg.id !== batchMessageId),
      );
    } finally {
      setBusy(false);
      await refreshSessions();
    }
  }

  async function handleSend(query: string) {
    if (!hasReadyDocs) {
      setError(
        "Upload and process at least one document before asking questions.",
      );
      return;
    }

    let docIds: string[] | undefined;
    if (selected.size > 0) {
      docIds = Array.from(selected);
    } else {
      docIds = readyDocs.map((d) => d.document_id);
      setSelected(new Set(docIds));
    }

    setBusy(true);
    setError(null);

    const userMsg: ChatMessage = { id: uid(), role: "user", content: query };
    const assistantId = uid();
    setMessages((m) => [
      ...m,
      userMsg,
      {
        id: assistantId,
        role: "assistant",
        content: "",
        streaming: true,
        trace: [],
        sources: [],
      },
    ]);

    try {
      await streamQuery(
        `${API}/query/stream`,
        {
          query,
          session_id: activeSessionId,
          document_ids: docIds,
          stream: true,
          top_k: settings.top_k,
          score_threshold: settings.similarity_threshold,
          require_citations: settings.source_citations,
          allow_abstain: true,
        },
        (ev: SseEvent) => {
          if (ev.type === "step") {
            const step = ev.data as ActivityStep;
            setMessages((msgs) =>
              msgs.map((msg) => {
                if (msg.id !== assistantId) return msg;
                const trace = [...(msg.trace ?? [])];
                const last = trace[trace.length - 1];
                if (
                  last &&
                  last.state === step.state &&
                  step.status !== "running"
                ) {
                  trace[trace.length - 1] = step;
                } else {
                  trace.push(step);
                }
                return { ...msg, trace };
              }),
            );
          } else if (ev.type === "token") {
            const { token } = ev.data as { token: string };
            setMessages((msgs) =>
              msgs.map((msg) =>
                msg.id === assistantId ? { ...msg, content: token } : msg,
              ),
            );
          } else if (ev.type === "final") {
            const f = ev.data as {
              answer: string;
              citations: Citation[];
              abstained: boolean;
              session_id?: string;
              message_id?: number;
            };
            if (f.session_id) setActiveSessionId(f.session_id);

            const sources: SourcePreview[] = (f.citations ?? []).map((c) => ({
              source: c.filename,
              page: c.page ?? "?",
              preview: c.quote ?? "",
            }));

            setMessages((msgs) =>
              msgs.map((msg) =>
                msg.id === assistantId
                  ? {
                      ...msg,
                      messageId: f.message_id ?? msg.messageId,
                      content: f.answer ?? msg.content,
                      citations: f.citations ?? [],
                      sources,
                      abstained: f.abstained ?? false,
                      streaming: false,
                    }
                  : msg,
              ),
            );
          } else if (ev.type === "error") {
            const err = ev.data as { detail?: string };
            setError(err.detail ?? "stream error");
          } else if (ev.type === "done") {
            setMessages((msgs) =>
              msgs.map((msg) =>
                msg.id === assistantId ? { ...msg, streaming: false } : msg,
              ),
            );
          }
        },
      );
    } catch (e) {
      setError(String(e));
      setMessages((msgs) =>
        msgs.map((msg) =>
          msg.id === assistantId
            ? {
                ...msg,
                content: "Error: " + String(e),
                streaming: false,
              }
            : msg,
        ),
      );
    } finally {
      setBusy(false);
      await refreshSessions();
    }
  }

  const showChat = hasReadyDocs || messages.length > 0;

  return (
    <div className="app">
      {error && (
        <div className="banner error" onClick={() => setError(null)}>
          {error}
        </div>
      )}

      <div className={`main${sidebarCollapsed ? " sidebar-collapsed" : ""}`}>
        <aside className="sidebar">
          <BrandHeader
            sidebarCollapsed={sidebarCollapsed}
            onToggleSidebar={() => setSidebarCollapsed((v) => !v)}
          />

          <button
            className="btn"
            onClick={handleNewSession}
            style={{ width: "100%", marginBottom: 4 }}
          >
            ➕  New Chat
          </button>

          <div className="sidebar-section-label"> Conversations</div>
          <SessionList
            sessions={sessions}
            activeId={activeSessionId}
            onSelect={handleSelectSession}
            onDelete={handleDeleteSession}
            onRename={handleRenameSession}
          />

          <hr />

          <div className="sidebar-section-label"> Documents</div>
          <DocumentList
            docs={docs}
            selected={selected}
            onToggle={toggleDoc}
            onDelete={handleDeleteDoc}
            onPickFiles={handlePickFiles}
            pendingCount={pendingFiles.length}
            onProcess={handleProcess}
            processing={processing}
            onClearAll={handleClearAllDocs}
            topK={settings.top_k}
          />

          <AgentSettingsPanel
            settings={settings}
            onChange={(patch) => setSettings((s) => ({ ...s, ...patch }))}
            showActivity={showActivity}
            onToggleActivity={setShowActivity}
            showSources={showSources}
            onToggleSources={setShowSources}
            voiceName={speech.voiceName}
            availableVoices={speech.availableVoices}
            onVoiceChange={speech.setVoiceName}
            onVoicePreview={speech.preview}
            voicePreviewing={speech.previewing}
          />

          {hasReadyDocs && (
            <IndexStatsExpander
              documents={readyDocs.reduce(
                (n, d) => n + (d.page_count ?? 0),
                0,
              )}
              chunks={readyDocs.reduce(
                (n, d) => n + (d.chunk_count ?? 0),
                0,
              )}
              embeddingDimension={384}
              embeddingModel="sentence-transformers/all-MiniLM-L6-v2"
              llmModel="openai/gpt-oss-120b"
            />
          )}

          <div className="sidebar-user">
            <div className="sidebar-user-email" title={user?.email}>
              {user?.email}
            </div>
            <button
              type="button"
              className="btn ghost sm"
              onClick={async () => {
                if (confirm("Log out of Argus?")) {
                  await logout();
                  navigate("/");
                }
              }}
            >
              Log out
            </button>
          </div>
        </aside>

        {showChat ? (
          <section className="chat">
            <ChatHeader version={version} />
            <ChatPanel
              messages={
                showActivity && showSources
                  ? messages
                  : messages.map((m) => ({
                      ...m,
                      trace: showActivity ? m.trace : undefined,
                      sources: showSources ? m.sources : undefined,
                    }))
              }
              onSend={handleSend}
              onImagePick={handleImageQuery}
              busy={busy}
              onFeedback={handleFeedback}
              feedbackFor={(id) => feedback[id]}
              onRegenerate={handleRegenerate}
              onExportMarkdown={handleExportMarkdown}
              onExportPdf={handleExportPdf}
              suggestedQuestions={suggested}
              onPickSuggested={handleSend}
              speech={speech}
            />
          </section>
        ) : (
          <section className="chat">
            <ChatHeader version={version} />
            <HeroEmptyState />
          </section>
        )}
      </div>
    </div>
  );
}