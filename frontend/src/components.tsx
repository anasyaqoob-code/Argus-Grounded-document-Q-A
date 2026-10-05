/** UI components for Argus — Streamlit-parity. */

import React from "react";
import { createPortal } from "react-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeRaw from "rehype-raw";
import {
  ArgusLogo,
  ExportIcon,
  MicIcon,
  MutedIcon,
  PencilIcon,
  RegenerateIcon,
  SpeakerIcon,
  StopIcon,
  ThumbsDownIcon,
  ThumbsUpIcon,
  TrashIcon,
} from "./ArgusLogo";
import { useSpeech, useVoiceRecorder } from "./useVoice";
import type {
  ActivityStep,
  AgentSettings,
  ChatMessage,
  DocumentInfo,
  SessionInfo,
  SourcePreview,
} from "./types";

/**
 * Fires a transient pulse class the first time `trigger` becomes true.
 */
function useArrivalPulse(trigger: boolean, duration = 1600) {
  const [active, setActive] = React.useState(false);
  const firedRef = React.useRef(false);

  React.useEffect(() => {
    if (!trigger) {
      firedRef.current = false;
      setActive(false);
      return;
    }
    if (firedRef.current) return;
    firedRef.current = true;
    setActive(true);
    const t = window.setTimeout(() => setActive(false), duration);
    return () => window.clearTimeout(t);
  }, [trigger, duration]);

  return active;
}

/**
 * Prepare assistant answer text for markdown rendering.
 */
function prepareAnswerForDisplay(text: string, pulseActive: boolean): string {
  const cleaned = text
    .replace(/[ \t]{2,}/g, " ")
    .replace(/ \n/g, "\n");

  return cleaned.replace(
    /[\[【]S(\d+)(?:\+L(\d+)-L(\d+))?[\]】]/g,
    (_, n, start, end) => {
      const tip = start && end ? ` title="Lines ${start}-${end}"` : "";
      return (
        `<span class="citation-marker${pulseActive ? " pulse" : ""}"` +
        ` data-cite="${n}"${tip}>S${n}</span>`
      );
    },
  );
}

// ===========================================================================
// 3D rotating Argus mark — hero of the inner empty state
// ===========================================================================
export function ArgusLogo3D({
  size = 72,
  duration = 16,
}: {
  size?: number;
  duration?: number;
}) {
  return (
    <div
      className="argus-3d-wrap"
      style={{
        width: size,
        height: size,
        ["--argus-spin-duration" as string]: `${duration}s`,
      }}
      aria-hidden="true"
    >
      <div className="argus-3d-scene">
        <div className="argus-3d-face argus-3d-front">
          <ArgusLogo size={size} idSuffix="3d-front" />
        </div>
        <div className="argus-3d-face argus-3d-back">
          <ArgusLogo size={size} idSuffix="3d-back" />
        </div>
      </div>
    </div>
  );
}

// ===========================================================================
// Multi-answer bubble — image-driven Q/A list
// ===========================================================================
export interface BatchQAItem {
  id: number;
  question: string;
  answer: string;
  citations: SourcePreview[];
  notCovered: boolean;
  streaming: boolean;
}

