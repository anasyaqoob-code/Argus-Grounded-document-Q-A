/**
 * Public landing page — product page, not a spec sheet.
 *
 * Structure:
 *   1. Hero         — copy on the left, live 3D-tilted answer artifact
 *                     on the right. Mousemove drives a subtle rotation.
 *   2. Contrast     — typical chatbot vs Argus, side by side.
 *   3. Stack        — two columns. Left: heading, four stack cards,
 *                     "See how it works" button. Right: a serif paper
 *                     panel that reveals in stages (title → abstract →
 *                     Figure 1 → Q → A → cite → Table 1 → References).
 *                     Table 1 runs its own idle → running → complete
 *                     animation once the reveal reaches it.
 *   4. How it works — the six-step agentic loop as a horizontal flow.
 *   5. Capabilities — three cards in an asymmetric grid.
 *   6. CTA          — confident, single action.
 *   7. Footer
 *
 * Styles live in ./landing.css, scoped under `lp2-*` and `auth-paper-*`.
 */

import React from "react";
import { Link, useNavigate } from "react-router-dom";

import { ArgusLogo } from "./ArgusLogo";
import { useAuth } from "./AuthContext";
import "./landing.css";

export function LandingPage() {
  React.useEffect(() => {
    document.body.classList.add("lp-scroll");
    return () => {
      document.body.classList.remove("lp-scroll");
    };
  }, []);

  return (
    <div className="lp2">
      <div className="lp2-bg" aria-hidden="true" />
      <LandingNav />
      <LandingHero />
      <LandingContrast />
      <LandingStack />
      <LandingHowItWorks />
      <LandingCapabilities />
      <LandingCTA />
      <LandingFooter />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tilt hook — 3D mousemove rotation for the hero artifact
// ---------------------------------------------------------------------------
function useTilt(maxDeg = 7) {
  const ref = React.useRef<HTMLDivElement | null>(null);

  React.useEffect(() => {
    const el = ref.current;
    if (!el) return;

    if (typeof window === "undefined") return;
    if (window.matchMedia("(hover: none)").matches) return;

    let raf = 0;

    const onMove = (e: MouseEvent) => {
      const rect = el.getBoundingClientRect();
      const cx = rect.left + rect.width / 2;
      const cy = rect.top + rect.height / 2;
      const dx = (e.clientX - cx) / (rect.width / 2);
      const dy = (e.clientY - cy) / (rect.height / 2);
      const rx = Math.max(-1, Math.min(1, -dy)) * maxDeg;
      const ry = Math.max(-1, Math.min(1, dx)) * maxDeg;

      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => {
        el.style.setProperty("--lp2-tilt-x", `${rx.toFixed(2)}deg`);
        el.style.setProperty("--lp2-tilt-y", `${ry.toFixed(2)}deg`);
      });
    };

    const onLeave = () => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => {
        el.style.setProperty("--lp2-tilt-x", "0deg");
        el.style.setProperty("--lp2-tilt-y", "0deg");
      });
    };

    el.addEventListener("mousemove", onMove);
    el.addEventListener("mouseleave", onLeave);
    return () => {
      cancelAnimationFrame(raf);
      el.removeEventListener("mousemove", onMove);
      el.removeEventListener("mouseleave", onLeave);
    };
  }, [maxDeg]);

  return ref;
}

// ---------------------------------------------------------------------------
// Nav
// ---------------------------------------------------------------------------
function LandingNav() {
  const { user, isAdmin, loading } = useAuth();
  const navigate = useNavigate();

  const authed = Boolean(user);

  return (
    <nav className="lp2-nav">
      <div className="lp2-nav-left">
        <Link to="/" className="lp2-nav-brand">
          <ArgusLogo size={28} idSuffix="lp2-nav" />
          <span className="lp2-nav-title">Argus</span>
        </Link>

        {isAdmin && (
          <button
            type="button"
            className="lp2-nav-link lp2-nav-link-admin"
            onClick={() => navigate("/admin")}
          >
            Admin
          </button>
        )}
      </div>

      <div className="lp2-nav-links">
        <a href="#contrast" className="lp2-nav-link">Why</a>
        <a href="#how" className="lp2-nav-link">How</a>
        <a href="#caps" className="lp2-nav-link">Features</a>

        {loading ? null : authed ? (
          <Link to="/app" className="lp2-nav-cta">Open app</Link>
        ) : (
          <Link to="/login" className="lp2-nav-cta">Get started</Link>
        )}
      </div>
    </nav>
  );
}

