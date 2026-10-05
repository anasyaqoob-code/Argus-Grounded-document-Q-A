/** TypeScript mirrors of backend schemas. */

export type DocumentStatus = "pending" | "indexing" | "ready" | "failed";

export interface DocumentInfo {
  document_id: string;
  filename: string;
  status: DocumentStatus;
  page_count?: number | null;
  chunk_count?: number | null;
  created_at?: string | null;
  error?: string | null;
}

export interface Citation {
  document_id: string;
  filename: string;
  page?: number | null;
  chunk_id: string;
  quote: string;
  score: number;
}

export interface QueryRequest {
  query: string;
  session_id?: string | null;
  document_ids?: string[] | null;
  top_k?: number | null;
  stream?: boolean;
  temperature?: number | null;
  max_tokens?: number | null;
  score_threshold?: number | null;
  require_citations?: boolean;
  allow_abstain?: boolean;
}

export interface AnswerResponse {
  answer: string;
  citations: Citation[];
  abstained: boolean;
  abstain_reason?: string | null;
  session_id: string;
  confidence?: number | null;
  metadata?: Record<string, unknown>;
}

export interface UploadResponse {
  document_id: string;
  filename: string;
  status: DocumentStatus;
  message: string;
}

// ---------------------------------------------------------------------------
// Sessions (mirrors the backend's SessionInfo / ChatMessageResponse)
// ---------------------------------------------------------------------------
export interface SessionInfo {
  session_id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
}

export interface SessionMessage {
  message_id: number;
  role: "user" | "assistant";
  content: string;
  created_at: string;
  metadata: Record<string, unknown>;
}

export interface SessionHistory {
  session_id: string;
  title: string;
  messages: SessionMessage[];
}

// ---------------------------------------------------------------------------
// Activity trace — one entry per pipeline step
// ---------------------------------------------------------------------------
export interface ActivityStep {
  state: string;
  status: "running" | "complete" | "failed";
  summary: string;
  duration_ms: number;
  metadata?: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Source preview — used by the sources accordion
// ---------------------------------------------------------------------------
export interface SourcePreview {
  source: string;
  page: number | string;
  preview: string;
}

// ---------------------------------------------------------------------------
// Image batch — one image upload + its extracted Q&A pairs
// ---------------------------------------------------------------------------
export interface ImageBatchItem {
  id: number;
  question: string;
  answer: string;
  citations: SourcePreview[];
  notCovered: boolean;
  streaming: boolean;
}

export interface ImageBatch {
  imageId: string;
  imageUrl: string;
  items: ImageBatchItem[];
}

// ---------------------------------------------------------------------------
// Chat message (UI-side, richer than the backend's ChatMessageResponse)
// ---------------------------------------------------------------------------
export type ChatRole = "user" | "assistant" | "system";

export interface ChatMessage {
  id: string;
  /** Server-assigned id, populated from the `final` SSE event. */
  messageId?: number;
  role: ChatRole;
  content: string;
  citations?: Citation[];
  abstained?: boolean;
  abstain_reason?: string | null;
  confidence?: number | null;
  streaming?: boolean;
  /** Activity trace steps, appended as `step` SSE events arrive. */
  trace?: ActivityStep[];
  /** Source previews for the sources accordion. */
  sources?: SourcePreview[];
  /**
   * Present when this message is an image batch — the uploaded image
   * plus its extracted Q&A list. Rendered as `MultiAnswerBubble`
   * instead of a normal `MessageBubble`.
   */
  batch?: ImageBatch;
}

// ---------------------------------------------------------------------------
// Agent settings
// ---------------------------------------------------------------------------
export interface AgentSettings {
  top_k: number;
  similarity_threshold: number;
  doc_relevance_floor: number;
  max_retrieval_attempts: number;
  memory_message_limit: number;
  query_rewriting: boolean;
  answer_verification: boolean;
  source_citations: boolean;
  chunk_size: number;
  chunk_overlap: number;
}

export const DEFAULT_AGENT_SETTINGS: AgentSettings = {
  top_k: 4,
  similarity_threshold: 0.0,
  doc_relevance_floor: 0.05,
  max_retrieval_attempts: 2,
  memory_message_limit: 6,
  query_rewriting: true,
  answer_verification: true,
  source_citations: true,
  chunk_size: 800,
  chunk_overlap: 150,
};