export function MultiAnswerBubble({
  msg,
  items,
  imageUrl,
  onFeedback,
  feedback,
  onToggleSpeak,
  speaking,
  speakSupported,
  onRegenerate,
  onExportMarkdown,
  onExportPdf,
  canRegenerate,
  busy,
}: {
  msg: ChatMessage;
  items: BatchQAItem[];
  imageUrl?: string | null;
  onFeedback?: (messageId: number, rating: "up" | "down") => void;
  feedback?: "up" | "down";
  onToggleSpeak: (key: string, text: string) => void;
  speaking: boolean;
  speakSupported: boolean;
  onRegenerate?: () => void;
  onExportMarkdown?: () => void;
  onExportPdf?: () => void;
  canRegenerate?: boolean;
  busy?: boolean;
}) {
  const [exportOpen, setExportOpen] = React.useState(false);
  const [popoverPos, setPopoverPos] = React.useState<{
    top: number;
    left: number;
  } | null>(null);
  const exportBtnRef = React.useRef<HTMLButtonElement>(null);
  const exportPanelRef = React.useRef<HTMLDivElement>(null);
  const capturedRef = React.useRef(false);

  const [lightboxOpen, setLightboxOpen] = React.useState(false);

  React.useLayoutEffect(() => {
    if (!exportOpen) {
      capturedRef.current = false;
      setPopoverPos(null);
      return;
    }
    if (capturedRef.current) return;
    const btn = exportBtnRef.current;
    if (!btn) return;
    const rect = btn.getBoundingClientRect();
    capturedRef.current = true;
    setPopoverPos({ top: rect.top - 8, left: rect.right });
  }, [exportOpen]);

  React.useEffect(() => {
    if (!exportOpen) return;
    function onDocClick(e: MouseEvent) {
      const target = e.target as Node;
      if (exportBtnRef.current?.contains(target)) return;
      if (exportPanelRef.current?.contains(target)) return;
      setExportOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setExportOpen(false);
    }
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [exportOpen]);

  // Escape closes the lightbox while it's open.
  React.useEffect(() => {
    if (!lightboxOpen) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setLightboxOpen(false);
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [lightboxOpen]);

  if (items.length === 0) return null;

  const done = !msg.streaming;

  // Flatten the batch to plaintext so TTS reads Q&A pairs in order.
  const spokenText = items
    .map((it) => `Q${it.id}. ${it.question}\n${it.answer}`)
    .join("\n\n");

  return (
    <div className="msg assistant">
      <div className="bubble">
        {imageUrl && (
          <>
            <button
              type="button"
              className="batch-qa-image"
              onClick={() => setLightboxOpen(true)}
              title="Click to enlarge"
            >
              <img src={imageUrl} alt="Uploaded with questions" />
              <span className="batch-qa-image-label">
                <strong>Uploaded image</strong>
                Click to enlarge
              </span>
            </button>

            {lightboxOpen &&
              createPortal(
                <div
                  className="lightbox-backdrop"
                  onClick={() => setLightboxOpen(false)}
                  role="dialog"
                  aria-modal="true"
                  aria-label="Uploaded image"
                >
                  <button
                    type="button"
                    className="lightbox-close"
                    onClick={() => setLightboxOpen(false)}
                    aria-label="Close"
                  >
                    ×
                  </button>
                  <img
                    className="lightbox-image"
                    src={imageUrl}
                    alt="Uploaded with questions"
                    onClick={(e) => e.stopPropagation()}
                  />
                </div>,
                document.body,
              )}
          </>
        )}
        <div className="answer-header">
          <div className="answer-header-mark">
            <ArgusLogo size={22} idSuffix="multi-ah" />
          </div>
          <span className="answer-header-doc">
            {items.length} question{items.length === 1 ? "" : "s"} from image
          </span>
        </div>
        <div className="answer-header-divider" />
        <ol className="batch-qa-list">
          {items.map((item) => (
            <li key={item.id} className="batch-qa-item">
              <div className="batch-qa-question">
                <span className="batch-qa-index">Q{item.id}</span>
                {item.question}
              </div>
              {item.notCovered ? (
                <div className="batch-qa-not-covered">
                  Not covered in the loaded documents.
                </div>
              ) : (
                <>
                  <div
                    className="batch-qa-answer markdown-body"
                    aria-busy={item.streaming}
                  >
                    {item.answer || <span className="stream-cursor" />}
                  </div>
                  {item.citations.length > 0 && (
                    <div className="batch-qa-citations">
                      {item.citations.map((c, i) => (
                        <span
                          key={`${c.source}-${c.page}-${i}`}
                          className="answer-header-doc"
                          title={c.preview}
                        >
                          {c.source} · p.{c.page}
                        </span>
                      ))}
                    </div>
                  )}
                </>
              )}
            </li>
          ))}
        </ol>

        {done && (
          <div className="feedback-row">
            {speakSupported && (
              <button
                type="button"
                className={`feedback-btn speaker-left${
                  speaking ? " speaking" : ""
                }`}
                onClick={() => onToggleSpeak(msg.id, spokenText)}
                title={speaking ? "Stop reading" : "Read aloud"}
                aria-label={speaking ? "Stop reading" : "Read aloud"}
              >
                {speaking ? (
                  <MutedIcon size={14} idSuffix={`spk-${msg.id}`} />
                ) : (
                  <SpeakerIcon size={14} idSuffix={`spk-${msg.id}`} />
                )}
              </button>
            )}

            {canRegenerate && onRegenerate && (
              <button
                type="button"
                className="feedback-btn"
                onClick={onRegenerate}
                disabled={busy}
                title="Regenerate this answer"
                aria-label="Regenerate this answer"
              >
                <RegenerateIcon size={14} idSuffix={`regen-${msg.id}`} />
              </button>
            )}

            {onExportMarkdown && onExportPdf && (
              <button
                ref={exportBtnRef}
                type="button"
                className="feedback-btn"
                onClick={() => setExportOpen((v) => !v)}
                disabled={busy}
                title="Export conversation"
                aria-label="Export conversation"
              >
                <ExportIcon size={14} idSuffix={`export-${msg.id}`} />
              </button>
            )}

            {onFeedback && msg.messageId != null && (
              <FeedbackButtons
                current={feedback}
                onRate={(r) => onFeedback(msg.messageId!, r)}
              />
            )}
          </div>
        )}
      </div>

      {exportOpen &&
        popoverPos &&
        onExportMarkdown &&
        onExportPdf &&
        createPortal(
          <div
            ref={exportPanelRef}
            className="export-popover-portal"
            style={{
              position: "fixed",
              top: popoverPos.top,
              left: popoverPos.left,
              transform: "translate(-100%, -100%)",
            }}
          >
            <div className="popover-title">Download conversation</div>
            <button
              className="btn"
              onClick={() => {
                setExportOpen(false);
                onExportMarkdown();
              }}
            >
              Markdown (.md)
            </button>
            <button
              className="btn"
              onClick={() => {
                setExportOpen(false);
                onExportPdf();
              }}
            >
              PDF (.pdf)
            </button>
          </div>,
          document.body,
        )}
    </div>
  );
}

// ===========================================================================
// Image attach button — sits inside the composer shell
// ===========================================================================
export function ImageAttachButton({
  onPick,
  disabled,
}: {
  onPick: (file: File) => void;
  disabled?: boolean;
}) {
  const ref = React.useRef<HTMLInputElement>(null);
  return (
    <>
      <button
        type="button"
        className="image-attach-btn"
        onClick={() => ref.current?.click()}
        disabled={disabled}
        title="Attach an image with questions"
        aria-label="Attach an image with questions"
      >
        <svg
          width={16}
          height={16}
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth={2}
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
          <circle cx="8.5" cy="8.5" r="1.5" />
          <polyline points="21 15 16 10 5 21" />
        </svg>
      </button>
      <input
        ref={ref}
        type="file"
        accept="image/*"
        hidden
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) onPick(f);
          e.target.value = "";
        }}
      />
    </>
  );
}

