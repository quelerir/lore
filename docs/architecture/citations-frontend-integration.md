# Citations — Frontend Integration (Phase C)

Date: 2026-07-21
Status: partial. The pure extraction logic (`frontend/src/chat/citations.ts` + `.test.ts`) is written
but **NOT executed in the agent env** (Node 16 there can't run vite/vitest v3 — run `npm test` on
Node 20). The React rendering below is a reference sketch for a human to implement + eyeball, since it
can't be visually verified here.

## Data contract

The backend attaches citations to the assistant message as Chainlit message **metadata**:

```python
cl.Message(content=answer, metadata={"citations": [c.model_dump() for c in result.citations]})
```

Each entry is the snake_case `Citation` (chunk_id, run_id, logical_file_key, preview_text,
heading_path, deep_link). `extractCitations(step)` (done) validates + maps these to the typed
`Citation[]`, dropping any without a `deep_link`/`chunk_id`.

## Rendering (reference sketch)

The chat is a native SPA (`@assistant-ui/react` + `@chainlit/react-client`), not an iframe. A citation
click is a direct SPA navigation via the existing `navigateTo` (`src/router/AppRouter.tsx`).

`src/chat/CitationList.tsx` (to implement):

```tsx
import { navigateTo } from "../router/AppRouter";
import type { Citation } from "./citations";

export function CitationList({ citations }: { citations: Citation[] }) {
  if (!citations.length) return null;
  return (
    <div className="citations">
      {citations.map((c) => (
        <button
          key={c.chunkId}
          className="citation-card"
          title={c.headingPath.join(" / ")}
          onClick={() => navigateTo(c.deepLink)}   // opens /files?file=..&run=..&chunk=..&tab=display
        >
          <span className="citation-heading">{c.headingPath.join(" / ") || "Источник"}</span>
          <span className="citation-preview">{c.previewText}</span>
        </button>
      ))}
    </div>
  );
}
```

Wire it under the assistant message body. Two options depending on how messages render:

- If the message renderer has access to the raw `IStep`: call `extractCitations(step)` there and render
  `<CitationList citations={...} />` below the text.
- If it renders `ThreadMessageLike` (from `convertMessage`): thread the citations through — extend
  `convertMessage` to stash `extractCitations(step)` on the message `metadata`, then read it in the
  assistant message component. (assistant-ui `ThreadMessageLike` supports a `metadata` bag.)

## Follow-ups

- Inline `[n]` superscripts in the answer text linking to the matching card (progressive enhancement).
- Broken-link handling is already the viewer's job (`VS-BROKEN-LINK` when membership is stale).
- Minimal CSS for `.citation-card` (compact, clickable, preview truncated with ellipsis).
