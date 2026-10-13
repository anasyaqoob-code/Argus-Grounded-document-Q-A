import React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeRaw from "rehype-raw";

// ---------------------------------------------------------------------------
// Inline Agent Trace — collapsed by default, expands in place
// ---------------------------------------------------------------------------
type TraceStepState = "pending" | "running" | "complete" | "failed";

export interface TraceStep {
  state: string;
  summary: string;
  status?: TraceStepState;
  /** Populated by the backend — not currently rendered but kept on the type */
  duration_ms?: number;
}

function AgentTrace({
  steps,
  totalSteps,
}: {
  steps: TraceStep[];
  totalSteps?: number;
}) {
  const [open, setOpen] = React.useState(false);
  const count = totalSteps ?? steps.length;

  return (
    <div className="argus-trace">
      <button
        type="button"
        className="argus-trace-header"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <span className="argus-trace-pulse" aria-hidden="true" />
        <span>Agent trace · {count} steps</span>
        <span className="argus-trace-toggle">{open ? "▲" : "▼"}</span>
      </button>

      {open && (
        <div className="argus-trace-rows">
          {steps.map((step, i) => (
            <div className="argus-trace-row" key={`${step.state}-${i}`}>
              <span
                className={`argus-trace-dot ${step.status ?? "complete"}`}
                aria-hidden="true"
              />
              <span className="argus-trace-state">
                {step.state.toUpperCase()}
              </span>
              <span className="argus-trace-msg">{step.summary}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Answer card — the visual for one assistant message
// ---------------------------------------------------------------------------
type CitationLite = {
  filename: string;
  page?: number | null;
  document_id?: string;
  chunk_id?: string;
  quote?: string;
  score?: number;
};

type SourcePreview = {
  source: string;
  page: number | string;
  preview: string;
};

interface AnswerCardProps {
  /** Documents that contributed to this answer. Multiple are supported. */
  documentNames?: string[];
  question?: string;
  answer: string;
  citations?: CitationLite[];
  traceSteps?: TraceStep[];
  sources?: SourcePreview[];
  abstained?: boolean;
  streaming?: boolean;
  markdown?: boolean;
  footer?: React.ReactNode;
}

const MAX_VISIBLE_DOCS = 3;

export function AnswerCard({
  documentNames = [],
  question,
  answer,
  traceSteps = [],
  sources = [],
  abstained = false,
  streaming = false,
  markdown = true,
  footer,
}: AnswerCardProps) {
  const [sourcesOpen, setSourcesOpen] = React.useState(false);

  // Dedupe while preserving order
  const uniqueDocs = Array.from(new Set(documentNames));
  const visibleDocs = uniqueDocs.slice(0, MAX_VISIBLE_DOCS);
  const remainder = Math.max(0, uniqueDocs.length - visibleDocs.length);

  // Show a badge only when there's something meaningful to say:
  //   - "abstained" → the model refused to answer
  //   - "streaming" → the answer is still arriving
  //   - "cited"     → the answer has sources we can point to
  //   - null        → plain chat message (greeting, clarification, etc.)
  const badgeLabel = abstained
    ? "abstained"
    : streaming
      ? "streaming"
      : sources.length > 0
        ? "cited"
        : null;
  const badgeClass = abstained ? "argus-badge-abstained" : "";

  return (
    <article className="argus-card">
      {(visibleDocs.length > 0 || badgeLabel) && (
        <header className="argus-card-header">
          {visibleDocs.map((name) => (
            <span className="argus-doc-chip" key={name} title={name}>
              {name}
            </span>
          ))}
          {remainder > 0 && (
            <span
              className="argus-doc-chip argus-doc-chip-more"
              title={uniqueDocs.slice(MAX_VISIBLE_DOCS).join(", ")}
            >
              +{remainder} more
            </span>
          )}
          {badgeLabel && (
            <span className={`argus-badge-cited ${badgeClass}`}>
              {badgeLabel}
            </span>
          )}
        </header>
      )}

      {question && (
        <div className="argus-card-q">
          <span className="argus-card-q-label">Q</span>
          <span>{question}</span>
        </div>
      )}

      <div className="argus-card-a">
        {markdown ? (
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            rehypePlugins={[rehypeRaw]}
            components={{
              p({ children }) {
                return <p>{highlightCitations(children)}</p>;
              },
            }}
          >
            {answer}
          </ReactMarkdown>
        ) : (
          <p>{answer}</p>
        )}
        {streaming && <span className="stream-cursor" />}
      </div>

      {sources.length > 0 && (
        <div className="argus-sources">
          <button
            type="button"
            className="argus-sources-header"
            onClick={() => setSourcesOpen((v) => !v)}
            aria-expanded={sourcesOpen}
          >
            <span className="argus-sources-pulse" aria-hidden="true" />
            <span>Sources</span>
            <span className="argus-sources-count">
              {sources.length} cited
            </span>
            <span className="argus-sources-toggle">
              {sourcesOpen ? "▲" : "▼"}
            </span>
          </button>

          {sourcesOpen && (
            <div className="argus-sources-body">
              {sources.map((s, i) => {
                const preview =
                  s.preview.length > 260
                    ? s.preview.slice(0, 260) + "…"
                    : s.preview;
                return (
                  <div
                    key={`${s.source}-${s.page}-${i}`}
                    className="argus-source-item"
                  >
                    <div className="argus-source-num">[{i + 1}]</div>
                    <div>
                      <div className="argus-source-head">
                        {s.source} · p.{s.page}
                      </div>
                      <div className="argus-source-body">{preview}</div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {traceSteps.length > 0 && <AgentTrace steps={traceSteps} />}

      {footer && <div className="argus-card-footer">{footer}</div>}
    </article>
  );
}

/**
 * Walk text nodes looking for `[S1]` markers and wrap them with the
 * amber `.argus-cite` span. The brackets are stripped from the visible
 * text — the chip styling is what signals "this is a citation" — which
 * matches the original design language. Everything else passes through
 * unchanged.
 *
 * Adjacent markers like `[S1][S2]` are split into two separate spans,
 * each with its own margin (see `.argus-cite` in the stylesheet), so
 * the rendered output is `S1 S2` rather than the concatenated `S1S2`
 * that came from replacing the whole run as one string.
 */
function highlightCitations(children: React.ReactNode): React.ReactNode {
  return React.Children.map(children, (child) => {
    if (typeof child === "string") {
      const parts = child.split(/(\[S\d+\])/g);
      return parts.map((part, i) => {
        const m = /^\[S(\d+)\]$/.exec(part);
        if (m) {
          return (
            <span className="argus-cite" key={i} data-cite={m[1]}>
              S{m[1]}
            </span>
          );
        }
        return <React.Fragment key={i}>{part}</React.Fragment>;
      });
    }
    return child;
  });
}