// ===========================================================================
// Brand header — includes optional sidebar collapse toggle
// ===========================================================================
export function BrandHeader({
  sidebarCollapsed,
  onToggleSidebar,
}: {
  sidebarCollapsed?: boolean;
  onToggleSidebar?: () => void;
}) {
  return (
    <div className="rag-brand">
      <div className="rag-brand-logo">
        <ArgusLogo size={34} idSuffix="brand" />
      </div>
      <div className="rag-brand-text">
        <div className="rag-brand-title">Argus</div>
        <div className="rag-brand-sub">Document Intelligence</div>
      </div>
      {onToggleSidebar && (
        <button
          type="button"
          className="rag-brand-toggle"
          onClick={onToggleSidebar}
          aria-label={sidebarCollapsed ? "Show sidebar" : "Hide sidebar"}
          title={sidebarCollapsed ? "Show sidebar" : "Hide sidebar"}
        >
          {sidebarCollapsed ? "›" : "‹"}
        </button>
      )}
    </div>
  );
}

// ===========================================================================
// Chat header
// ===========================================================================
export function ChatHeader({ version }: { version?: string }) {
  return (
    <div className="chat-header">
      <div className="chat-header-mark">
        <ArgusLogo size={44} idSuffix="chatheader" />
      </div>
      <div className="chat-header-text">
        <h1>Argus</h1>
        <p className="chat-header-sub">
          Document-grounded question answering with adaptive retrieval,
          context evaluation, and source-verified responses.
        </p>
        {version && <span className="version">v{version}</span>}
      </div>
    </div>
  );
}

// ===========================================================================
// Hero
// ===========================================================================
export function HeroEmptyState() {
  return (
    <div className="hero grid-floor">
      <div className="hero-mark">
        <ArgusLogo size={88} idSuffix="hero" />
      </div>
      <div className="hero-title">Query your documents with confidence.</div>
      <div className="hero-sub">
        Upload PDF or TXT files, run indexing, and ask questions in natural
        language. Every response is grounded in your files, verified against
        evidence, and cited by source page.
      </div>
      <div className="hero-cards">
        <div className="hero-card">
          <span className="hero-card-icon">🧠</span>
          <div className="hero-card-title">Grounded reasoning</div>
          <div className="hero-card-body">
            Understand → Decide → Retrieve → Evaluate → Verify → Answer.
          </div>
        </div>
        <div className="hero-card">
          <span className="hero-card-icon">🎯</span>
          <div className="hero-card-title">Cited sources</div>
          <div className="hero-card-body">
            Every claim is traceable to a specific document and page.
          </div>
        </div>
        <div className="hero-card">
          <span className="hero-card-icon">🛡️</span>
          <div className="hero-card-title">Document-only</div>
          <div className="hero-card-body">
            No general knowledge. Answers are strictly limited to your uploads.
          </div>
        </div>
      </div>
    </div>
  );
}

// ===========================================================================
// Answer header — filename pills only
// ===========================================================================
const MAX_VISIBLE_DOCS = 3;

export function AnswerHeader({ docNames }: { docNames: string[] }) {
  const seen = Array.from(new Set(docNames));

  if (seen.length === 0) return null;

  const visible = seen.slice(0, MAX_VISIBLE_DOCS);
  const remainder = Math.max(0, seen.length - visible.length);

  return (
    <>
      <div className="answer-header">
        <div className="answer-header-mark">
          <ArgusLogo size={22} idSuffix="ah" />
        </div>
        {visible.map((name) => (
          <span key={name} className="answer-header-doc" title={name}>
            {name}
          </span>
        ))}
        {remainder > 0 && (
          <span
            className="answer-header-doc answer-header-more"
            title={seen.slice(MAX_VISIBLE_DOCS).join(", ")}
          >
            +{remainder} more
          </span>
        )}
      </div>
      <div className="answer-header-divider" />
    </>
  );
}

// ===========================================================================
// Activity trace
// ===========================================================================
export function ActivityTrace({
  steps,
  live,
}: {
  steps: ActivityStep[];
  live?: boolean;
}) {
  if (steps.length === 0) return null;

  const label = live
    ? ` Agent Reasoning (in progress · ${steps.length} steps)`
    : ` Agent Reasoning (${steps.length} steps)`;

  return (
    <details className="trace" open={live}>
      <summary>{label}</summary>
      <div className="trace-body">
        {steps.map((s, i) => (
          <div key={`${s.state}-${i}`} className="trace-row">
            <div className={`trace-dot ${s.status}`} />
            <div className="trace-state">{s.state.toUpperCase()}</div>
            <div className="trace-msg">{s.summary}</div>
            {s.duration_ms > 0 && (
              <div className="trace-dur">{s.duration_ms.toFixed(0)} ms</div>
            )}
          </div>
        ))}
      </div>
    </details>
  );
}