// ---------------------------------------------------------------------------
// Hero — copy + 3D artifact
// ---------------------------------------------------------------------------
function LandingHero() {
  const tiltRef = useTilt(7);

  return (
    <header className="lp2-hero">
      <div className="lp2-hero-inner">
        <div className="lp2-hero-copy">
          <div className="lp2-eyebrow">
            <span className="lp2-eyebrow-dot" />
            Grounded document Q&amp;A
          </div>

          <h1 className="lp2-title">
            Ask your documents.
            <br />
            Get <span className="lp2-title-accent">cited answers</span>.
          </h1>

          <p className="lp2-sub">
            Argus answers only from the files you upload. Every claim
            points to a specific page. When the evidence runs out, it
            says so — instead of guessing.
          </p>

          <div className="lp2-cta-row">
            <Link to="/login" className="lp2-cta-primary">
              Try Argus
              <span className="lp2-cta-arrow" aria-hidden="true">→</span>
            </Link>
            <a href="#contrast" className="lp2-cta-secondary">
              See the difference
            </a>
          </div>

          <div className="lp2-trust-row">
            <span className="lp2-trust-item">
              <span className="lp2-trust-num">0</span>
              <span className="lp2-trust-label">hallucinated claims</span>
            </span>
            <span className="lp2-trust-sep" aria-hidden="true" />
            <span className="lp2-trust-item">
              <span className="lp2-trust-num">6</span>
              <span className="lp2-trust-label">step agentic loop</span>
            </span>
            <span className="lp2-trust-sep" aria-hidden="true" />
            <span className="lp2-trust-item">
              <span className="lp2-trust-num">100%</span>
              <span className="lp2-trust-label">local embeddings</span>
            </span>
          </div>
        </div>

        <div className="lp2-hero-artifact-wrap">
          <div ref={tiltRef} className="lp2-hero-artifact">
            <div className="lp2-hero-artifact-glow" aria-hidden="true" />

            <div className="lp2-artifact-header">
              <ArgusLogo size={18} idSuffix="lp2-hero-artifact" />
              <span className="lp2-artifact-doc">InvoZone.pdf</span>
              <span className="lp2-artifact-badge">cited</span>
            </div>

            <div className="lp2-artifact-q">
              <span className="lp2-artifact-q-label">Q</span>
              Why should PITB not select the GPU or private-cloud
              product first?
            </div>

            <div className="lp2-artifact-a">
              <p>
                The process must begin with classifying workloads and
                data, defining service-level objectives, and
                benchmarking representative workloads before making
                procurement decisions{" "}
                <span className="lp2-cite">[S2]</span>.
              </p>
            </div>

            <div className="lp2-artifact-pills">
              <span className="lp2-pill">InvoZone.pdf · p.2</span>
              <span className="lp2-pill">InvoZone.pdf · p.5</span>
            </div>

            <div className="lp2-artifact-trace">
              <div className="lp2-trace-header">
                <span className="lp2-trace-pulse" aria-hidden="true" />
                Agent trace · 6 steps
              </div>
              <div className="lp2-trace-rows">
                <TraceRow state="UNDERSTAND" summary="Resolved pronoun + intent" />
                <TraceRow state="SEARCH"     summary="6 chunks retrieved" />
                <TraceRow state="EVALUATE"   summary="Context sufficient" />
                <TraceRow state="VERIFY"     summary="Coverage 83% · passed" />
              </div>
            </div>
          </div>
        </div>
      </div>
    </header>
  );
}

