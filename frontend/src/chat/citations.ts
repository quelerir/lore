import type { IStep } from "@chainlit/react-client";

/**
 * Цитаты-источники, которые бэкенд вешает на metadata сообщения ассистента
 * (см. docs/superpowers/specs/2026-07-21-chat-citations-fileviewer-design.md).
 * Каждая цитата — превью чанка + deep-link в FileViewer (`/files?...`).
 *
 * ⚠️ NOT EXECUTED in the agent env (Node 16 can't run vite/vitest v3). Pure TS,
 * matches the existing test style — verify with `npm test` on Node 20.
 */
export interface Citation {
  chunkId: string;
  runId: string;
  logicalFileKey: string;
  previewText: string;
  headingPath: string[];
  deepLink: string;
}

interface RawCitation {
  chunk_id?: unknown;
  run_id?: unknown;
  logical_file_key?: unknown;
  preview_text?: unknown;
  heading_path?: unknown;
  deep_link?: unknown;
}

const asString = (value: unknown): string => (typeof value === "string" ? value : "");

const toCitation = (raw: RawCitation): Citation | null => {
  const deepLink = asString(raw.deep_link);
  const chunkId = asString(raw.chunk_id);
  // A citation must be linkable; otherwise drop it (no broken cards).
  if (!deepLink || !chunkId) return null;
  return {
    chunkId,
    runId: asString(raw.run_id),
    logicalFileKey: asString(raw.logical_file_key),
    previewText: asString(raw.preview_text),
    headingPath: Array.isArray(raw.heading_path) ? raw.heading_path.map(asString) : [],
    deepLink,
  };
};

/** Read + validate citations from a chat step's metadata. Returns [] when absent/invalid. */
export function extractCitations(step: IStep): Citation[] {
  const meta = (step.metadata ?? {}) as { citations?: unknown };
  if (!Array.isArray(meta.citations)) return [];
  return meta.citations
    .map((entry) => toCitation((entry ?? {}) as RawCitation))
    .filter((entry): entry is Citation => entry !== null);
}

/**
 * id ассистентского сообщения → его цитаты, обходя дерево шагов (ответ приходит
 * вложенным в run-обёртку on_message — как и в collectTraceByMessage). Мапой
 * пользуется AssistantMessage через sessionUi, по аналогии с traceByMessage.
 * Сообщения без цитат в мапу не попадают.
 */
export function collectCitationsByMessage(steps: IStep[]): Map<string, Citation[]> {
  const out = new Map<string, Citation[]>();
  const walk = (nodes: IStep[]): void => {
    for (const node of nodes) {
      if (node.type === "assistant_message") {
        const cites = extractCitations(node);
        if (cites.length) out.set(node.id, cites);
      }
      if (node.steps?.length) walk(node.steps);
    }
  };
  walk(steps);
  return out;
}