// ===========================================================================
// Sources
// ===========================================================================
export function SourceList({
  sources,
  pulseActive,
}: {
  sources: SourcePreview[];
  pulseActive?: boolean;
}) {
  if (sources.length === 0) return null;

  return (
    <details className="sources-block">
      <summary> Sources ({sources.length})</summary>
      <div>
        {sources.map((s, i) => {
          const preview =
            s.preview.length > 400 ? s.preview.slice(0, 400) + "…" : s.preview;
          return (
            <div
              key={`${s.source}-${s.page}-${i}`}
              className={`source-item${pulseActive ? " highlight" : ""}`}
              style={
                pulseActive ? { animationDelay: `${i * 120}ms` } : undefined
              }
            >
              <div className="source-head">
                [{i + 1}] {s.source} — p.{s.page}
              </div>
              <div className="source-body">{preview}</div>
            </div>
          );
        })}
      </div>
    </details>
  );
}

// ===========================================================================
// Feedback — thumbs up/down
// ===========================================================================
export function FeedbackButtons({
  current,
  onRate,
}: {
  current?: "up" | "down";
  onRate: (rating: "up" | "down") => void;
}) {
  return (
    <>
      <button
        type="button"
        className={`feedback-btn${current === "up" ? " active" : ""}`}
        disabled={current === "up"}
        onClick={() => onRate("up")}
        title={current === "up" ? "Marked helpful" : "Mark as helpful"}
        aria-label="Mark as helpful"
      >
        <ThumbsUpIcon size={14} filled={current === "up"} idSuffix="fb-up" />
      </button>
      <button
        type="button"
        className={`feedback-btn${current === "down" ? " active" : ""}`}
        disabled={current === "down"}
        onClick={() => onRate("down")}
        title={current === "down" ? "Marked not helpful" : "Mark as not helpful"}
        aria-label="Mark as not helpful"
      >
        <ThumbsDownIcon
          size={14}
          filled={current === "down"}
          idSuffix="fb-down"
        />
      </button>
    </>
  );
}

// ===========================================================================
// Suggested questions
// ===========================================================================
export function SuggestedQuestions({
  questions,
  onPick,
}: {
  questions: string[];
  onPick: (q: string) => void;
}) {
  if (questions.length === 0) return null;
  return (
    <div className="suggested">
      <div className="suggested-title">💡 Try asking</div>
      <div className="suggested-grid">
        {questions.map((q, i) => (
          <button key={i} className="btn" onClick={() => onPick(q)} title={q}>
            {q}
          </button>
        ))}
      </div>
    </div>
  );
}

