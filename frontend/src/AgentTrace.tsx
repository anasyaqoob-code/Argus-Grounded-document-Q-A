import { useState } from "react";

export type TraceStepState = "pending" | "running" | "complete" | "failed";

export interface TraceStep {
  /** Uppercase label rendered in monospace, e.g. "UNDERSTAND" */
  state: string;
  /** Human-readable summary to the right of the label */
  summary: string;
  /** Optional — defaults to "complete" if a summary is present */
  status?: TraceStepState;
}

interface AgentTraceProps {
  steps: TraceStep[];
  /** Total number of steps, if greater than the ones you're rendering */
  totalSteps?: number;
  /** Optional metrics to show in the header, e.g. "coverage 83% · passed" */
  summary?: string;
  /** Start expanded? Landing uses true; chat uses false */
  defaultOpen?: boolean;
}

export function AgentTrace({
  steps,
  totalSteps,
  summary,
  defaultOpen = false,
}: AgentTraceProps) {
  const [open, setOpen] = useState(defaultOpen);
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
        {summary && (
          <span style={{ marginLeft: 8, color: "var(--argus-text-tertiary)" }}>
            {summary}
          </span>
        )}
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
              <span className="argus-trace-state">{step.state}</span>
              <span className="argus-trace-msg">{step.summary}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