// ---------------------------------------------------------------------------
// Contrast — the killer comparison
// ---------------------------------------------------------------------------
function LandingContrast() {
  return (
    <section className="lp2-section" id="contrast">
      <div className="lp2-section-head">
        <div className="lp2-section-label">The difference</div>
        <h2 className="lp2-section-title">
          Most assistants guess. Argus{" "}
          <span className="lp2-title-accent">shows its work</span>.
        </h2>
      </div>

      <div className="lp2-contrast">
        <div className="lp2-contrast-card lp2-contrast-bad">
          <div className="lp2-contrast-badge">Typical chatbot</div>
          <div className="lp2-contrast-q">
            What does the audit say about our Q3 spend?
          </div>
          <div className="lp2-contrast-a">
            Based on general best practices, audits typically review
            quarterly spending against budgeted targets and highlight
            variances. I'd recommend consulting your finance team for
            specifics.
          </div>
          <div className="lp2-contrast-foot">
            <span className="lp2-contrast-mark lp2-contrast-mark-bad">✕</span>
            No source. No page. Reads like advice, not an answer.
          </div>
        </div>

        <div className="lp2-contrast-card lp2-contrast-good">
          <div className="lp2-contrast-badge">Argus</div>
          <div className="lp2-contrast-q">
            What does the audit say about our Q3 spend?
          </div>
          <div className="lp2-contrast-a">
            The Q3 audit flags $412K in unapproved vendor spend, with the
            largest variance in cloud infrastructure — 38% over the
            pre-approved ceiling <span className="lp2-cite">[S1]</span>.
          </div>
          <div className="lp2-artifact-pills">
            <span className="lp2-pill">audit_Q3.pdf · p.4</span>
          </div>
          <div className="lp2-contrast-foot">
            <span className="lp2-contrast-mark lp2-contrast-mark-good">✓</span>
            Cited to page 4. Numbers from the document. Nothing invented.
          </div>
        </div>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Reveal — fade + slide a block into place once its index is unlocked.
// Reads the current reveal level from a context so each block can decide
// its own state without prop-drilling through every level.
// ---------------------------------------------------------------------------
const RevealContext = React.createContext<number>(-1);

function Reveal({
  index,
  children,
}: {
  index: number;
  children: React.ReactNode;
}) {
  const revealed = React.useContext(RevealContext);
  const shown = revealed >= index;
  return (
    <div
      className={`auth-paper-reveal${shown ? " auth-paper-reveal-shown" : ""}`}
    >
      {children}
    </div>
  );
}

// ---------------------------------------------------------------------------
// useStagedReveal — advance a counter on a timer, one stage per interval.
// Once all stages have fired, hold for HOLD_MS, then reset to -1 and loop.
//
// Timing note: HOLD_MS must be larger than the PipelineTable's full cycle
// (LOOP_START_DELAY_MS + rows.length × STAGE_RUNNING_MS + LOOP_HOLD_MS),
// so the table finishes at least one complete pass before the paper resets.
// With the constants below, the table cycle is ~8.8s and the hold is 9s.
// ---------------------------------------------------------------------------
function useStagedReveal(totalStages: number) {
  const [revealed, setRevealed] = React.useState(-1);

  React.useEffect(() => {
    let cancelled = false;
    const timers: number[] = [];

    const STAGE_MS = 1000;       // one block per second
    const START_DELAY_MS = 600;  // brief pause before the title appears
    const HOLD_MS = 9000;        // long enough for the table to run once

    const runCycle = () => {
      if (cancelled) return;
      setRevealed(-1);

      for (let i = 0; i < totalStages; i++) {
        const t = window.setTimeout(() => {
          if (!cancelled) setRevealed(i);
        }, START_DELAY_MS + i * STAGE_MS);
        timers.push(t);
      }

      const totalMs = START_DELAY_MS + totalStages * STAGE_MS + HOLD_MS;
      const resetT = window.setTimeout(runCycle, totalMs);
      timers.push(resetT);
    };

    runCycle();
    return () => {
      cancelled = true;
      timers.forEach((t) => window.clearTimeout(t));
    };
  }, [totalStages]);

  return revealed;
}

// ---------------------------------------------------------------------------
// Stack — two-column section.
//
// Left column: heading, subheading, four vertical stack cards, and a
// "See how it works" button that anchors to the six-step flow below.
//
// Right column: a serif paper panel — title, abstract, Figure 1 with a
// cited answer, Table 1 with the pipeline trace, and References. The
// paper reveals in eight stages; Table 1 begins its own animation once
// the reveal reaches it.
// ---------------------------------------------------------------------------
function LandingStack() {
  const stack = [
    { k: "Retrieval",  v: "ChromaDB",         n: "cosine similarity" },
    { k: "Embeddings", v: "all-MiniLM-L6-v2", n: "384-dim · CPU" },
    { k: "Generation", v: "gpt-oss-120b",     n: "via Groq" },
    { k: "Backend",    v: "FastAPI + SQLite", n: "single-file DB" },
  ];

  const table = [
    { state: "Understand", obs: "Rewrote into a standalone question", dur: "0.42 s" },
    { state: "Search",     obs: "Retrieved 6 chunks from 2 documents", dur: "0.31 s" },
    { state: "Evaluate",   obs: "Context sufficient — proceeding",     dur: "0.28 s" },
    { state: "Verify",     obs: "Coverage 83% · passed",               dur: "0.51 s" },
  ];

  const TOTAL_STAGES = 8;
  const revealed = useStagedReveal(TOTAL_STAGES);

  return (
    <section className="lp2-section" id="stack">
      <div className="lp2-stack-split">
        {/* ---------------- Left: copy + cards + button ---------------- */}
        <div className="lp2-stack-left">
          <div className="lp2-section-label">The stack</div>
          <h2 className="lp2-stack-title">
            Four pieces. Nothing you have to babysit.
          </h2>

          <div className="lp2-stack-vertical">
            {stack.map((r) => (
              <div key={r.k} className="lp2-stack-item">
                <span className="lp2-stack-k">{r.k}</span>
                <span className="lp2-stack-v">{r.v}</span>
                <span className="lp2-stack-n">{r.n}</span>
              </div>
            ))}
          </div>

          <a href="#how" className="lp2-cta-primary lp2-stack-cta">
            See how it works
            <span className="lp2-cta-arrow" aria-hidden="true">→</span>
          </a>
        </div>

        {/* ---------------- Right: the paper panel ---------------- */}
        <RevealContext.Provider value={revealed}>
          <article className="auth-paper">
            <Reveal index={0}>
              <header className="auth-paper-header">
                <h1 className="auth-paper-title">
                  A grounded document assistant
                </h1>
              </header>
            </Reveal>

            <Reveal index={1}>
              <section className="auth-paper-abstract">
                <p>
                  Argus answers questions from a set of uploaded
                  documents. Every claim is cited to a specific page;
                  when the documents do not support an answer, the
                  system abstains rather than generating one.
                  Retrieval, generation, and verification are performed
                  by an explicit multi-stage pipeline whose trace is
                  preserved with each response.
                </p>
              </section>
            </Reveal>

            <Reveal index={2}>
              <section className="auth-paper-figure">
                <div className="auth-paper-figure-head">
                  <span className="auth-paper-figure-label">Figure 1.</span>
                  <span className="auth-paper-figure-caption">
                    A cited answer to a question about a quarterly audit.
                  </span>
                </div>
              </section>
            </Reveal>

            <Reveal index={3}>
              <div className="auth-paper-question">
                <span className="auth-paper-question-mark">Q</span>
                What does the audit say about our Q3 spend?
              </div>
            </Reveal>

            <Reveal index={4}>
              <blockquote className="auth-paper-answer">
                <p>
                  The Q3 audit flags $412K in unapproved vendor spend,
                  with the largest variance in cloud infrastructure —
                  38% over the pre-approved ceiling.
                  <a
                    href="#ref-1"
                    className="auth-paper-cite"
                    aria-label="Reference 1"
                  >
                    [1]
                  </a>
                </p>
              </blockquote>
            </Reveal>

            <Reveal index={5}>
              <div className="auth-paper-cite-source">
                <a href="#ref-1" className="auth-paper-cite-source-link">
                  [1]&nbsp;&nbsp;audit_Q3.pdf · page 4
                </a>
              </div>
            </Reveal>

            <Reveal index={6}>
              <section className="auth-paper-table">
                <div className="auth-paper-figure-head">
                  <span className="auth-paper-figure-label">Table 1.</span>
                  <span className="auth-paper-figure-caption">
                    The pipeline run that produced Figure 1.
                  </span>
                </div>

                <PipelineTable rows={table} active={revealed >= 6} />
              </section>
            </Reveal>

            <Reveal index={7}>
              <section className="auth-paper-references">
                <h2 className="auth-paper-section-title">References</h2>
                <ol className="auth-paper-ref-list">
                  <li id="ref-1" className="auth-paper-ref-item">
                    audit_Q3.pdf, page 4.
                  </li>
                  <li className="auth-paper-ref-item">
                    Embedding model:{" "}
                    <em>sentence-transformers/all-MiniLM-L6-v2</em>,
                    384 dimensions.
                  </li>
                </ol>
              </section>
            </Reveal>
          </article>
        </RevealContext.Provider>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// PipelineTable — animated table for the paper panel.
//
// Uses a single recursive setTimeout chain rather than pre-scheduled
// timers. Each step schedules the next one after it fires, so the chain
// cannot lose intermediate steps even if the parent re-renders.
//
// State progression: -1 → 0 → 1 → 2 → 3 → rows.length → -1 → ...
//   -1                 all rows idle
//   0..rows.length-1   that row is "running", earlier rows are "complete"
//   rows.length        all rows "complete"
//
// Timing per cycle:
//   LOOP_START_DELAY_MS            700   pause before the cycle begins
//   STAGE_RUNNING_MS              1400   each row stays "running"
//   LOOP_HOLD_MS                  2500   fully-complete hold before reset
//
// Total: 700 + 4×1400 + 2500 = 8800 ms (~8.8 s)
// ---------------------------------------------------------------------------
function PipelineTable({
  rows,
  active,
}: {
  rows: { state: string; obs: string; dur: string }[];
  active: boolean;
}) {
  const [activeStage, setActiveStage] = React.useState(-1);

  React.useEffect(() => {
    if (!active) {
      setActiveStage(-1);
      return;
    }

    let cancelled = false;
    let timeoutId: number | undefined;

    const STAGE_RUNNING_MS = 1400;
    const LOOP_HOLD_MS = 2500;
    const LOOP_START_DELAY_MS = 700;

    // Sequence of activeStage values: idle → each row running → all complete.
    const sequence: number[] = [
      -1,
      ...rows.map((_, i) => i),
      rows.length,
    ];

    let stepIndex = 0;

    const advance = () => {
      if (cancelled) return;

      if (stepIndex >= sequence.length) {
        stepIndex = 0;
      }

      const stage = sequence[stepIndex];
      setActiveStage(stage);

      // How long to wait before the next step in the sequence.
      //   -1  → LOOP_START_DELAY_MS (initial pause)
      //   0..rows.length-1 → STAGE_RUNNING_MS (each row runs)
      //   rows.length → LOOP_HOLD_MS (hold on all-complete)
      let nextDelay = STAGE_RUNNING_MS;
      if (stage === -1) {
        nextDelay = LOOP_START_DELAY_MS;
      } else if (stage === rows.length) {
        nextDelay = LOOP_HOLD_MS;
      }

      stepIndex += 1;
      timeoutId = window.setTimeout(advance, nextDelay);
    };

    // Kick off the cycle after the initial pause.
    timeoutId = window.setTimeout(advance, LOOP_START_DELAY_MS);

    return () => {
      cancelled = true;
      if (timeoutId !== undefined) window.clearTimeout(timeoutId);
    };
  }, [active, rows.length]);

  return (
    <table className="auth-paper-table-el">
      <thead>
        <tr>
          <th className="auth-paper-th-num">#</th>
          <th>Stage</th>
          <th>Observation</th>
          <th className="auth-paper-th-dur">Time</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row, i) => {
          const isComplete = i < activeStage;
          const isRunning = i === activeStage;
          const statusClass = isComplete
            ? "auth-paper-tr-complete"
            : isRunning
              ? "auth-paper-tr-running"
              : "auth-paper-tr-idle";
          return (
            <tr
              key={row.state}
              className={`auth-paper-tr ${statusClass}`}
            >
              <td className="auth-paper-td-num">{i + 1}</td>
              <td className="auth-paper-td-state">{row.state}</td>
              <td className="auth-paper-td-obs">
                {isComplete ? row.obs : isRunning ? "Running…" : "—"}
              </td>
              <td className="auth-paper-td-dur">
                {isComplete ? row.dur : "—"}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

// ---------------------------------------------------------------------------
// How it works — the six-step agentic loop
// ---------------------------------------------------------------------------
function LandingHowItWorks() {
  const steps = [
    { n: "01", name: "Understand", body: "Rewrite the question, resolve pronouns." },
    { n: "02", name: "Decide",     body: "Pick targeted vs. broad retrieval." },
    { n: "03", name: "Search",     body: "Vector retrieval over selected docs." },
    { n: "04", name: "Evaluate",   body: "Is the context sufficient to answer?" },
    { n: "05", name: "Refine",     body: "Rewrite and retry when evidence is thin." },
    { n: "06", name: "Verify",     body: "Check each claim. Abstain if unsupported." },
  ];

  return (
    <section className="lp2-section" id="how">
      <div className="lp2-section-head">
        <div className="lp2-section-label">How it works</div>
        <h2 className="lp2-section-title">Six steps, every question</h2>
        <p className="lp2-section-sub">
          Each stage is a decision, not a pass-through. The trace is
          visible in the app.
        </p>
      </div>

      <div className="lp2-flow">
        {steps.map((s, i) => (
          <React.Fragment key={s.n}>
            <div className="lp2-flow-step">
              <div className="lp2-flow-num">{s.n}</div>
              <div className="lp2-flow-name">{s.name}</div>
              <div className="lp2-flow-body">{s.body}</div>
            </div>
            {i < steps.length - 1 && (
              <div className="lp2-flow-arrow" aria-hidden="true">→</div>
            )}
          </React.Fragment>
        ))}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Capabilities — asymmetric grid, weighted
// ---------------------------------------------------------------------------
function LandingCapabilities() {
  return (
    <section className="lp2-section" id="caps">
      <div className="lp2-section-head">
        <div className="lp2-section-label">Capabilities</div>
        <h2 className="lp2-section-title">What Argus does</h2>
      </div>

      <div className="lp2-caps">
        <div className="lp2-cap lp2-cap-wide">
          <div className="lp2-cap-icon" aria-hidden="true">◉</div>
          <div className="lp2-cap-title">Grounded answers</div>
          <div className="lp2-cap-body">
            Argus only answers from your uploads. If the documents
            don't say it, Argus doesn't either. No general knowledge,
            no "based on typical patterns."
          </div>
        </div>

        <div className="lp2-cap">
          <div className="lp2-cap-icon" aria-hidden="true">◆</div>
          <div className="lp2-cap-title">Cited by page</div>
          <div className="lp2-cap-body">
            Every claim carries an <code>[Sn]</code> marker. Click a
            citation to see the exact chunk it came from.
          </div>
        </div>

        <div className="lp2-cap">
          <div className="lp2-cap-icon" aria-hidden="true">▣</div>
          <div className="lp2-cap-title">Abstention</div>
          <div className="lp2-cap-body">
            When evidence runs out, Argus says so. It never invents an
            answer to seem useful.
          </div>
        </div>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// CTA
// ---------------------------------------------------------------------------
function LandingCTA() {
  return (
    <section className="lp2-cta-section">
      <div className="lp2-cta-card">
        <div className="lp2-cta-glow" aria-hidden="true" />
        <h2 className="lp2-cta-title">
          Upload a document.
          <br />
          Ask it anything.
        </h2>
        <Link to="/login" className="lp2-cta-primary lp2-cta-primary-large">
          Try Argus
          <span className="lp2-cta-arrow" aria-hidden="true">→</span>
        </Link>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Footer
// ---------------------------------------------------------------------------
function LandingFooter() {
  return (
    <footer className="lp2-footer">
      <div className="lp2-footer-brand">
        <ArgusLogo size={20} idSuffix="lp2-foot" />
        <span>Argus</span>
      </div>
      <div className="lp2-footer-meta">
        Grounded document Q&amp;A
      </div>
    </footer>
  );
}

// ---------------------------------------------------------------------------
// Small piece — a single trace row in the hero artifact
// ---------------------------------------------------------------------------
function TraceRow({ state, summary }: { state: string; summary: string }) {
  return (
    <div className="lp2-trace-row">
      <span className="lp2-trace-dot complete" />
      <span className="lp2-trace-state">{state}</span>
      <span className="lp2-trace-msg">{summary}</span>
    </div>
  );
}