// ===========================================================================
// Message bubble
// ===========================================================================
export function MessageBubble({
  msg,
  onFeedback,
  feedback,
  onToggleSpeak,
  speaking,
  speakSupported,
  onRegenerate,
  onExportMarkdown,
  onExportPdf,
  canRegenerate,
  busy,
}: {
  msg: ChatMessage;
  onFeedback?: (messageId: number, rating: "up" | "down") => void;
  feedback?: "up" | "down";
  onToggleSpeak: (key: string, text: string) => void;
  speaking: boolean;
  speakSupported: boolean;
  onRegenerate?: () => void;
  onExportMarkdown?: () => void;
  onExportPdf?: () => void;
  canRegenerate?: boolean;
  busy?: boolean;
}) {
  const isUser = msg.role === "user";
  const [exportOpen, setExportOpen] = React.useState(false);
  const [popoverPos, setPopoverPos] = React.useState<{
    top: number;
    left: number;
  } | null>(null);
  const exportBtnRef = React.useRef<HTMLButtonElement>(null);
  const exportPanelRef = React.useRef<HTMLDivElement>(null);
  const capturedRef = React.useRef(false);

  React.useLayoutEffect(() => {
    if (!exportOpen) {
      capturedRef.current = false;
      setPopoverPos(null);
      return;
    }
    if (capturedRef.current) return;
    const btn = exportBtnRef.current;
    if (!btn) return;
    const rect = btn.getBoundingClientRect();
    capturedRef.current = true;
    setPopoverPos({ top: rect.top - 8, left: rect.right });
  }, [exportOpen]);

  React.useEffect(() => {
    if (!exportOpen) return;
    function onDocClick(e: MouseEvent) {
      const target = e.target as Node;
      if (exportBtnRef.current?.contains(target)) return;
      if (exportPanelRef.current?.contains(target)) return;
      setExportOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setExportOpen(false);
    }
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [exportOpen]);

  const done = !msg.streaming;
  const pulseActive = useArrivalPulse(done && !msg.abstained);

  if (isUser) {
    return (
      <div className="msg user">
        <div className="bubble">
          <div className="content">{msg.content}</div>
        </div>
      </div>
    );
  }

  const docNames: string[] = (msg.sources ?? []).map((s) => s.source);
  const displayText = prepareAnswerForDisplay(msg.content, pulseActive);

  return (
    <div className="msg assistant">
      <div className="bubble">
        <AnswerHeader docNames={docNames} />

        {msg.abstained && (
          <div className="abstain-badge" title={msg.abstain_reason ?? ""}>
            Abstained
          </div>
        )}

        <div className="content markdown-body">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            rehypePlugins={[rehypeRaw]}
          >
            {displayText}
          </ReactMarkdown>
          {msg.streaming && <span className="stream-cursor" />}
        </div>

        {msg.trace && msg.trace.length > 0 && (
          <ActivityTrace steps={msg.trace} live={msg.streaming} />
        )}

        {msg.sources && msg.sources.length > 0 && (
          <SourceList sources={msg.sources} pulseActive={pulseActive} />
        )}

        {done && (
          <div className="feedback-row">
            {speakSupported && (
              <button
                type="button"
                className={`feedback-btn speaker-left${
                  speaking ? " speaking" : ""
                }`}
                onClick={() => onToggleSpeak(msg.id, displayText)}
                title={speaking ? "Stop reading" : "Read aloud"}
                aria-label={speaking ? "Stop reading" : "Read aloud"}
              >
                {speaking ? (
                  <MutedIcon size={14} idSuffix={`spk-${msg.id}`} />
                ) : (
                  <SpeakerIcon size={14} idSuffix={`spk-${msg.id}`} />
                )}
              </button>
            )}

            {canRegenerate && onRegenerate && (
              <button
                type="button"
                className="feedback-btn"
                onClick={onRegenerate}
                disabled={busy}
                title="Regenerate this answer"
                aria-label="Regenerate this answer"
              >
                <RegenerateIcon size={14} idSuffix={`regen-${msg.id}`} />
              </button>
            )}

            {onExportMarkdown && onExportPdf && (
              <button
                ref={exportBtnRef}
                type="button"
                className="feedback-btn"
                onClick={() => setExportOpen((v) => !v)}
                disabled={busy}
                title="Export conversation"
                aria-label="Export conversation"
              >
                <ExportIcon size={14} idSuffix={`export-${msg.id}`} />
              </button>
            )}

            {onFeedback && msg.messageId != null && (
              <FeedbackButtons
                current={feedback}
                onRate={(r) => onFeedback(msg.messageId!, r)}
              />
            )}
          </div>
        )}
      </div>

      {exportOpen &&
        popoverPos &&
        onExportMarkdown &&
        onExportPdf &&
        createPortal(
          <div
            ref={exportPanelRef}
            className="export-popover-portal"
            style={{
              position: "fixed",
              top: popoverPos.top,
              left: popoverPos.left,
              transform: "translate(-100%, -100%)",
            }}
          >
            <div className="popover-title">Download conversation</div>
            <button
              className="btn"
              onClick={() => {
                setExportOpen(false);
                onExportMarkdown();
              }}
            >
              Markdown (.md)
            </button>
            <button
              className="btn"
              onClick={() => {
                setExportOpen(false);
                onExportPdf();
              }}
            >
              PDF (.pdf)
            </button>
          </div>,
          document.body,
        )}
    </div>
  );
}

// ===========================================================================
// Chat panel
// ===========================================================================
export function ChatPanel({
  messages,
  onSend,
  onImagePick,
  busy,
  onFeedback,
  feedbackFor,
  onRegenerate,
  onExportMarkdown,
  onExportPdf,
  suggestedQuestions,
  onPickSuggested,
  speech,
}: {
  messages: ChatMessage[];
  onSend: (text: string) => void;
  onImagePick?: (file: File) => void;
  busy: boolean;
  onFeedback?: (messageId: number, rating: "up" | "down") => void;
  feedbackFor?: (messageId: number) => "up" | "down" | undefined;
  onRegenerate?: () => void;
  onExportMarkdown?: () => void;
  onExportPdf?: () => void;
  suggestedQuestions?: string[];
  onPickSuggested?: (q: string) => void;
  speech: ReturnType<typeof useSpeech>;
}) {
  const [text, setText] = React.useState("");
  const bottomRef = React.useRef<HTMLDivElement>(null);

  const voice = useVoiceRecorder(
    (transcript) => {
      setText(transcript);
    },
    (partial) => {
      setText(partial);
    },
  );

  React.useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const q = text.trim();
    if (!q || busy) return;

    if (voice.state === "recording" || voice.state === "requesting") {
      voice.stop();
    }

    setText("");
    onSend(q);
  }

  const showSuggested =
    messages.length === 0 &&
    suggestedQuestions &&
    suggestedQuestions.length > 0;

  return (
    <>
      <div className="messages">
        {showSuggested && onPickSuggested && (
          <>
            <SuggestedQuestions
              questions={suggestedQuestions!}
              onPick={(q) => {
                setText("");
                onPickSuggested(q);
              }}
            />
            <div className="empty-empty-bottom">
              <div className="empty-mark-compact">
                <ArgusLogo3D size={140} duration={20} />
              </div>
              <div className="empty-title-block">
                <div className="empty-title">
                  Ask a question about your uploaded documents.
                </div>
                <div className="empty-sub">
                  Argus will abstain when evidence is weak.
                </div>
              </div>
            </div>
          </>
        )}

        {messages.length === 0 && !showSuggested && (
          <div className="empty grid-floor">
            <div className="empty-mark">
              <ArgusLogo3D size={180} duration={16} />
            </div>
            <div className="empty-title">
              Ask a question about your uploaded documents.
            </div>
            <div className="empty-sub">
              Argus will abstain when evidence is weak.
            </div>
          </div>
        )}

        {messages.map((m, i) => {
          // Image batch — rendered inline at the position the image
          // was uploaded. The batch is a ChatMessage variant with a
          // `batch` field instead of normal content.
          if (m.batch) {
            const isLastBatch = i === messages.length - 1;
            return (
              <MultiAnswerBubble
                key={m.id}
                msg={m}
                items={m.batch.items}
                imageUrl={m.batch.imageUrl}
                onFeedback={onFeedback}
                feedback={
                  m.messageId != null ? feedbackFor?.(m.messageId) : undefined
                }
                onToggleSpeak={speech.toggle}
                speaking={speech.speakingKey === m.id}
                speakSupported={speech.supported}
                onRegenerate={onRegenerate}
                onExportMarkdown={onExportMarkdown}
                onExportPdf={onExportPdf}
                canRegenerate={isLastBatch && !m.streaming}
                busy={busy}
              />
            );
          }

          const isLast = i === messages.length - 1;
          const canRegen = isLast && m.role === "assistant" && !m.streaming;
          return (
            <MessageBubble
              key={m.id}
              msg={m}
              onFeedback={onFeedback}
              feedback={
                m.messageId != null ? feedbackFor?.(m.messageId) : undefined
              }
              onToggleSpeak={speech.toggle}
              speaking={speech.speakingKey === m.id}
              speakSupported={speech.supported}
              onRegenerate={onRegenerate}
              onExportMarkdown={onExportMarkdown}
              onExportPdf={onExportPdf}
              canRegenerate={canRegen}
              busy={busy}
            />
          );
        })}

        <div ref={bottomRef} />
      </div>

      <form className="composer" onSubmit={submit}>
        <div className="composer-shell">
          {onImagePick && (
            <ImageAttachButton onPick={onImagePick} disabled={busy} />
          )}
          <input
            type="text"
            placeholder={
              voice.state === "transcribing"
                ? "Transcribing…"
                : voice.state === "recording"
                  ? "Listening…"
                  : "Ask a question about your documents…"
            }
            value={text}
            onChange={(e) => setText(e.target.value)}
            disabled={busy || voice.state === "transcribing"}
          />

          <button
            type="button"
            className={`mic-inside ${voice.state}`}
            onClick={() => {
              if (voice.state === "recording") {
                voice.stop();
              } else {
                setText("");
                voice.start();
              }
            }}
            disabled={
              busy ||
              voice.state === "transcribing" ||
              voice.state === "requesting"
            }
            title={
              voice.state === "recording"
                ? "Stop recording"
                : voice.state === "transcribing"
                  ? "Transcribing…"
                  : voice.liveCapable
                    ? "Speak your question (live)"
                    : "Speak your question"
            }
            aria-label="Voice input"
          >
            {voice.state === "recording" ? (
              <StopIcon size={16} idSuffix="mic-stop" />
            ) : voice.state === "transcribing" ? (
              <span className="mic-spinner" />
            ) : (
              <MicIcon size={16} idSuffix="mic-idle" />
            )}
          </button>
        </div>

        <button
          className="btn primary"
          type="submit"
          disabled={busy || !text.trim()}
        >
          {busy ? "…" : "Send"}
        </button>
      </form>

      {voice.error && (
        <div className="voice-error" onClick={() => voice.cancel()}>
          {voice.error}
        </div>
      )}
    </>
  );
}

