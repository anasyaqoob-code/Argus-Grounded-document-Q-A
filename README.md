# Argus

Grounded document Q&A with explicit safety rails.

Argus is an agentic retrieval-augmented generation system that answers questions strictly from uploaded documents — with page-level citations, verification, and a full reasoning trace. It refuses to answer when evidence is weak, validates every citation against its source, and isolates every request from every other request.

## Table of contents

- [What it does](#what-it-does)
- [The 10-stage pipeline](#the-10-stage-pipeline)
- [Safety rails](#safety-rails)
- [Architecture](#architecture)
- [Project structure](#project-structure)
- [Tech stack](#tech-stack)
- [Data model](#data-model)
- [API surface](#api-surface)
- [Authentication](#authentication)
- [Frontend architecture](#frontend-architecture)
- [Mobile layout](#mobile-layout)
- [Running it](#running-it)
- [Environment](#environment)
- [Deploying](#deploying)
- [Using it](#using-it)
- [Testing](#testing)
- [Design notes](#design-notes)

## What it does

Argus is a document-grounded Q&A system. Upload PDFs, TXTs, or MDs. Ask questions. Get answers only from those files, with inline citations pointing to specific pages. When the evidence runs out, it abstains instead of guessing.

Core capabilities:

- **Multi-document retrieval with per-doc sweeps.** When two or more documents are selected, retrieval sweeps each doc individually so no single document dominates the top-k. Critical for comparison and cross-doc questions.
- **Grounding by construction.** The generation prompt contains only retrieved chunks. The LLM is explicitly forbidden from using general knowledge; if the context doesn't answer the question, it returns the abstain message.
- **Inline citations with validation.** Every factual claim carries a `[Sn]` marker that maps to a specific chunk. Citations that don't resolve to a real chunk are dropped before the response is sent.
- **Full reasoning trace.** The Agent Reasoning expander shows every stage, its duration, and its metadata — the same data that gets persisted to SQLite for session reload.
- **Session persistence.** Messages, citations, source previews, and the full activity trace are stored. Reloading a session reproduces the original experience — pills, trace, sources — not a stripped version.
- **Multi-user with per-user isolation.** bcrypt passwords, HS256 JWT in an HTTP-only cookie, Google OAuth, password reset via email, every read and write scoped by `user_id`.
- **Admin analytics.** Signups, logins, sessions over time. Per-query RAG evaluation metrics (faithfulness, precision, verification pass rate, abstention rate, latency, composite). Metrics live in a table decoupled from messages so they survive document deletion.
- **Image Q&A.** Upload a photo with questions. Groq Vision extracts each question; Argus answers each from the loaded documents; the whole batch persists as one bubble.
- **Voice in / voice out.** Web Speech API first, Groq Whisper fallback. Text-to-speech with markdown-stripping and natural pause insertion.
- **Exports.** Markdown and PDF, with citations and the agent trace preserved.
- **Mobile-first workspace.** Below 768px the sidebar becomes an off-canvas drawer, the chat header collapses, and the composer pins above the home indicator. Safe-area aware.

## The 10-stage pipeline

Every question runs through a deterministic agent loop. No tool-calling, no hidden LLM orchestration — a plain Python controller with one LLM call per stage.

```text
UNDERSTAND  →  resolve pronouns, rewrite into a standalone question
DECIDE      →  pick response format + broad vs targeted retrieval
PLAN        →  build an optimized search query
SEARCH      →  ChromaDB vector search with per-doc filtering
OBSERVE     →  assemble the retrieved context
EVALUATE    →  judge whether the context answers the question
               ⚡ skipped when ≥4 chunks retrieved
REFINE      →  rewrite the query if EVALUATE fails
GENERATE    →  stream a grounded answer with inline [Sn] citation IDs
VERIFY      →  validate each citation against its source chunk
               ⚡ skipped when coverage ≥50%
FINAL       →  emit answer + citations + full activity trace
```

Two stages short-circuit on strong signals to save LLM tokens without sacrificing correctness. Both short-circuits still appear in the trace with `skipped_llm: true` metadata so the audit trail stays complete.

**Gates.** Before the pipeline runs, five regex gates intercept common cases without any retrieval:

- Greetings (`hi`, `hello`, `good morning`) → canned reply
- Capability questions (`what can you do`, `who are you`) → canned reply
- Thanks (`thanks`, `nice`, `perfect`) → canned reply
- Overview queries (`summarize this pdf`, `what's in these documents`) → per-document summarization path
- Past-session queries (`what did we discuss earlier`) → cross-session summary recall

Each gate is a regex match, so it costs nothing and doesn't touch the LLM.

## Safety rails

Each finding maps to one module. Every one is load-bearing — remove it and behavior regresses in a specific, testable way.

| # | Finding | Module | What it prevents |
|---|---|---|---|
| 1 | Filter-at-DB | `backend/app/retrieval.py` | `top_k` wasted on unselected docs. Filters pushed into the Chroma query, not applied after ranking. |
| 2 | Abstention | `backend/app/verification.py` | Answering when evidence is weak. Returns a grounded refusal instead of hallucinating. |
| 3 | Citation validation | `backend/app/citations.py` | Citations pointing to chunks that don't exist or whose quotes aren't in the source. |
| 4 | Upload limits | `backend/app/validation.py` | Oversized files, unsupported types, encrypted PDFs, page bombs. |
| 5 | Per-request settings | `backend/app/agent_state.py` | Global `Settings` mutation under concurrent requests. Each request gets an immutable snapshot. |
| 6 | Rate-limit handling | `backend/app/rag_engine.py` | Mid-stream Groq 429s crashing the SSE connection. Surfaces a clean, user-facing message. |
| 7 | Fail-open on final verify | `backend/app/rag_engine.py` | A well-cited answer being overwritten with the abstain message on the last retry. |
| 8 | Filename normalization | `backend/app/rag_engine.py` | "No documents selected" when chip names, DB filenames, and chunk metadata differ by case or path prefix. |
| 9 | Full metadata persistence | `backend/app/rag_engine.py` | Pills, reasoning trace, and sources vanishing when reloading a past session. |
| 10 | Per-user isolation | `backend/app/storage.py` | Session and document cross-talk between users. Every read/write scoped by `user_id`. |

Beyond the numbered rails, five architectural decisions do heavy lifting:

- **Durable metrics.** `query_metrics` is a separate table from `messages`. Every eval metric (faithfulness, precision, latency, composite) is written there so deleting a document or purging a session doesn't erase the analytics. `recent_queries` LEFT JOINs on the message so a deleted message still shows its metric with a `(question no longer available)` placeholder.
- **Strict threshold.** `VectorStore.query()` applies `score_threshold` before returning. If every result is below the threshold, it returns `[]`. No silent fallback to unfiltered results.
- **Model routing.** Structured-output tasks (understand, evaluate, refine, verify, suggest, overview) route to `gpt-oss-20b`. Only generation routes to `gpt-oss-120b`. Roughly halves the per-query token bill.
- **Content-token grounding.** `verification.py::estimate_grounding` measures coverage over content tokens only — stopwords and punctuation are stripped before the intersection. Grounded paraphrased answers score high; hallucinated answers (whose content words aren't in the source) still score low.
- **Scroll anchored to the user, not the assistant.** On mobile, when the assistant's answer exceeds the viewport, the auto-scroll targets the last user bubble at the top of the visible area, not the bottom of the message list. The user can re-read their question while reading the answer. Desktop behaviour is unchanged (there's enough vertical room for both to stay in view).

## Architecture

```text
┌─────────────────────────────────────────────────────────────────┐
│ Browser                                                         │
│ React + Vite + TypeScript                                       │
│ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────┐  │
│ │ Landing  │ │ Login    │ │ Forgot   │ │ Reset    │ │ Google │  │
│ │          │ │ /Sign up │ │ Password │ │ Password │ │ Call   │  │
│ └──────────┘ └──────────┘ └──────────┘ └──────────┘ └────────┘  │
│ ┌──────────┐ ┌──────────┐                                       │
│ │ App      │ │ Admin    │                                       │
│ └──────────┘ └──────────┘                                       │
│                                                                 │
│ fetch + SSE  (HTTP-only cookie auth)                            │
└───────────────────────────┼─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│ FastAPI (uvicorn)                                               │
│ ┌───────────────────────────────────────────────────────────┐   │
│ │ main.py — routes, auth deps, SSE serialization            │   │
│ └───────────────────────────────────────────────────────────┘   │
│                            │                                    │
│  ├──► auth.py            (JWT, bcrypt)                          │
│  ├──► password_reset.py  (Resend email + tokens)                │
│  ├──► google_auth.py     (OAuth 2.0 authorization code)         │
│  ├──► email.py           (Resend wrapper)                       │
│  ├──► storage.py         (SQLite)                               │
│  ├──► validation.py      (upload checks)                        │
│  ├──► vision.py          (Groq Qwen 3.8)                        │
│  ├──► voice.py           (Groq Whisper)                         │
│  │                                                              │
│  └──► rag_engine.AgenticRAGService                              │
│       │                                                         │
│       ├──► agent_state.py   (immutable per-request)             │
│       ├──► retrieval.py     (Chroma + filter-at-DB)             │
│       ├──► citations.py     ([Sn] protocol)                     │
│       ├──► verification.py  (3-signal verdict)                  │
│       ├──► routing.py       (task → model)                      │
│       ├──► memory.py        (history formatting)                │
│       ├──► models.py        (domain dataclasses)                │
│       └──► config.py        (Pydantic settings)                 │
│                                                                 │
│  LLM calls ──► Groq                                             │
│    • openai/gpt-oss-120b   (generation)                         │
│    • openai/gpt-oss-20b    (structured tasks)                   │
│    • qwen/qwen3.8-27b      (vision)                             │
│    • whisper-large-v3-turbo (voice)                             │
│                                                                 │
│  Embeddings  ──► HuggingFace (all-MiniLM-L6-v2, CPU)            │
│  Vector store──► ChromaDB (persistent, cosine)                  │
│  Persistence ──► SQLite (app.db)                                │
│  Email       ──► Resend                                         │
└─────────────────────────────────────────────────────────────────┘
```

## Project structure

```text
Argus/
│
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI routes, auth deps, SSE serialization
│   │   ├── config.py          # Pydantic BaseSettings — env-driven
│   │   ├── agent_state.py     # ★ Immutable per-request AgentSettings + state names
│   │   ├── auth.py            # bcrypt + JWT (HS256, 7-day expiry)
│   │   ├── password_reset.py  # Forgot/reset endpoints
│   │   ├── google_auth.py     # Google OAuth start + callback
│   │   ├── email.py           # Resend wrapper
│   │   ├── schemas.py         # Pydantic request/response models
│   │   ├── models.py          # Domain dataclasses
│   │   ├── rag_engine.py      # ★ 10-stage pipeline + persistence
│   │   ├── retrieval.py       # ★ Chroma wrapper, filter-at-DB, broad mode
│   │   ├── citations.py       # ★ [Sn] parsing + validation
│   │   ├── verification.py    # ★ Abstention verdict
│   │   ├── validation.py      # ★ Upload size/type/page/encoding/PDF checks
│   │   ├── routing.py         # Task → Groq model mapping
│   │   ├── memory.py          # Conversation history formatting
│   │   ├── storage.py         # SQLite: users, sessions, messages, docs, metrics
│   │   ├── vision.py          # Groq Qwen 3.8 image → questions extraction
│   │   ├── voice.py           # Groq Whisper transcription endpoint
│   │   ├── seed_metrics.py    # Synthetic data for dashboard chart dev
│   │   └── data/              # Runtime: app.db, chroma/, uploads/
│   │       ├── app.db         # SQLite (auto-created)
│   │       ├── chroma/        # Chroma persistence + index_meta.pkl
│   │       └── uploads/       # Persisted files + images/
│   ├── tests/                 # pytest suite (safety rails)
│   ├── requirements.txt
│   ├── requirements-dev.txt
│   ├── pyproject.toml
│   ├── railway.toml           # Railway start command + healthcheck
│   ├── Makefile
│   └── .env.example
│
├── frontend/
│   ├── index.html             # Requires viewport-fit=cover for safe-area insets
│   ├── src/
│   │   ├── main.tsx           # React entry — mounts App inside providers
│   │   ├── App.tsx            # Route definitions
│   │   ├── RequireAuth.tsx    # Route guard
│   │   ├── AuthContext.tsx    # useAuth()
│   │   ├── AuthPage.tsx       # Login / register
│   │   ├── ForgotPassword.tsx # Email entry for reset
│   │   ├── ResetPassword.tsx  # New password + strength meter
│   │   ├── GoogleCallback.tsx # OAuth landing
│   │   ├── LandingPage.tsx    # Public marketing page
│   │   ├── MainApp.tsx        # Authenticated chat surface + mobile drawer shell
│   │   ├── AdminPage.tsx      # Analytics dashboard
│   │   ├── components.tsx     # 15+ UI components
│   │   ├── AnswerCard.tsx     # Assistant message card
│   │   ├── UserBubble.tsx     # User message bubble
│   │   ├── AgentTrace.tsx     # Standalone trace component (landing preview)
│   │   ├── ArgusLogo.tsx      # Brand mark + utility icons
│   │   ├── api.ts             # Typed HTTP client
│   │   ├── admin.ts           # Admin analytics API client
│   │   ├── sse.ts             # SSE parser (JSON envelope)
│   │   ├── types.ts           # TS mirrors of backend schemas
│   │   ├── useVoice.ts        # STT + TTS hooks
│   │   ├── index.css          # Dark violet theme
│   │   ├── theme-argus.css    # Chat card language + mobile shell
│   │   └── landing.css        # Landing page (lp2-* scope)
│   ├── package.json
│   ├── tsconfig.json
│   ├── railway.toml           # Railway build + serve commands
│   └── vite.config.ts         # Dev proxies /api and /health to :8000
│
└── README.md
```

### `backend/app/` — what each file owns

| File | Responsibility | Key exports |
|---|---|---|
| `main.py` | FastAPI app, route definitions, dependencies (`current_user`, `require_admin`), SSE serialization, image batch streaming | `app` |
| `config.py` | Pydantic `BaseSettings` loaded from `.env`. Groq + HuggingFace fields, `frontend_url` for OAuth/reset links | `Settings`, `get_settings()` |
| `agent_state.py` | Frozen per-request `AgentSettings` + the `AgentStateName` enum | `AgentSettings`, `AgentStateName` |
| `auth.py` | bcrypt hash/verify, HS256 JWT issuance + validation. Fails at import if `JWT_SECRET` missing | `hash_password`, `verify_password`, `create_jwt`, `decode_jwt` |
| `password_reset.py` | `/auth/forgot-password` and `/auth/reset-password`. Non-disclosure on missing email | `router` |
| `google_auth.py` | `/auth/google/start` and `/auth/google/callback`. Find-or-create user, link by email | `router` |
| `email.py` | Thin wrapper over `resend.Emails.send`. Failures are logged, never raised | `send_password_reset` |
| `schemas.py` | Pydantic request/response models — `QueryRequest`, `AnswerResponse`, `Citation`, `SessionInfo`, SSE event shapes | 15+ models |
| `models.py` | Domain dataclasses — `Chunk`, `Citation`, `AgentDecision`, `ActivityStep`, `AgentResult`, `EvaluationResult`, `VerificationResult` | 10+ dataclasses |
| `rag_engine.py` | The pipeline. `AgenticRAGService` — `stream()`, `run()`, `stream_batch()`, `ask_stream()`. Eval block computation. Rate-limit detection. Gate regexes. Support-token check | `AgenticRAGService`, `get_rag_engine`, `RunResult` |
| `retrieval.py` | Chroma wrapper. Filter-at-DB + strict threshold. Targeted vs broad mode. `MAX_TOTAL_K = 24` | `VectorStore`, `Retriever`, `get_vector_store` |
| `citations.py` | `[Sn]` protocol. Handles `【S1】` and `【S1+L1-L4】` variants. Validates quotes against source | `build_citation_prompt_block`, `parse_citation_ids`, `citations_from_referenced` |
| `verification.py` | Abstention logic. Content-token overlap heuristic + optional LLM verifier + citation coverage. Fails closed on LLM error | `combine_verdicts`, `verify_answer`, `estimate_grounding`, `ABSTAIN_MESSAGE` |
| `validation.py` | Six upload checks: extension, size, page count, batch size, UTF-8-with-fallback decode, encrypted-PDF detection | `ValidationError`, `validate_upload`, `guard_pdf_open` |
| `routing.py` | Task → model mapping. Structured tasks → 20B, generation → 120B | `MODEL_SMALL`, `MODEL_LARGE`, `model_for_task` |
| `memory.py` | `ChatSession` view + `format_history_for_prompt()` | `ChatSession`, `format_history_for_prompt` |
| `storage.py` | All SQLite. Users, sessions, messages, feedback, documents, summaries, auth_events, query_metrics, password_resets. Schema + forward migrations | 45+ functions, `get_storage()` |
| `vision.py` | Groq Qwen 3.8 for image → questions extraction. Returns `[]` on parse failure | `extract_questions_from_image` |
| `voice.py` | `POST /api/v1/transcribe` via Whisper Large v3 Turbo | `router` |
| `seed_metrics.py` | Generates synthetic dashboard data. Writes to `app_seed.db` by default | CLI entrypoint |

### `frontend/src/` — what each file owns

| File | Responsibility | Key exports |
|---|---|---|
| `main.tsx` | React entry — `BrowserRouter > AuthProvider > App`, imports `index.css` and `theme-argus.css` | default render |
| `App.tsx` | Seven routes: `/`, `/login`, `/forgot-password`, `/reset-password`, `/auth/google/callback`, `/app`, `/admin`. Wildcard → `/` | `App` |
| `RequireAuth.tsx` | Route guard. Loading → placeholder; no user → redirect with `state.from` | `RequireAuth` |
| `AuthContext.tsx` | Session state. Imports `BACKEND_ORIGIN` from `./api` — single source of truth for the backend URL. Provides `user`, `isAdmin`, `loading`, `login`, `register`, `logout`, `refresh` | `AuthProvider`, `useAuth` |
| `AuthPage.tsx` | Login / register tabbed screen. Split layout with live agent preview. Hosts Forgot-password link + Continue with Google button (`BACKEND_ORIGIN`) | `AuthPage` |
| `ForgotPassword.tsx` | Centered glass card, rotating aurora, 3D tilt. Uses `API_BASE` from `./api` | `ForgotPassword` |
| `ResetPassword.tsx` | Two-column split. Form on left, live strength meter on right. Uses `API_BASE` from `./api` | `ResetPassword` |
| `GoogleCallback.tsx` | Refreshes auth context, navigates to `/app`. Uses `API` from `./api` | `GoogleCallback` |
| `LandingPage.tsx` | Public marketing page. Hero with 3D tilt, contrast section, animated paper panel, flow, capabilities, CTA | `LandingPage` |
| `MainApp.tsx` | The chat surface. Doc selection, session list, SSE consumer, image batch handler, settings persistence. Also owns the mobile off-canvas drawer: `drawerOpen` state, `matchMedia` breakpoint detection, body-scroll-lock, escape-key close, and drawer auto-close on session select / new chat / send / image query / logout | `MainApp` |
| `AdminPage.tsx` | Analytics dashboard. Summary cards, activity chart, RAG health tiles, recent queries table | `AdminPage` |
| `components.tsx` | 15+ presentational components. `ChatPanel` owns the auto-scroll effect (anchors to the last user bubble, not the bottom of the list) and the composer + suggested-question rendering | 15+ exports |
| `AnswerCard.tsx` | Assistant message card — doc chips, badge, markdown body, inline citation chips (`highlightCitations`), Sources accordion, trace, footer | `AnswerCard` |
| `UserBubble.tsx` | Right-aligned user message bubble | `UserBubble` |
| `AgentTrace.tsx` | Standalone trace component (used by landing preview, kept separate from the inline one inside `AnswerCard`) | `AgentTrace` |
| `ArgusLogo.tsx` | Brand mark (violet→pink gradient) + 14 utility icons | `ArgusLogo`, `MicIcon`, `SpeakerIcon`, … |
| `api.ts` | Typed HTTP client. `BASE` from `VITE_API_BASE` or `localhost:8000`, resolved via `import.meta.env.PROD`. Exports `BACKEND_ORIGIN` and `API_BASE` so auth modules share one URL | 20+ functions, `API` |
| `admin.ts` | Admin analytics client — `fetchSummary`, `fetchTimeSeries`, `fetchRagMetrics`, `fetchRecent` | 4 functions, 6 interfaces |
| `sse.ts` | `streamQuery()` — hand-rolled SSE parser for the JSON-envelope format | `streamQuery`, `SseEvent` |
| `types.ts` | TS mirrors of every backend schema | 20+ interfaces |
| `useVoice.ts` | `useVoiceRecorder` (Web Speech API → Whisper fallback) + `useSpeech` (TTS with markdown stripping) | two hooks |
| `index.css` | Dark violet theme. App shell, chat canvas, sidebar, composer, auth, admin, forgot/reset password. Contains a `@media (max-width: 768px)` block that collapses the two-column grid and hides the desktop chat header | ~1800 lines |
| `theme-argus.css` | Chat card language ported from the landing page — `.argus-card`, `.argus-cite`, `.argus-user-bubble`, `.argus-msg-row`, unified `.argus-sources-header` / `.argus-trace-header`. Also owns the mobile shell: off-canvas drawer, mobile top bar, safe-area padding, `scroll-padding-top` on `.messages`, and the composer sticky positioning | ~600 lines |
| `landing.css` | Landing page styles. All selectors `lp2-*` scoped | ~1000 lines |

## Tech stack

| Layer | Technology | Notes |
|---|---|---|
| Backend framework | FastAPI + Uvicorn | Async routes, SSE streaming, auto OpenAPI at `/docs` |
| LLM (generation) | Groq `openai/gpt-oss-120b` | Answer writing. Highest-quality model in the rotation |
| LLM (structured tasks) | Groq `openai/gpt-oss-20b` | Understand, evaluate, refine, verify, suggest, overview. ~half the cost |
| LLM (vision) | Groq `qwen/qwen3.8-27b` | Image → questions extraction |
| LLM (voice) | Groq `whisper-large-v3-turbo` | Speech → text |
| Embeddings | `sentence-transformers/all-MiniLM-L6-v2` | 384-dim, CPU-only, local. No external API |
| Vector store | ChromaDB | Persistent, cosine similarity, per-doc metadata filtering |
| Chunking | LangChain `RecursiveCharacterTextSplitter` | 800 tokens per chunk, 150 overlap |
| Persistence | SQLite | Single-file DB. No server |
| Auth | bcrypt + PyJWT | HS256, 7-day expiry, HTTP-only `argus_session` cookie |
| Password hashing | bcrypt | Per-password salt, constant-time verify |
| Email | Resend | Password reset delivery |
| Google OAuth | OAuth 2.0 authorization code flow | `requests` for the token exchange |
| PDF export | ReportLab | Session → PDF with citations and trace |
| Frontend framework | React 18 + Vite + TypeScript | Modern toolchain, HMR, fast builds |
| Routing | react-router-dom 7 | Seven routes, one route guard |
| State | React hooks + Context + localStorage | No Redux |
| Markdown rendering | react-markdown + remark-gfm + rehype-raw | Tables, task lists, raw HTML (citation markers) |
| Charts | Recharts | Admin dashboard: line charts for activity and RAG metrics |
| Icons | Hand-drawn SVG | No icon library |
| CSS | Plain CSS with custom properties | No Tailwind, no CSS-in-JS |
| Backend testing | pytest | Focused on safety-rail modules |
| Backend dev deps | pytest, pytest-asyncio, ruff, mypy | |

**Why these choices:**

- **Groq over OpenAI.** Groq's inference is fast enough that the 10-stage pipeline still feels instant. Free tier is 200k tokens/day.
- **Local embeddings.** No network call for every chunk. MiniLM runs on CPU in milliseconds. No API key, no rate limit, no cost.
- **Chroma over Pinecone/Weaviate.** Single-directory persistence, no cluster, filters pushed into the query.
- **SQLite over Postgres.** Single-file DB. Perfect for a demo, adequate for moderate scale.
- **No framework for the pipeline.** Plain Python controller with if/else — no LangGraph, no agent framework. Easier to debug, easier to modify.
- **Two SSE formats.** Historical: `/query/stream` uses JSON-envelope (`data: {"type":..., "data":...}`), `/query/image` uses named events (`event: <type>\ndata: <payload>`). Documented as a known quirk.
- **Single source of truth for the backend URL.** `api.ts` exports `BACKEND_ORIGIN` and `API_BASE`, resolved at build time via `import.meta.env.PROD`. Auth modules import these — no hardcoded URLs anywhere else.

## Data model

### SQLite tables

**`users`** — `id`, `email` (unique), `password_hash`, `created_at`, `is_admin`, `google_sub`

- `password_hash = "*"` marks a Google-only account that has never set a password
- `google_sub` is the stable Google account identifier, `NULL` until linked

**`sessions`** — `id`, `title`, `created_at`, `updated_at`, `user_id`

**`messages`** — `id` (autoincrement), `session_id`, `role`, `content`, `metadata_json`, `created_at`

- `metadata_json` holds: `citations`, `sources` (previews), `trace` (agent steps), `eval` (metrics), plus image fields when applicable (`image_upload`, `image_id`, `image_url`, `image_answer`, `question_id`, `question_text`, `not_covered`)

**`feedback`** — `message_id` (PK), `rating` (up/down), `created_at`

**`documents`** — `document_id`, `filename`, `path`, `status`, `page_count`, `chunk_count`, `error`, `created_at`, `updated_at`, `user_id`

**`session_summaries`** — `session_id` (PK), `summary`, `created_at`, `user_id`

**`auth_events`** — `id`, `user_id`, `event` (signup/login/logout/password_reset), `created_at`

**`query_metrics`** — `message_id` (PK), `user_id`, `session_id`, `created_at`, `faithfulness`, `context_precision`, `chunks_retrieved`, `abstained`, `verification_passed`, `latency_ms`, `composite`

- Decoupled from `messages`. Deleting a session or purging a document doesn't erase these rows.

**`password_resets`** — `token` (PK), `user_id`, `expires_at`, `created_at`

- Tokens expire after 30 minutes and are deleted on consumption or startup purge

### Indexes

`idx_users_email`, `idx_users_google_sub`, `idx_messages_session`, `idx_sessions_user`, `idx_documents_user`, `idx_summaries_user`, `idx_auth_events_time`, `idx_auth_events_user`, `idx_query_metrics_time`, `idx_query_metrics_user`, `idx_password_resets_user`, `idx_password_resets_expires`

### Forward migrations

`init_db()` is idempotent. On older DBs it adds:

- `sessions.user_id` (for pre-auth DBs)
- `users.is_admin` (for pre-analytics DBs)
- `users.google_sub` (for Google OAuth)
- `password_resets` table (for the reset flow)

## API surface

All routes are under `/api/v1` except `/health`.

### Auth

| Method | Path | Purpose |
|---|---|---|
| POST | `/auth/register` | Create account, returns exchange token |
| POST | `/auth/login` | Verify credentials, returns exchange token |
| POST | `/auth/exchange` | Redeem exchange token for session cookie |
| POST | `/auth/logout` | Clears cookie, records event |
| GET | `/auth/me` | Return current user or 401 |
| POST | `/auth/forgot-password` | Email a reset link (non-disclosure on missing email) |
| POST | `/auth/reset-password` | Consume a reset token, set a new password |
| GET | `/auth/google/start` | Redirect to Google consent |
| GET | `/auth/google/callback` | Exchange code, redirect to SPA with exchange token |

> **Note on the two-step login flow.** Login and register do not set the session cookie on their response. They return a one-time `exchange_token`, which the frontend POSTs back to `/auth/exchange` via `fetch()`. The cookie is set on that response. This is a workaround for Chrome's bounce-tracking mitigations, which clear cookies set on cross-site POSTs when the destination domain has no prior site engagement history. Setting the cookie on a fetch-initiated response avoids the mitigation.

### Documents

| Method | Path | Purpose |
|---|---|---|
| POST | `/upload` | Upload + index a single file |
| POST | `/upload/batch` | Upload + index multiple files |
| GET | `/documents` | List user's documents |
| GET | `/documents/{id}` | Get one document |
| DELETE | `/documents/{id}` | Delete doc (+ optional session purge via `?purge_conversations=true`) |

### Query

| Method | Path | Purpose |
|---|---|---|
| POST | `/query` | Non-streaming JSON query |
| POST | `/query/stream` | SSE stream (JSON envelope) |
| POST | `/query/image` | Image upload → batch Q&A (SSE with named events) |

### Sessions

| Method | Path | Purpose |
|---|---|---|
| GET | `/sessions` | List user's sessions |
| GET | `/sessions/{id}` | Full history |
| PATCH | `/sessions/{id}` | Rename |
| DELETE | `/sessions/{id}` | Delete (+ images) |
| GET | `/sessions/{id}/export.md` | Markdown export |
| GET | `/sessions/{id}/export.pdf` | PDF export |

### Feedback & suggestions

| Method | Path | Purpose |
|---|---|---|
| POST | `/feedback/{message_id}?rating=up\|down` | Record thumbs |
| POST | `/suggest` | Generate starter questions |

### Voice

| Method | Path | Purpose |
|---|---|---|
| POST | `/transcribe` | Audio → text (Whisper) |

### Static

| Method | Path | Purpose |
|---|---|---|
| GET | `/images/{filename}` | Persisted chat images |

### Admin (403 for non-admins)

| Method | Path | Purpose |
|---|---|---|
| GET | `/admin/stats/summary?days=N` | Total users, sessions, messages, docs |
| GET | `/admin/stats/timeseries?days=N` | Per-day signups, logins, sessions |
| GET | `/admin/stats/rag?days=N` | Aggregate RAG metrics |
| GET | `/admin/stats/recent?limit=N` | Recent turns with metrics |

### Health

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Service status + version |

## Authentication

Three ways to get a session cookie:

1. **Email + password.** `POST /auth/register` (or `/auth/login`) hashes with bcrypt and returns a one-time `exchange_token`. The frontend POSTs the token to `/auth/exchange`, which sets `argus_session` on that fetch response. The first user whose email matches `ADMIN_EMAIL` is auto-promoted.
2. **Google OAuth.** `GET /auth/google/start` redirects to Google. `GET /auth/google/callback` exchanges the code, fetches the userinfo, and either finds an existing user by `google_sub`, links to an account with a matching email, or creates a new one. Redirects to the SPA with a one-time `exchange_token` in the URL; the frontend redeems it the same way as password login.
3. **Password reset.** `POST /auth/forgot-password` accepts an email and always returns 200 with the same message, whether or not the email exists. If the user exists and isn't Google-only, a token is generated, stored with a 30-minute TTL, and emailed via Resend. `POST /auth/reset-password` consumes the token, hashes the new password, and deletes the token.

**Cookie policy.** `argus_session` is HTTP-only, 7-day TTL, and `SameSite` is:

- `lax` in development (so plain HTTP on localhost works)
- `none` in production (so the split-origin deploy works — the cookie needs to be sent on cross-site requests)

`Secure` is set when `ENV=production`, and off locally.

## Frontend architecture

### Route map

| Path | Component | Guard |
|---|---|---|
| `/` | `LandingPage` | Public |
| `/login` | `AuthPage` | Public (redirects authed users to `/app`) |
| `/forgot-password` | `ForgotPassword` | Public |
| `/reset-password` | `ResetPassword` | Public (requires `?token=` in URL) |
| `/auth/google/callback` | `GoogleCallback` | Public (refreshes session, navigates to `/app`) |
| `/app` | `MainApp` | `RequireAuth` |
| `/admin` | `AdminPage` | `RequireAuth` + in-page `isAdmin` check |
| `*` | redirect → `/` | |

### State ownership

- **`AuthContext`** — the logged-in user. Fetched once on mount from `/auth/me`. Provides `user`, `isAdmin`, `loading`, `login`, `register`, `logout`, `refresh`.
- **`MainApp`** — everything else. Documents, selected doc IDs, pending uploads, sessions, active session ID, messages, feedback, suggestions, agent settings, UI toggles, sidebar collapse, mobile drawer. Persisted to `localStorage` where it matters.
- **`useSpeech`** — TTS state, voice selection, preview playback.
- **`useVoiceRecorder`** — STT state (`idle → requesting → recording → transcribing → error`).

No global state library. Context for session; hooks + localStorage for the rest.

### Backend URL resolution

`api.ts` resolves the backend URL once and exports it:

```ts
const BASE =
  env?.VITE_API_BASE ||
  (env?.PROD ? PROD_BACKEND : "http://localhost:8000");

export const BACKEND_ORIGIN = BASE;
export const API_BASE = `${BASE}/api/v1`;
```

- Dev (`npm run dev`): `import.meta.env.PROD` is false → `BASE` is `http://localhost:8000`
- Prod (`npm run build`): `import.meta.env.PROD` is true → `BASE` is the Railway backend URL

`AuthContext`, `AuthPage`, `ForgotPassword`, and `ResetPassword` all import from `api.ts` — they do not hardcode URLs. This kills the localhost/prod flip-flop trap: there is exactly one place that decides the backend URL.

### SSE handling

Two parsers because two formats:

- `sse.ts` → `streamQuery()` for `/query/stream`. Reads `data: {"type": "...", "data": {...}}` frames. Events: `step | token | final | error | done`.
- `api.ts` → `queryImage()` for `/query/image`. Reads `event: <type>\ndata: <payload>` frames. Events: `questions | answer_start | answer_done | done`.

Both hand-rolled — no `EventSource`, no polyfill. `fetch` with `credentials: "include"`, response body read as a stream.

### Message restoration

Reloading a session doesn't replay raw rows. `MainApp.handleSelectSession`:

1. Iterates history rows in order.
2. Builds a `Map<image_id, ImageBatch>` as it goes.
3. Pushes an empty batch message the first time it sees `image_upload: true`.
4. Fills that batch as `image_answer: true` rows stream past.
5. Sorts each batch's items by `question_id`.

The result: the batch comes back as one bubble, not N separate messages.

### Chat message rendering

The chat workspace uses a card-based visual language ported from the landing page. Styles live in `theme-argus.css`:

- `.argus-card` — the assistant message container: frosted panel, 18px radius, radial glow in the top-left
- `.argus-cite` — inline citation chips. `S1 S2 S4` in bordered violet pills with monospace numerals. Adjacent markers get separated by `margin-left: 3px` so they never concatenate
- `.argus-doc-chip` — filename pills at the top of an answer
- `.argus-badge-cited` / `.argus-badge-abstained` — right-aligned state badge
- `.argus-user-row` / `.argus-user-bubble` — right-aligned user message, aligned with the assistant card's right edge
- `.argus-sources-header` / `.argus-trace-header` — shared styling for the two collapsible rows, so they render identically

Citation extraction happens in `AnswerCard.tsx::highlightCitations`. It walks the React tree, splits strings on `/\[S\d+\]/`, and emits `<span className="argus-cite">S{n}</span>` for each match. Brackets are stripped from the visible text — the chip styling is what signals "this is a citation."

`components.tsx::prepareAnswerForDisplay` normalizes whitespace before the answer reaches the renderer:

```ts
text
  .replace(/\u00A0/g, " ")           // non-breaking spaces → regular
  .replace(/[ \t]{2,}/g, " ")
  .replace(/ \n/g, "\n")
  .replace(/\]\s*\[/g, "] [")        // ensure a space between adjacent markers
  .replace(/\s+([.,;:!?])/g, "$1")   // tighten punctuation
```

It intentionally does **not** convert markers to HTML. That job belongs to `highlightCitations` — having both do it caused the marker to be replaced twice, losing the brackets and concatenating adjacent citations into `S1S2S4`.

## Mobile layout

Below 768px the workspace becomes a single-column phone UI. Desktop behaviour is unchanged.

- **Off-canvas drawer.** The sidebar becomes a fixed-position panel that slides in from the left when the hamburger in the mobile top bar is tapped. It's gated on a single `.app.drawer-open` class — set by `MainApp.tsx` when `drawerOpen === true`. The CSS has no other trigger.
- **Mobile top bar.** A sticky header above the chat with the hamburger, the "Argus" wordmark, and a scope pill (`N/N · K=x`). Hidden on desktop via `display: none` outside the media query.
- **Body scroll lock.** While the drawer is open, `document.body.style.overflow = "hidden"`. Cleared on close — the effect always writes `""`, never restores a captured `prev`, so a stale value can't get stuck across HMR.
- **Breakpoint detection.** Uses `matchMedia("(min-width: 769px)")` instead of a resize listener so the drawer closes once on the actual 768→769 boundary, not on every resize tick from DevTools device switching.
- **Scroll anchoring.** `ChatPanel` scrolls the last user message to the top of the viewport when a new turn begins, using `scrollIntoView({ block: "start" })` inside a `requestAnimationFrame`. Not `bottomRef` — that would push the user bubble off-screen when the assistant's answer fills the viewport. `scroll-padding-top` on `.messages` reserves space for the sticky top bar so the bubble doesn't land behind it.
- **Safe-area support.** `env(safe-area-inset-*)` on the top bar, drawer, and composer. Requires `viewport-fit=cover` in `frontend/index.html` — without it, iOS returns 0 for every inset and the notch/home-indicator padding silently disables.
- **Tap targets.** List rows in the sidebar get `min-height: 44px` on mobile. Composer inputs are forced to 16px — anything smaller triggers iOS Safari's auto-zoom-on-focus, which never zooms back out.
- **Chat header collapse.** The desktop chat header (logo + marketing copy) is hidden below 768px. The mobile top bar already shows "Argus", so the extra header is redundant and eats vertical space.

## Running it

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # then edit .env — see "Environment"
uvicorn app.main:app --reload --port 8000
```

Backend is live at `http://localhost:8000`. OpenAPI docs at `http://localhost:8000/docs`.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`. The Vite dev server proxies `/api` and `/health` to `localhost:8000` (see `vite.config.ts`) so there's no CORS dance in development.

**Testing on a phone over Wi-Fi:**

```bash
cd frontend
npm run dev -- --host
```

Vite prints a Network URL (`http://192.168.x.x:5173`). Open it on any phone on the same network. The dev proxy forwards `/api` to the Mac's `localhost:8000`, so the backend stays bound to localhost — no `--host` needed there.

### First-time admin

The first user whose email matches `ADMIN_EMAIL` in `.env` is auto-promoted. Otherwise promote manually:

```bash
cd backend
source .venv/bin/activate
python -c "
from app import storage
uid = storage.get_user_by_email('you@example.com')['id']
storage.set_admin(uid, True)
print('promoted')
"
```

## Environment

`backend/.env` must contain at minimum:

```bash
# LLM
GROQ_API_KEY=gsk_...

# Auth
JWT_SECRET=<long random string>
ADMIN_EMAIL=you@example.com

# Frontend origin — CORS + password-reset links
FRONTEND_URL=http://localhost:5173

# Google OAuth (optional — leave blank to disable)
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=http://localhost:8000/api/v1/auth/google/callback

# Resend (optional — leave blank to skip email delivery)
RESEND_API_KEY=
RESEND_FROM_EMAIL=onboarding@resend.dev
RESEND_FROM_NAME=Argus

# Set to "production" on Railway so cookies get Secure + SameSite=None
ENV=development
```

Get a free Groq key at <https://console.groq.com> — the free tier is 200,000 tokens/day.

Generate a `JWT_SECRET` with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Optional overrides (defaults shown):

```bash
# Retrieval
TOP_K=4
SCORE_THRESHOLD=0.0
MAX_RETRIEVAL_ATTEMPTS=2
CHUNK_SIZE=800
CHUNK_OVERLAP=150
MEMORY_MESSAGE_LIMIT=6

# Model routing (defaults)
GROQ_MODEL=openai/gpt-oss-120b
LLM_TEMPERATURE=0.0
LLM_MAX_TOKENS=2048

# Upload limits
MAX_UPLOAD_BYTES=20971520         # 20 MB
MAX_PAGES_PER_DOC=500
MAX_FILES_PER_BATCH=10

# Agent behaviour
QUERY_REWRITING=true
ANSWER_VERIFICATION=true
SOURCE_CITATIONS=true

# Verification
MIN_CITATION_COVERAGE=0.0
ABSTAIN_CONFIDENCE_THRESHOLD=0.15

# Storage — honour Railway-mounted volume
SQLITE_PATH=/data/argus.db
CHROMA_PATH=/data/chroma
```

## Deploying

Two Railway services, both from the same GitHub repo. Each has a `railway.toml` that tells Railway how to build and start it.

### Backend service

- **Root directory:** `backend`
- **Start command** (in `backend/railway.toml`): `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- **Healthcheck:** `/health`
- **Env vars** (set in Railway's dashboard, not from a file):
  - `GROQ_API_KEY`
  - `JWT_SECRET` — generate with `python -c "import secrets; print(secrets.token_urlsafe(48))"`
  - `ADMIN_EMAIL` — the account that gets auto-promoted
  - `FRONTEND_URL` — your Railway frontend URL
  - `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `GOOGLE_REDIRECT_URI`
  - `RESEND_API_KEY` / `RESEND_FROM_EMAIL` / `RESEND_FROM_NAME`
  - `ENV=production` — flips cookies to `Secure` + `SameSite=None`
  - `SQLITE_PATH=/data/argus.db`, `CHROMA_PATH=/data/chroma`
- **Volume:** mount at `/data`. Without it, every deploy starts with an empty database.

### Frontend service

- **Root directory:** `frontend`
- **Build command** (in `frontend/railway.toml`): `npm install && npm run build`
- **Start command:** `npx serve -s dist -l $PORT` (the `-s` flag rewrites unknown paths to `index.html`, so `/reset-password?token=...` works on a hard refresh)
- **Env var:** `VITE_API_BASE=https://<backend>.up.railway.app` — Vite bakes this into the bundle at build time. If it's missing in production, the app falls back to the hardcoded `PROD_BACKEND` constant in `api.ts`.

**Testing mobile.** Use a real iPhone or Android device, not DevTools emulation. Emulation doesn't reproduce `env(safe-area-inset-*)` (the insets are always 0 in DevTools), so the notch and home-indicator padding only appear on-device. In DevTools you can verify layout, drawer behaviour, and scroll anchoring — but not safe-area padding or iOS input zoom.

### Google Cloud

Add to **Authorized redirect URIs**:

- `http://localhost:8000/api/v1/auth/google/callback` (dev)
- `https://<backend>.up.railway.app/api/v1/auth/google/callback` (prod)

The URI in Google Cloud must match `GOOGLE_REDIRECT_URI` in the backend's env vars, character for character. A trailing slash difference breaks the flow.

### torch on Railway

`requirements.txt` starts with:

```text
--extra-index-url https://download.pytorch.org/whl/cpu
```

This makes pip pull the CPU-only torch wheel (~200 MB) instead of the CUDA one (~2 GB). Cuts the first build from ~8 min to ~3.

## Using it

1. **Sign up / log in.** First account becomes admin if the email matches `ADMIN_EMAIL`. Google OAuth and password reset are also available.
2. **Upload** one or more PDF / TXT / MD files via the sidebar.
3. **Process Documents** — the pipeline extracts text, chunks, embeds, and indexes into ChromaDB. Idempotent: re-uploading the same file is skipped by SHA-256 hash.
4. **Ask a question.** Watch the Agent Reasoning expander fill in live.
5. **Read the grounded answer** with inline `[Sn]` citations. Click Sources to see the exact chunks that supported each claim.
6. **Rate answers** with 👍 / 👎 — persists to SQLite.
7. **Rename a session** by clicking the pencil icon on hover.
8. **Export** a conversation as Markdown or PDF.
9. **Upload an image** with the picture icon to get batch Q&A over questions in the photo. Click the thumbnail to open the lightbox.
10. **Use voice** with the mic button for STT, the speaker icon on any answer for TTS.
11. **Visit `/admin`** (admins only) for the analytics dashboard. Range selector: 7d / 30d / 90d / All.
12. **On mobile:** tap the ☰ in the top bar to open the document / session drawer. Everything else works the same way.

## Testing

```bash
cd backend
source .venv/bin/activate
pytest -q
```

Test coverage focuses on the safety-rail modules:

- `retrieval` — filter-at-DB correctness, strict threshold, broad mode
- `verification` — abstention verdict on low-confidence, LLM failure fallback
- `citations` — `[Sn]` parsing, unknown-ID detection, quote validation
- `validation` — size, page, encoding, encrypted-PDF checks

### Seeding the dashboard

For chart development without real usage:

```bash
cd backend
source .venv/bin/activate
python -m app.seed_metrics              # writes to app_seed.db
python -m app.seed_metrics --real       # writes to app.db (prompts first)
```

Both generate 30 days of deterministic synthetic data. The `--real` flag wipes only rows where `user_id='seed_user'`, so your real metrics survive.

## Design notes

- **No tool-calling.** The pipeline is a plain Python controller. Every LLM call returns structured JSON (parsed leniently — accepts fenced blocks, stray prose, `【】` bracket variants). No function-calling protocols, no framework lock-in.
- **Offline-safe abstractions.** `VectorStore` and the embedding function are interchangeable. Swap in an OpenAI embedder or a managed vector DB by editing `retrieval.py` — the rest of the pipeline doesn't care.
- **Deterministic regeneration.** Regenerating a question produces a fresh answer but reuses the same retrieved chunks, so you can compare phrasing without the retrieval layer changing underneath.
- **Durable metrics.** `query_metrics` is a separate table from `messages`. Eval metrics survive document deletion and session purge. This is the single most important architectural decision in the analytics layer.
- **Two SSE formats.** Historical: `/query/stream` uses JSON-envelope (`data: {"type":..., "data":...}`), `/query/image` uses named events (`event: <type>\ndata: <payload>`). Both work; unifying them is a future refactor.
- **Per-request settings.** `AgentSettings` is a frozen dataclass built from `Settings` + per-request overrides. Concurrent requests get independent snapshots. This was Finding #5 from the safety-rail audit.
- **Gates before retrieval.** Five regex patterns intercept greetings, capability questions, thanks, overview queries, and past-session queries before the pipeline runs. Each gate costs zero tokens.
- **Two-step login for bounce-tracking survival.** Login, register, and Google callback all return a short-lived `exchange_token` rather than setting the session cookie directly. The frontend redeems the token via `fetch()`, and the cookie is set on that response. Chrome's bounce-tracking mitigation clears cookies set on cross-site navigation responses, but leaves fetch-initiated `Set-Cookie` alone.
- **Single source of truth for the backend URL.** `api.ts` exports `BACKEND_ORIGIN` and `API_BASE`, resolved at build time via `import.meta.env.PROD`. Auth modules import these — no hardcoded URLs anywhere else. Adding a new auth-adjacent module means importing from `api.ts`, not defining a new constant.
- **Content-token grounding.** `verification.py::estimate_grounding` strips stopwords and punctuation before computing token coverage. A grounded explanatory answer scores ~0.7; a hallucinated one still scores ~0.3. Earlier versions counted every token with `len > 2`, which diluted the signal ~60% with stopwords and punctuation-glued fragments and caused grounded answers to score 0.38–0.39.
- **Mobile drawer as a single boolean.** The mobile UI has one piece of state — `drawerOpen` in `MainApp` — and one class gate — `.app.drawer-open` in the CSS. No separate "is mobile" boolean, no duplicated state in child components. The CSS media query decides when the drawer behavior applies; the JS just decides whether it's open. Adding a mobile-only feature means adding a rule inside `@media (max-width: 768px)`, not threading a new boolean through the tree.
- **Scroll anchored to the user, not the assistant.** Chat UIs commonly scroll to the bottom of the message list on every new message. On a phone, when the assistant's answer is longer than the viewport, that pushes the user's own question off the top — they can't see what they asked while reading the answer. Argus anchors the scroll to the last user bubble instead. The tradeoff: very long answers extend below the fold and require a manual scroll to read the end. That's the correct tradeoff for a Q&A interface — the question is what the user needs to re-read while evaluating the answer.
- **Safe-area padding requires `viewport-fit=cover`.** Every `env(safe-area-inset-*)` in the mobile CSS returns 0 if the viewport meta tag is missing `viewport-fit=cover`. The symptom is subtle: layout looks correct in DevTools but breaks on device. The fix is one word in `frontend/index.html`: `content="width=device-width, initial-scale=1.0, viewport-fit=cover"`.

### Known limitation: Incognito Chrome and authentication

Chrome's Bounce Tracking Mitigations clear cookies that are set on cross-site POSTs when the destination domain has no prior site engagement history. The Argus frontend and backend are on different Railway subdomains, so login involves a cross-origin POST — exactly the shape Chrome looks for.

**Consequence:** signing in from a fresh incognito window (or a brand-new Chrome profile with no browsing history) will appear to succeed but every subsequent request returns 401. The app shows the "Error: Not authenticated" banner.

In a normal browser window, everything works — Chrome has already accumulated engagement history for the Railway domains from ordinary browsing, so the mitigation doesn't fire.

**Testing guidance:** use a normal browser window for manual testing, or a dedicated Chrome profile (not incognito) with `chrome://settings/content/all` for clearing state between tests. If you need the app to work reliably from a cold profile, the fix is to serve the frontend and backend from a single origin.

**Why we haven't consolidated (yet):** the split-origin deploy is simpler to reason about per-service and doesn't require rebuilding the frontend inside the backend's Docker image. The tradeoff is that incognito testing is unreliable. If that becomes a real problem, consolidating into one Railway service eliminates this entire class of bug.

### Known limitation: mobile requires `viewport-fit=cover`

If `frontend/index.html`'s viewport meta tag is ever changed to remove `viewport-fit=cover`, every `env(safe-area-inset-*)` in the mobile CSS silently returns 0. The top bar will sit under the iPhone notch and the composer will sit under the home indicator. The symptom is subtle — layout looks correct in DevTools but breaks on device. The fix is one word in the meta tag.

## License

Copyright © 2026 Anas Yaqoob Baig. All rights reserved.