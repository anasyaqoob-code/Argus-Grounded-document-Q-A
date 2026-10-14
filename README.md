
Argus
Grounded document Q&A with explicit safety rails.

Argus is an agentic retrieval-augmented generation system that answers questions strictly from uploaded documents — with page-level citations, verification, and a full reasoning trace. It refuses to answer when evidence is weak, validates every citation against its source, and isolates every request from every other request.

Table of contents
What it does
The 10-stage pipeline
Safety rails
Architecture
Project structure
Tech stack
Data model
API surface
Authentication
Frontend architecture
Mobile layout
Running it
Environment
Deploying
Using it
Testing
Design notes
What it does
Argus is a document-grounded Q&A system. Upload PDFs, TXTs, or MDs. Ask questions. Get answers only from those files, with inline citations pointing to specific pages. When the evidence runs out, it abstains instead of guessing.

Multi-document retrieval with per-doc sweeps. When two or more documents are selected, retrieval sweeps each doc individually so no single document dominates the top-k. Critical for comparison and cross-doc questions.

Grounding by construction. The generation prompt contains only retrieved chunks. The LLM is explicitly forbidden from using general knowledge; if the context doesn't answer the question, it returns the abstain message.

Inline citations with validation. Every factual claim carries a [Sn] marker that maps to a specific chunk. Citations that don't resolve to a real chunk are dropped before the response is sent.

Full reasoning trace. The Agent Reasoning expander shows every stage, its duration, and its metadata — the same data that gets persisted to SQLite for session reload.

Session persistence. Messages, citations, source previews, and the full activity trace are stored. Reloading a session reproduces the original experience — pills, trace, sources — not a stripped version.

Multi-user with per-user isolation. bcrypt passwords, HS256 JWT in an HTTP-only cookie, Google OAuth, password reset via email, every read and write scoped by user_id.

Admin analytics. Signups, logins, sessions over time. Per-query RAG evaluation metrics (faithfulness, precision, verification pass rate, abstention rate, latency, composite). Metrics live in a table decoupled from messages so they survive document deletion.

Image Q&A. Upload a photo with questions. Groq Vision extracts each question; Argus answers each from the loaded documents; the whole batch persists as one bubble.

Voice in / voice out. Web Speech API first, Groq Whisper fallback. Text-to-speech with markdown-stripping and natural pause insertion.

Exports. Markdown and PDF, with citations and the agent trace preserved.

Mobile-first workspace. Below 768px the sidebar becomes an off-canvas drawer, the chat header collapses, and the composer pins above the home indicator. Safe-area aware.

The 10-stage pipeline
Every question runs through a deterministic agent loop. No tool-calling, no hidden LLM orchestration — a plain Python controller with one LLM call per stage.

UNDERSTAND  →  resolve pronouns, rewrite into a standalone question
DECIDE      →  pick response format + broad vs targeted retrieval
PLAN        →  build an optimized search query
SEARCH      →  ChromaDB vector search with per-doc filtering
OBSERVE     →  assemble the retrieved context
EVALUATE    →  judge whether the context answers the question
               skipped when ≥4 chunks retrieved
REFINE      →  rewrite the query if EVALUATE fails
GENERATE    →  stream a grounded answer with inline [Sn] citation IDs
VERIFY      →  validate each citation against its source chunk
               skipped when coverage ≥50%
FINAL       →  emit answer + citations + full activity trace
Two stages short-circuit on strong signals to save LLM tokens without sacrificing correctness. Both short-circuits still appear in the trace with skipped_llm: true metadata so the audit trail stays complete.

Gates
Before the pipeline runs, five regex gates intercept common cases without any retrieval:

Greetings (hi, hello, good morning) → canned reply
Capability questions (what can you do, who are you) → canned reply
Thanks (thanks, nice, perfect) → canned reply
Overview queries (summarize this pdf, what's in these documents) → per-document summarization path
Past-session queries (what did we discuss earlier) → cross-session summary recall
Each gate is a regex match, so it costs nothing and doesn't touch the LLM.

Safety rails
Each finding maps to one module. Every one is load-bearing — remove it and behavior regresses in a specific, testable way.

#	Finding	Module	What it prevents
1	Filter-at-DB	backend/app/retrieval.py	top_k wasted on unselected docs. Filters pushed into the Chroma query, not applied after ranking.
2	Abstention	backend/app/verification.py	Answering when evidence is weak. Returns a grounded refusal instead of hallucinating.
3	Citation validation	backend/app/citations.py	Citations pointing to chunks that don't exist or whose quotes aren't in the source.
4	Upload limits	backend/app/validation.py	Oversized files, unsupported types, encrypted PDFs, page bombs.
5	Per-request settings	backend/app/agent_state.py	Global Settings mutation under concurrent requests. Each request gets an immutable snapshot.
6	Rate-limit handling	backend/app/rag_engine.py	Mid-stream Groq 429s crashing the SSE connection. Surfaces a clean, user-facing message.
7	Fail-open on final verify	backend/app/rag_engine.py	A well-cited answer being overwritten with the abstain message on the last retry.
8	Filename normalization	backend/app/rag_engine.py	"No documents selected" when chip names, DB filenames, and chunk metadata differ by case or path prefix.
9	Full metadata persistence	backend/app/rag_engine.py	Pills, reasoning trace, and sources vanishing when reloading a past session.
10	Per-user isolation	backend/app/storage.py	Session and document cross-talk between users. Every read/write scoped by user_id.
Beyond the numbered rails, five architectural decisions do heavy lifting:

Durable metrics. query_metrics is a separate table from messages. Every eval metric (faithfulness, precision, latency, composite) is written there so deleting a document or purging a session doesn't erase the analytics. recent_queries LEFT JOINs on the message so a deleted message still shows its metric with a (question no longer available) placeholder.

Strict threshold. VectorStore.query() applies score_threshold before returning. If every result is below the threshold, it returns []. No silent fallback to unfiltered results.

Model routing. Structured-output tasks (understand, evaluate, refine, verify, suggest, overview) route to gpt-oss-20b. Only generation routes to gpt-oss-120b. Roughly halves the per-query token bill.

Content-token grounding. verification.py::estimate_grounding measures coverage over content tokens only — stopwords and punctuation are stripped before the intersection. Grounded paraphrased answers score high; hallucinated answers (whose content words aren't in the source) still score low.

Scroll anchored to the user, not the assistant. On mobile, when the assistant's answer exceeds the viewport, the auto-scroll targets the last user bubble at the top of the visible area, not the bottom of the message list. The user can re-read their question while reading the answer. Desktop behaviour is unchanged.

Architecture
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
│ fetch + SSE (HTTP-only cookie auth)                              │
└───────────────────────────┼─────────────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│ FastAPI (uvicorn)                                               │
│ main.py — routes, auth deps, SSE serialization                  │
│   ├── auth.py            (JWT, bcrypt)                           │
│   ├── password_reset.py  (Resend email + tokens)                │
│   ├── google_auth.py     (OAuth 2.0 authorization code)          │
│   ├── email.py           (Resend wrapper)                        │
│   ├── storage.py         (SQLite)                                │
│   ├── validation.py      (upload checks)                         │
│   ├── vision.py          (Groq vision model)                     │
│   ├── voice.py           (Groq Whisper)                          │
│   └── rag_engine.AgenticRAGService                              │
│       ├── agent_state.py   (immutable per-request)               │
│       ├── retrieval.py     (Chroma + filter-at-DB)               │
│       ├── citations.py     ([Sn] protocol)                       │
│       ├── verification.py  (3-signal verdict)                    │
│       ├── routing.py       (task → model)                        │
│       ├── memory.py        (history formatting)                  │
│       ├── models.py        (domain dataclasses)                  │
│       └── config.py        (Pydantic settings)                    │
│                                                                 │
│ LLM calls ──► Groq                                             │
│   • openai/gpt-oss-120b   (generation)                          │
│   • openai/gpt-oss-20b    (structured tasks)                     │
│   • qwen vision model     (image question extraction)            │
│   • whisper-large-v3-turbo (voice)                               │
│ Embeddings ──► HuggingFace (all-MiniLM-L6-v2, CPU)              │
│ Vector store ──► ChromaDB (persistent, cosine)                  │
│ Persistence ──► SQLite (app.db)                                 │
│ Email ──► Resend                                                │
└─────────────────────────────────────────────────────────────────┘
Project structure
Argus/
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI routes, auth deps, SSE serialization
│   │   ├── config.py          # Pydantic BaseSettings — env-driven
│   │   ├── agent_state.py     # Immutable per-request AgentSettings + state names
│   │   ├── auth.py            # bcrypt + JWT (HS256, 7-day expiry)
│   │   ├── password_reset.py  # Forgot/reset endpoints
│   │   ├── google_auth.py     # Google OAuth start + callback
│   │   ├── email.py           # Resend wrapper
│   │   ├── schemas.py         # Pydantic request/response models
│   │   ├── models.py          # Domain dataclasses
│   │   ├── rag_engine.py      # 10-stage pipeline + persistence
│   │   ├── retrieval.py       # Chroma wrapper, filter-at-DB, broad mode
│   │   ├── citations.py       # [Sn] parsing + validation
│   │   ├── verification.py    # Abstention verdict
│   │   ├── validation.py      # Upload size/type/page/encoding/PDF checks
│   │   ├── routing.py         # Task → Groq model mapping
│   │   ├── memory.py          # Conversation history formatting
│   │   ├── storage.py         # SQLite tables and migrations
│   │   ├── vision.py          # Image → question extraction
│   │   ├── voice.py           # Whisper transcription endpoint
│   │   ├── seed_metrics.py    # Synthetic dashboard data
│   │   └── data/              # Runtime database, Chroma and uploads
│   ├── tests/                 # pytest safety-rail suite
│   ├── requirements.txt
│   ├── requirements-dev.txt
│   ├── pyproject.toml
│   ├── railway.toml
│   ├── Makefile
│   └── .env.example
├── frontend/
│   ├── index.html             # viewport-fit=cover for safe-area insets
│   ├── src/
│   │   ├── main.tsx
│   │   ├── App.tsx
│   │   ├── RequireAuth.tsx
│   │   ├── AuthContext.tsx
│   │   ├── AuthPage.tsx
│   │   ├── ForgotPassword.tsx
│   │   ├── ResetPassword.tsx
│   │   ├── GoogleCallback.tsx
│   │   ├── LandingPage.tsx
│   │   ├── MainApp.tsx        # Chat surface + mobile drawer shell
│   │   ├── AdminPage.tsx
│   │   ├── components.tsx     # UI components + chat auto-scroll
│   │   ├── AnswerCard.tsx
│   │   ├── UserBubble.tsx
│   │   ├── AgentTrace.tsx
│   │   ├── ArgusLogo.tsx
│   │   ├── api.ts
│   │   ├── admin.ts
│   │   ├── sse.ts
│   │   ├── types.ts
│   │   ├── useVoice.ts
│   │   ├── index.css
│   │   ├── theme-argus.css    # Chat cards + mobile shell
│   │   └── landing.css
│   ├── package.json
│   ├── tsconfig.json
│   ├── railway.toml
│   └── vite.config.ts
└── README.md
backend/app/ file responsibilities
File	Responsibility	Key exports
main.py	FastAPI routes, dependencies, SSE serialization, image batch streaming	app
config.py	Pydantic settings loaded from .env	Settings, get_settings()
agent_state.py	Frozen per-request settings and state names	AgentSettings, AgentStateName
auth.py	bcrypt password hashing and HS256 JWT	hash_password, verify_password, create_jwt, decode_jwt
password_reset.py	Forgot/reset endpoints with non-disclosure for unknown email	router
google_auth.py	Google OAuth start and callback	router
email.py	Resend wrapper	send_password_reset
schemas.py	Pydantic request/response models and SSE event shapes	15+ models
models.py	Domain dataclasses	Chunk, Citation, AgentDecision, ActivityStep, AgentResult, EvaluationResult, VerificationResult
rag_engine.py	Pipeline, persistence, rate-limit handling, gate regexes	AgenticRAGService, get_rag_engine, RunResult
retrieval.py	Chroma wrapper, strict threshold, targeted/broad retrieval	VectorStore, Retriever, get_vector_store
citations.py	[Sn] parsing and citation/quote validation	build_citation_prompt_block, parse_citation_ids, citations_from_referenced
verification.py	Abstention, grounding heuristic and optional LLM verifier	combine_verdicts, verify_answer, estimate_grounding, ABSTAIN_MESSAGE
validation.py	Upload extension, size, page, batch, encoding and encrypted-PDF checks	ValidationError, validate_upload, guard_pdf_open
routing.py	Task-to-model mapping	MODEL_SMALL, MODEL_LARGE, model_for_task
memory.py	Chat history formatting	ChatSession, format_history_for_prompt()
storage.py	SQLite users, sessions, messages, docs, metrics, auth events and migrations	45+ functions, get_storage()
vision.py	Image question extraction	extract_questions_from_image
voice.py	Whisper transcription endpoint	router
seed_metrics.py	Synthetic dashboard data	CLI entrypoint
frontend/src/ file responsibilities
File	Responsibility	Key exports
main.tsx	React entry; mounts providers	default render
App.tsx	Route definitions	App
RequireAuth.tsx	Route guard	RequireAuth
AuthContext.tsx	User/session state and auth operations	AuthProvider, useAuth
AuthPage.tsx	Login/register and Google sign-in	AuthPage
ForgotPassword.tsx	Password reset request UI	ForgotPassword
ResetPassword.tsx	New password form and strength meter	ResetPassword
GoogleCallback.tsx	OAuth callback handling	GoogleCallback
LandingPage.tsx	Public marketing page	LandingPage
MainApp.tsx	Chat surface, documents, sessions, SSE, settings and mobile drawer	MainApp
AdminPage.tsx	Analytics dashboard	AdminPage
components.tsx	Presentational components, composer and user-anchored scroll	15+ exports
AnswerCard.tsx	Answer, citation chips, sources and trace	AnswerCard
UserBubble.tsx	User message bubble	UserBubble
AgentTrace.tsx	Standalone trace component	AgentTrace
ArgusLogo.tsx	Brand mark and utility icons	ArgusLogo, MicIcon, etc.
api.ts	Typed HTTP client and backend URL source of truth	BACKEND_ORIGIN, API_BASE, API
admin.ts	Admin analytics client	fetchSummary, fetchTimeSeries, fetchRagMetrics, fetchRecent
sse.ts	SSE parser for query stream	streamQuery, SseEvent
types.ts	TypeScript mirrors of backend schemas	20+ interfaces
useVoice.ts	Speech-to-text and text-to-speech hooks	useVoiceRecorder, useSpeech
index.css	Main theme, app shell, auth/admin and mobile breakpoints	CSS
theme-argus.css	Chat cards, citation chips and mobile shell	CSS
landing.css	Scoped landing page styles	CSS
Tech stack
Layer	Technology	Notes
Backend	FastAPI + Uvicorn	Async routes, SSE, OpenAPI at /docs
LLM generation	Groq openai/gpt-oss-120b	Grounded answer generation
LLM structured tasks	Groq openai/gpt-oss-20b	Understand, evaluate, refine, verify, suggest, overview
LLM vision	Groq vision model	Image question extraction
LLM voice	Groq whisper-large-v3-turbo	Speech-to-text
Embeddings	sentence-transformers/all-MiniLM-L6-v2	384-dimensional, CPU-only, local
Vector store	ChromaDB	Persistent, cosine similarity, metadata filters
Chunking	LangChain RecursiveCharacterTextSplitter	800-token chunks, 150 overlap
Persistence	SQLite	Single-file database
Authentication	bcrypt + PyJWT	HS256, 7-day HTTP-only cookie
Email	Resend	Password reset
Google OAuth	OAuth 2.0 authorization code flow	Token exchange
PDF export	ReportLab	Session export with citations and trace
Frontend	React 18 + Vite + TypeScript	HMR and production build
Routing	react-router-dom 7	Route guards
State	React hooks + Context + localStorage	No Redux
Markdown	react-markdown + remark-gfm + rehype-raw	Tables and task lists
Charts	Recharts	Admin dashboard
Icons	Hand-drawn SVG	No icon library
CSS	Plain CSS with custom properties	No Tailwind or CSS-in-JS
Tests	pytest	Safety-rail modules
Why these choices
Groq over OpenAI: fast inference keeps the multi-stage pipeline responsive.
Local embeddings: no external embedding API call, API key, or per-request embedding fee.
Chroma over managed vector DBs: simple local persistence and metadata filtering.
SQLite over Postgres: a single-file database suits a demo and moderate workloads.
No agent framework: the Python controller is explicit and easier to debug.
Single backend URL source: frontend auth modules import URL constants from api.ts.
Two SSE formats: /query/stream uses a JSON envelope; /query/image uses named events. This is a documented legacy inconsistency.
Data model
SQLite tables
users — id, unique email, password_hash, created_at, is_admin, google_sub
password_hash = "*" marks a Google-only account that has never set a password.
google_sub is the stable Google account identifier, null until linked.
sessions — id, title, created_at, updated_at, user_id
messages — id, session_id, role, content, metadata_json, created_at
metadata_json holds citations, source previews, trace, eval metrics and image fields.
feedback — message_id (PK), rating (up/down), created_at
documents — document ID, filename, path, status, page/chunk counts, error, timestamps, user_id
session_summaries — session_id (PK), summary, created_at, user_id
auth_events — ID, user ID, event, timestamp
query_metrics — message ID (PK), user/session IDs, timestamp, faithfulness, context precision, chunks retrieved, abstention, verification pass, latency, composite
Decoupled from messages so analytics can survive message or session deletion.
password_resets — token (PK), user ID, expiry, creation timestamp
Tokens expire after 30 minutes and are deleted on consumption or startup purge.
Indexes
idx_users_email, idx_users_google_sub, idx_messages_session, idx_sessions_user, idx_documents_user, idx_summaries_user, idx_auth_events_time, idx_auth_events_user, idx_query_metrics_time, idx_query_metrics_user, idx_password_resets_user, idx_password_resets_expires.

Forward migrations
init_db() is idempotent. Older databases are migrated to add sessions.user_id, users.is_admin, users.google_sub, and the password_resets table.

API surface
All routes are under /api/v1 except /health.

Auth
Method	Path	Purpose
POST	/auth/register	Create account; return exchange token
POST	/auth/login	Verify credentials; return exchange token
POST	/auth/exchange	Redeem exchange token for session cookie
POST	/auth/logout	Clear cookie and record event
GET	/auth/me	Return current user or 401
POST	/auth/forgot-password	Email reset link; avoid disclosing unknown email
POST	/auth/reset-password	Consume reset token and set new password
GET	/auth/google/start	Redirect to Google consent
GET	/auth/google/callback	Exchange code and redirect to SPA
Documents
Method	Path	Purpose
POST	/upload	Upload and index one file
POST	/upload/batch	Upload and index multiple files
GET	/documents	List user's documents
GET	/documents/{id}	Get one document
DELETE	/documents/{id}	Delete document; optional session purge
Query
Method	Path	Purpose
POST	/query	Non-streaming JSON query
POST	/query/stream	SSE stream using JSON envelope
POST	/query/image	Image upload and batch Q&A using named SSE events
Sessions
Method	Path	Purpose
GET	/sessions	List user's sessions
GET	/sessions/{id}	Full history
PATCH	/sessions/{id}	Rename session
DELETE	/sessions/{id}	Delete session and images
GET	/sessions/{id}/export.md	Markdown export
GET	/sessions/{id}/export.pdf	PDF export
Feedback and suggestions
Method	Path	Purpose
POST	/feedback/{message_id}?rating=up|down	Record answer rating
POST	/suggest	Generate starter questions
Voice and static assets
Method	Path	Purpose
POST	/transcribe	Audio-to-text via Whisper
GET	/images/{filename}	Serve persisted chat images
Admin (403 for non-admins)
Method	Path	Purpose
GET	/admin/stats/summary?days=N	User, session, message and document totals
GET	/admin/stats/timeseries?days=N	Daily signups, logins and sessions
GET	/admin/stats/rag?days=N	Aggregate RAG metrics
GET	/admin/stats/recent?limit=N	Recent turns with metrics
Health
Method	Path	Purpose
GET	/health	Service status and version
Two-step login flow
Login and register do not set the session cookie directly. They return a one-time exchange_token, which the frontend sends to /auth/exchange; that response sets the HTTP-only cookie. The Google callback uses the same exchange flow.

Authentication
Three ways to obtain a session cookie:

Email and password: /auth/register or /auth/login verifies credentials and returns an exchange token. The frontend redeems it through /auth/exchange. The first user whose email matches ADMIN_EMAIL is auto-promoted.
Google OAuth: /auth/google/start redirects to Google. The callback exchanges the code, fetches user info, links or creates the user, then redirects to the SPA with a one-time exchange token.
Password reset: /auth/forgot-password always returns the same success message whether or not the email exists. For eligible users, a 30-minute token is emailed via Resend. /auth/reset-password consumes it and updates the password.
Cookie policy
argus_session is HTTP-only with a seven-day TTL:

Development: SameSite=Lax; Secure is off for localhost HTTP.
Production: SameSite=None and Secure for split-origin deployment.
Frontend architecture
Route map
Path	Component	Access
/	LandingPage	Public
/login	AuthPage	Public; redirects authenticated users
/forgot-password	ForgotPassword	Public
/reset-password	ResetPassword	Public; requires ?token=
/auth/google/callback	GoogleCallback	Public
/app	MainApp	Authenticated
/admin	AdminPage	Authenticated; admin-only
*	Redirect to /	—
State ownership
AuthContext owns the logged-in user and auth operations.
MainApp owns documents, sessions, messages, feedback, suggestions, settings, UI toggles and the mobile drawer.
useSpeech owns text-to-speech state and playback.
useVoiceRecorder owns speech-to-text state.
No global state library is used. Context manages authentication; hooks and localStorage manage the remaining client state.

Backend URL resolution
api.ts resolves the backend URL once and exports BACKEND_ORIGIN and API_BASE. Development uses http://localhost:8000; production uses VITE_API_BASE or the PROD_BACKEND constant. Auth modules import these exports rather than defining their own backend URLs.

SSE handling
Two parsers handle the two existing formats:

sse.ts → streamQuery() for /query/stream; parses data: {"type": "...", "data": {...}}. Events: step, token, final, error, done.
api.ts → queryImage() for /query/image; parses event: <type>\ndata: <payload>. Events: questions, answer_start, answer_done, done.
Both use fetch with credentials: "include" and read the response body as a stream.

Message restoration
When restoring a session, MainApp.handleSelectSession iterates history in order, groups image rows by image_id, creates a batch bubble on the first image_upload: true row, fills it from later image_answer: true rows, and sorts items by question_id. A batch therefore restores as one bubble.

Chat message rendering
The chat workspace uses card-based styling in theme-argus.css:

.argus-card — assistant message container with frosted panel, rounded corners and radial glow.
.argus-cite — inline citation chips.
.argus-doc-chip — filename pills.
.argus-badge-cited / .argus-badge-abstained — answer state badges.
.argus-user-row / .argus-user-bubble — right-aligned user message.
.argus-sources-header / .argus-trace-header — shared styling for collapsible sections.
AnswerCard.tsx::highlightCitations walks the React tree, splits strings on /\[S\d+\]/, and renders citation chips. components.tsx::prepareAnswerForDisplay normalizes whitespace and ensures adjacent citation markers stay separated; it does not convert markers to HTML.

Mobile layout
Below 768px, the workspace becomes a single-column phone UI. Desktop behaviour is unchanged.

Off-canvas drawer. The sidebar becomes a fixed-position panel that slides in from the left when the hamburger in the mobile top bar is tapped. It is controlled by .app.drawer-open, set by MainApp.tsx when drawerOpen === true.

Mobile top bar. A sticky header above the chat contains the hamburger, Argus wordmark and scope pill. It is hidden on desktop.

Body scroll lock. While the drawer is open, document.body.style.overflow is set to hidden; on close the effect clears it to an empty string.

Breakpoint detection. Uses matchMedia("(min-width: 769px)") so the drawer closes at the 768-to-769px boundary rather than on every resize tick.

Scroll anchoring. When a new turn begins, ChatPanel scrolls the last user message to the top of the viewport using scrollIntoView({ block: "start" }) in a requestAnimationFrame. It does not pin to the bottom of the message list, which would push the question off-screen during a long answer. scroll-padding-top reserves space for the sticky top bar.

Safe-area support. The top bar, drawer and composer use env(safe-area-inset-*). This requires viewport-fit=cover in frontend/index.html; without it, iOS reports zero insets.

Tap targets. Sidebar rows have a minimum 44px height on mobile. Composer inputs use 16px font size to avoid iOS Safari's automatic zoom on focus.

Chat header collapse. The desktop chat header is hidden below 768px because the mobile top bar already identifies the app and preserves vertical space.

Running it
Backend
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
cp .env.example .env               # then edit .env — see Environment
uvicorn app.main:app --reload --port 8000
Backend: http://localhost:8000. OpenAPI docs: http://localhost:8000/docs.

Frontend
cd frontend
npm install
npm run dev
Open http://localhost:5173. Vite proxies /api and /health to localhost:8000 during development.

Testing on a phone over Wi-Fi
cd frontend
npm run dev -- --host
Open the Network URL printed by Vite (for example, http://192.168.x.x:5173) on a phone connected to the same network. The dev proxy forwards API requests to the Mac's backend.

First-time admin
The first user whose email matches ADMIN_EMAIL in .env is auto-promoted. Otherwise, promote manually:

cd backend
source .venv/bin/activate
python -c "
from app import storage
uid = storage.get_user_by_email('you@example.com')['id']
storage.set_admin(uid, True)
print('promoted')
"
Environment
backend/.env must contain at minimum:

# LLM
GROQ_API_KEY=gsk_...

# Auth
JWT_SECRET=<long-random-string>
ADMIN_EMAIL=you@example.com

# Frontend origin — CORS + password-reset links
FRONTEND_URL=http://localhost:5173

# Google OAuth (optional; leave blank to disable)
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=http://localhost:8000/api/v1/auth/google/callback

# Resend (optional; leave blank to skip email delivery)
RESEND_API_KEY=
RESEND_FROM_EMAIL=onboarding@resend.dev
RESEND_FROM_NAME=Argus

# Production enables Secure + SameSite=None cookies
ENV=development
Get a Groq API key from https://console.groq.com. Generate a JWT secret with:

python -c "import secrets; print(secrets.token_urlsafe(48))"
Optional overrides (defaults shown):

# Retrieval
TOP_K=4
SCORE_THRESHOLD=0.0
MAX_RETRIEVAL_ATTEMPTS=2
CHUNK_SIZE=800
CHUNK_OVERLAP=150
MEMORY_MESSAGE_LIMIT=6

# Model routing
GROQ_MODEL=openai/gpt-oss-120b
LLM_TEMPERATURE=0.0
LLM_MAX_TOKENS=2048

# Upload limits
MAX_UPLOAD_BYTES=20971520
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
Deploying
Deploy two Railway services from the same GitHub repository.

Backend service
Root directory: backend
Start command: uvicorn app.main:app --host 0.0.0.0 --port $PORT
Healthcheck: /health
Set the environment variables listed above in Railway's dashboard.
Set ENV=production.
Set SQLITE_PATH=/data/argus.db and CHROMA_PATH=/data/chroma.
Mount a persistent volume at /data; otherwise, deployments may start with an empty database and vector store.
Frontend service
Root directory: frontend
Build command: npm install && npm run build
Start command: npx serve -s dist -l $PORT
Set VITE_API_BASE=https://<backend>.up.railway.app. Vite embeds this value at build time. If unset, the app falls back to PROD_BACKEND in api.ts.
The -s option rewrites unknown paths to index.html, allowing routes such as /reset-password?token=... to work after a hard refresh.

Testing mobile
Use a real iPhone or Android device to validate safe-area behaviour. DevTools emulation can help verify layout, drawer behaviour and scroll anchoring, but it does not reliably reproduce device safe-area insets or iOS input zoom.

Google Cloud
Add these Authorized redirect URIs:

http://localhost:8000/api/v1/auth/google/callback (development)
https://<backend>.up.railway.app/api/v1/auth/google/callback (production)
The Google Cloud URI must match GOOGLE_REDIRECT_URI exactly, including trailing slash behaviour.

CPU-only PyTorch on Railway
If configured in requirements.txt, this index directs pip to CPU-only PyTorch wheels:

--extra-index-url https://download.pytorch.org/whl/cpu
This avoids downloading CUDA-enabled wheels when GPU support is not required.

Using it
Sign up or log in. The first account matching ADMIN_EMAIL becomes admin.
Upload one or more PDF, TXT or MD files through the sidebar.
Select Process Documents to extract text, chunk, embed and index files into ChromaDB. Re-uploading the same file is skipped by SHA-256 hash.
Ask a question and watch the Agent Reasoning expander fill in live.
Read the grounded answer with inline [Sn] citations. Open Sources to inspect the supporting chunks.
Rate answers with thumbs up/down; feedback persists to SQLite.
Rename sessions using the pencil icon.
Export conversations as Markdown or PDF.
Upload an image with the picture icon for batch Q&A over questions in the photo. Click the thumbnail to open the lightbox.
Use the mic for speech-to-text and the speaker icon on an answer for text-to-speech.
Visit /admin (admins only) for analytics, with 7-day, 30-day, 90-day and all-time ranges.
On mobile, tap the hamburger in the top bar to open the document/session drawer.
Testing
cd backend
source .venv/bin/activate
pytest -q
Test coverage focuses on:

Retrieval: filter-at-DB correctness, strict threshold and broad mode.
Verification: abstention on low confidence and LLM failure fallback.
Citations: [Sn] parsing, unknown-ID detection and quote validation.
Validation: size, page, encoding and encrypted-PDF checks.
Seeding the dashboard
For chart development without real usage:

cd backend
source .venv/bin/activate
python -m app.seed_metrics              # writes to app_seed.db
python -m app.seed_metrics --real       # writes to app.db (prompts first)
Both commands generate 30 days of deterministic synthetic data. The --real flag removes only rows where user_id='seed_user', preserving other metrics.

Design notes
No tool-calling. The pipeline is a plain Python controller. LLM calls return structured JSON, parsed leniently to accept fenced blocks, stray prose and bracket variants.

Offline-safe abstractions. The vector store and embedding function are interchangeable. A managed vector DB or hosted embedder can be substituted in retrieval.py.

Deterministic regeneration. Regenerating a question reuses the same retrieved chunks, allowing answer phrasing to be compared without changing retrieval.

Durable metrics. query_metrics is separate from messages, so evaluation metrics can survive document deletion and session purge.

Two SSE formats. /query/stream uses a JSON envelope, while /query/image uses named events. Both work, but unifying them is a possible future refactor.

Per-request settings. AgentSettings is a frozen dataclass built from global settings and request overrides, giving concurrent requests independent snapshots.

Gates before retrieval. Five regex patterns intercept greetings, capability questions, thanks, overview queries and past-session queries before the main pipeline.

Two-step login. Login, registration and Google callback return a short-lived exchange token. The frontend redeems it through fetch(), and that response sets the session cookie.

Single backend URL source. api.ts exports BACKEND_ORIGIN and API_BASE; auth modules import them instead of hardcoding URLs.

Content-token grounding. verification.py::estimate_grounding strips stopwords and punctuation before computing token coverage, reducing noise from common words and punctuation.

Mobile drawer as one boolean. MainApp owns drawerOpen; .app.drawer-open is the CSS gate. The media query determines when drawer styling applies, avoiding duplicated mobile state.

Scroll anchored to the user, not the assistant. On a phone, pinning the bottom of a long answer can push the user's question off-screen. Argus anchors to the last user bubble instead. Very long answers may require manual scrolling to reach the end.

Safe-area padding requires viewport-fit=cover. The viewport meta tag in frontend/index.html must include viewport-fit=cover; otherwise iOS safe-area insets may be zero, allowing the top bar or composer to overlap device hardware areas.

Known limitations
Incognito Chrome and authentication
Chrome's tracking protections and cookie policies can affect cross-site authentication when the frontend and backend are deployed on different Railway subdomains. In a fresh or incognito profile, login may appear to succeed while subsequent requests return 401 if the session cookie is not retained or sent.

For testing, use a normal browser profile and inspect cookie settings and network requests when authentication fails. For reliable cold-profile behaviour, consider serving the frontend and backend from a single origin or using a deployment/auth configuration designed for cross-site cookies.

Mobile requires viewport-fit=cover
If the viewport meta tag in frontend/index.html loses viewport-fit=cover, iOS safe-area padding may stop working. The top bar can overlap the notch and the composer can overlap the home indicator. The fix is to restore:

<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover" />
License
Private project. Not for redistribution.