// ===========================================================================
// Document picker
// ===========================================================================
export function DocumentList({
  docs,
  selected,
  onToggle,
  onDelete,
  onPickFiles,
  pendingCount,
  onProcess,
  processing,
  onClearAll,
  topK = 4,
}: {
  docs: DocumentInfo[];
  selected: Set<string>;
  onToggle: (id: string) => void;
  onDelete: (id: string) => void;
  onPickFiles: (files: File[]) => void;
  pendingCount: number;
  onProcess: () => void;
  processing: boolean;
  onClearAll: () => void;
  topK?: number;
}) {
  const inputRef = React.useRef<HTMLInputElement>(null);

  const readyDocs = docs.filter((d) => d.status === "ready");
  const selectedCount = selected.size > 0 ? selected.size : readyDocs.length;
  const baseK = Math.max(1, topK);
  const effectiveK = Math.min(baseK * Math.max(1, selectedCount), 12);

  return (
    <>
      <button
        className="btn"
        onClick={() => inputRef.current?.click()}
        disabled={processing}
        style={{ width: "100%", marginBottom: "6px" }}
      >
         Upload PDF or TXT
      </button>
      <input
        ref={inputRef}
        type="file"
        accept=".pdf,.txt,.md"
        multiple
        hidden
        onChange={(e) => {
          const files = Array.from(e.target.files ?? []);
          if (files.length) onPickFiles(files);
          e.target.value = "";
        }}
      />

      {pendingCount > 0 && (
        <button
          className="btn primary"
          onClick={onProcess}
          disabled={processing}
          style={{ width: "100%", marginBottom: "8px" }}
        >
          {processing
            ? "Processing…"
            : `◉  Process Documents (${pendingCount})`}
        </button>
      )}

      {docs.length === 0 && (
        <div className="empty-doclist">
          No documents yet. Upload a .txt, .md, or .pdf file.
        </div>
      )}

      {docs.length > 0 && (
        <>
          <div
            className="sidebar-section-label"
            style={{
              marginTop: 8,
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
            }}
          >
            <span>Loaded</span>
            <span style={{ color: "var(--muted)", fontWeight: 400 }}>
              {docs.length}
            </span>
          </div>
          <ul className="loaded-list">
            {docs.map((d) => (
              <li key={d.document_id} className="loaded-item">
                <span className="loaded-file-icon">📄</span>
                <span className="loaded-file-name" title={d.filename}>
                  {d.filename}
                </span>
                <button
                  className="loaded-del"
                  title="Remove from index"
                  onClick={() => onDelete(d.document_id)}
                >
                  ×
                </button>
              </li>
            ))}
          </ul>

          {readyDocs.length > 1 && (
            <>
              <div className="sidebar-section-label" style={{ marginTop: 10 }}>
                Search in
              </div>
              <div className="chip-selector">
                {[...readyDocs]
                  .sort((a, b) => {
                    const aActive = selected.has(a.document_id) ? 0 : 1;
                    const bActive = selected.has(b.document_id) ? 0 : 1;
                    return aActive - bActive;
                  })
                  .map((d) => {
                    const active = selected.has(d.document_id);
                    return (
                      <button
                        key={d.document_id}
                        type="button"
                        className={`doc-chip ${active ? "active" : ""}`}
                        onClick={() => onToggle(d.document_id)}
                        title={
                          active
                            ? "Click to exclude from retrieval"
                            : "Click to include in retrieval"
                        }
                      >
                        <span className="doc-chip-label">{d.filename}</span>
                        {active && <span className="doc-chip-x">×</span>}
                      </button>
                    );
                  })}
              </div>
              <div className="effective-k-caption">
                 Searching <strong>{selectedCount}</strong> of{" "}
                <strong>{readyDocs.length}</strong> docs · Effective K:{" "}
                <strong>{effectiveK}</strong>
              </div>
            </>
          )}

          {readyDocs.length === 1 && (
            <div className="effective-k-caption">
              1 document indexed: <strong>{readyDocs[0].filename}</strong>
            </div>
          )}

          <button
            className="btn ghost sm"
            onClick={onClearAll}
            title="Delete every indexed document"
            style={{ marginTop: "8px", width: "100%" }}
          >
             Clear all indexed documents
          </button>
        </>
      )}
    </>
  );
}

