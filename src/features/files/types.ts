export type RunStatus = "success" | "active" | "failed" | "skipped";
export type ReviewVerdict = "OK" | "problem" | "question";
export type ReviewState = "open" | "reviewed";
export type InspectorTab =
  | "display"
  | "fulltext"
  | "vectortext"
  | "payloads"
  | "metadata"
  | "diagnostics";

export interface FileChunkPayloadRef {
  type: "table" | "image" | "transcript";
  id: string;
  label: string;
}

export interface FileChunk {
  id: string;
  ordinal: number;
  type: string;
  coordinates: string;
  section: string;
  displayText: string;
  fullText: string;
  vectorText: string;
  charCount: number;
  tokenCount: number;
  hash: string;
  contentSignature: string;
  warnings: string[];
  findings: string[];
  payloads: FileChunkPayloadRef[];
  metadata: Record<string, string>;
  diagnostics: Array<{
    severity: "info" | "warning" | "error";
    code: string;
    message: string;
  }>;
}

export interface FileTablePayload {
  id: string;
  summary: string;
  coordinates: string;
  schema: Array<{ name: string; type: string }>;
  rowCount: number;
  columnCount: number;
  samples: Array<Record<string, string | number | null>>;
  contentId: string;
  usages: string[];
  relatedChunkIds: string[];
}

export interface FileImagePayload {
  id: string;
  title: string;
  description: string;
  mimeType: string;
  dimensions: string;
  fileSize: string;
  hash: string;
  coordinates: string;
  classification: string;
  warnings: string[];
  usages: string[];
  relatedChunkIds: string[];
  objectUrl?: string;
  unavailable?: boolean;
}

export interface FileTranscriptBlock {
  id: string;
  speaker: string;
  timeRange: string;
  display: string;
  fulltext: string;
  vectortext: string;
}

export interface FileTranscriptPayload {
  id: string;
  title: string;
  blocks: FileTranscriptBlock[];
  relatedChunkIds: string[];
}

export interface FileRun {
  id: string;
  label: string;
  processedAt: string;
  status: RunStatus;
  pipeline: string;
  autoAuditStatus: "clean" | "attention" | "missing";
  sourceUrl: string;
  originalUrl?: string;
  versionMismatch?: boolean;
  warnings: string[];
  errors: string[];
  chunks: FileChunk[];
  tables: FileTablePayload[];
  images: FileImagePayload[];
  transcripts: FileTranscriptPayload[];
}

export interface FileRecord {
  id: string;
  name: string;
  type: string;
  pipeline: string;
  runs: FileRun[];
}

export interface ReviewComment {
  id: string;
  verdict: ReviewVerdict;
  categories: string[];
  text: string;
  quote?: string;
  reviewerName: string;
  createdAt: string;
  updatedAt: string;
  state: ReviewState;
  environment: string;
  fileId: string;
  runId: string;
  objectType: "chunk";
  objectId: string;
  contentSignature: string;
  ordinal?: number;
  coordinates?: string;
  source: "human" | "agent";
}