// ===========================================================================
// Session list
// ===========================================================================
export function SessionList({
  sessions,
  activeId,
  onSelect,
  onDelete,
  onRename,
}: {
  sessions: SessionInfo[];
  activeId?: string;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
  onRename?: (id: string, title: string) => void;
}) {
  const visible = sessions.filter((s) => (s.message_count ?? 0) > 0);
  const [editingId, setEditingId] = React.useState<string | null>(null);
  const [draft, setDraft] = React.useState("");
  const inputRef = React.useRef<HTMLInputElement>(null);

  React.useEffect(() => {
    if (editingId) {
      requestAnimationFrame(() => {
        inputRef.current?.focus();
        inputRef.current?.select();
      });
    }
  }, [editingId]);

  function beginEdit(id: string, currentTitle: string) {
    if (!onRename) return;
    setEditingId(id);
    setDraft(currentTitle || "");
  }

  function commitEdit() {
    if (!editingId) return;
    const trimmed = draft.trim();
    if (trimmed && onRename) {
      onRename(editingId, trimmed);
    }
    setEditingId(null);
    setDraft("");
  }

  function cancelEdit() {
    setEditingId(null);
    setDraft("");
  }

  if (visible.length === 0) {
    return (
      <div className="empty-doclist" style={{ fontSize: "0.75rem" }}>
        No conversations yet.
      </div>
    );
  }

  return (
    <ul className="session-list">
      {visible.map((s) => {
        const isEditing = editingId === s.session_id;
        return (
          <li
            key={s.session_id}
            className={`session-item ${
              s.session_id === activeId ? "active" : ""
            }`}
            onClick={() => {
              if (!isEditing) onSelect(s.session_id);
            }}
          >
            {isEditing ? (
              <input
                ref={inputRef}
                className="session-title-input"
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onBlur={commitEdit}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    commitEdit();
                  } else if (e.key === "Escape") {
                    e.preventDefault();
                    cancelEdit();
                  }
                }}
                onClick={(e) => e.stopPropagation()}
              />
            ) : (
              <span className="session-title" title={s.title || "New Chat"}>
                {s.title || "New Chat"}
              </span>
            )}

            {!isEditing && (
              <div className="session-actions">
                {onRename && (
                  <button
                    type="button"
                    className="session-action-btn"
                    title="Rename conversation"
                    onClick={(e) => {
                      e.stopPropagation();
                      beginEdit(s.session_id, s.title || "");
                    }}
                  >
                    <PencilIcon size={13} />
                  </button>
                )}
                <button
                  type="button"
                  className="session-action-btn session-del"
                  title="Delete conversation"
                  onClick={(e) => {
                    e.stopPropagation();
                    onDelete(s.session_id);
                  }}
                >
                  <TrashIcon size={13} />
                </button>
              </div>
            )}
          </li>
        );
      })}
    </ul>
  );
}

// ===========================================================================
// Agent settings panel
// ===========================================================================
export function AgentSettingsPanel({
  settings,
  onChange,
  showActivity,
  onToggleActivity,
  showSources,
  onToggleSources,
  voiceName,
  availableVoices,
  onVoiceChange,
  onVoicePreview,
  voicePreviewing,
}: {
  settings: AgentSettings;
  onChange: (next: Partial<AgentSettings>) => void;
  showActivity: boolean;
  onToggleActivity: (v: boolean) => void;
  showSources: boolean;
  onToggleSources: (v: boolean) => void;
  voiceName: string | null;
  availableVoices: { name: string; lang: string }[];
  onVoiceChange: (name: string) => void;
  onVoicePreview: () => void;
  voicePreviewing: boolean;
}) {
  return (
    <>
      <details className="settings-expander">
        <summary>Agent Settings</summary>
        <div className="settings-body">
          <Slider
            label={`Top-K  ·  ${settings.top_k}`}
            min={1}
            max={10}
            step={1}
            value={settings.top_k}
            onChange={(v) => onChange({ top_k: v })}
          />
          <Slider
            label={`Similarity threshold  ·  ${settings.similarity_threshold.toFixed(2)}`}
            min={0}
            max={0.5}
            step={0.01}
            value={settings.similarity_threshold}
            onChange={(v) => onChange({ similarity_threshold: v })}
          />
          <Slider
            label={`Per-doc relevance floor  ·  ${settings.doc_relevance_floor.toFixed(2)}`}
            min={0}
            max={0.5}
            step={0.01}
            value={settings.doc_relevance_floor}
            onChange={(v) => onChange({ doc_relevance_floor: v })}
          />
          <Slider
            label={`Max retrieval attempts  ·  ${settings.max_retrieval_attempts}`}
            min={1}
            max={3}
            step={1}
            value={settings.max_retrieval_attempts}
            onChange={(v) => onChange({ max_retrieval_attempts: v })}
          />
          <Slider
            label={`Memory message limit  ·  ${settings.memory_message_limit}`}
            min={0}
            max={20}
            step={1}
            value={settings.memory_message_limit}
            onChange={(v) => onChange({ memory_message_limit: v })}
          />
          <Slider
            label={`Chunk size  ·  ${settings.chunk_size}`}
            min={200}
            max={2000}
            step={100}
            value={settings.chunk_size}
            onChange={(v) => onChange({ chunk_size: v })}
          />
          <Slider
            label={`Chunk overlap  ·  ${settings.chunk_overlap}`}
            min={0}
            max={500}
            step={50}
            value={settings.chunk_overlap}
            onChange={(v) => onChange({ chunk_overlap: v })}
          />

          <Checkbox
            label="Query rewriting"
            checked={settings.query_rewriting}
            onChange={(v) => onChange({ query_rewriting: v })}
          />
          <Checkbox
            label="Answer verification"
            checked={settings.answer_verification}
            onChange={(v) => onChange({ answer_verification: v })}
          />
          <Checkbox
            label="Source citations"
            checked={settings.source_citations}
            onChange={(v) => onChange({ source_citations: v })}
          />

          {availableVoices.length > 0 && (
            <div className="voice-picker">
              <label className="slider-label">Read-aloud voice</label>
              <div className="voice-picker-row">
                <select
                  className="voice-select"
                  value={voiceName ?? availableVoices[0]?.name ?? ""}
                  onChange={(e) => onVoiceChange(e.target.value)}
                >
                  {availableVoices.map((v) => (
                    <option key={v.name} value={v.name}>
                      {v.name} — {v.lang}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  className={`btn ghost sm voice-preview-btn${
                    voicePreviewing ? " active" : ""
                  }`}
                  onClick={onVoicePreview}
                  title={voicePreviewing ? "Stop preview" : "Play a sample"}
                  aria-label={
                    voicePreviewing ? "Stop preview" : "Play a sample"
                  }
                >
                  {voicePreviewing ? "◼" : "▶"}
                </button>
              </div>
            </div>
          )}
        </div>
      </details>

      <div className="sidebar-checkbox-row">
        <Checkbox
          label=" Show agent activity"
          checked={showActivity}
          onChange={onToggleActivity}
        />
        <Checkbox
          label=" Show sources"
          checked={showSources}
          onChange={onToggleSources}
        />
      </div>
    </>
  );
}

function Slider({
  label,
  min,
  max,
  step,
  value,
  onChange,
}: {
  label: string;
  min: number;
  max: number;
  step: number;
  value: number;
  onChange: (v: number) => void;
}) {
  return (
    <div className="slider-row">
      <label className="slider-label">{label}</label>
      <input
        type="range"
        className="slider"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
      />
    </div>
  );
}

function Checkbox({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="checkbox-row">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span>{label}</span>
    </label>
  );
}

// ===========================================================================
// Index stats
// ===========================================================================
export function IndexStatsExpander({
  documents,
  chunks,
  embeddingDimension,
  llmModel,
  embeddingModel,
}: {
  documents: number;
  chunks: number;
  embeddingDimension: number;
  llmModel: string;
  embeddingModel: string;
}) {
  return (
    <details className="settings-expander">
      <summary>  Index Stats</summary>
      <div className="settings-body">
        <div className="metric-grid">
          <div className="metric">
            <div className="metric-value">{documents}</div>
            <div className="metric-label">Pages</div>
          </div>
          <div className="metric">
            <div className="metric-value">{chunks}</div>
            <div className="metric-label">Chunks</div>
          </div>
        </div>
        <div className="stat-caption">
          Embed dim: <code>{embeddingDimension}</code>
        </div>
        <div className="stat-caption">
          Embed: <code>{embeddingModel}</code>
        </div>
        <div className="stat-caption">
          LLM: <code>{llmModel}</code>
        </div>
      </div>
    </details>
  );
}

export { ArgusLogo, PencilIcon, TrashIcon };