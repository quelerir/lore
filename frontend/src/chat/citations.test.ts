import { describe, expect, it } from "vitest";
import type { IStep } from "@chainlit/react-client";
import { collectCitationsByMessage, extractCitations } from "./citations";

const step = (metadata: unknown): IStep =>
  ({ id: "s1", name: "assistant", type: "assistant_message", output: "ответ", metadata } as IStep);

const raw = {
  chunk_id: "c1",
  run_id: "r1",
  logical_file_key: "manual.pdf",
  preview_text: "превью источника",
  heading_path: ["Root", "Раздел"],
  deep_link: "/files?file=manual.pdf&run=r1&chunk=c1&tab=display",
};

describe("extractCitations", () => {
  it("returns [] when metadata has no citations", () => {
    expect(extractCitations(step(undefined))).toEqual([]);
    expect(extractCitations(step({}))).toEqual([]);
    expect(extractCitations(step({ citations: "nope" }))).toEqual([]);
  });

  it("maps snake_case metadata to typed Citations", () => {
    const cites = extractCitations(step({ citations: [raw] }));
    expect(cites).toHaveLength(1);
    expect(cites[0].chunkId).toBe("c1");
    expect(cites[0].logicalFileKey).toBe("manual.pdf");
    expect(cites[0].headingPath).toEqual(["Root", "Раздел"]);
    expect(cites[0].deepLink).toContain("/files?file=manual.pdf");
  });

  it("drops entries missing a deep_link or chunk_id (no broken cards)", () => {
    const cites = extractCitations(
      step({ citations: [{ preview_text: "x" }, { ...raw, deep_link: "" }, raw] }),
    );
    expect(cites).toHaveLength(1);
    expect(cites[0].chunkId).toBe("c1");
  });

  it("maps kind and marker, defaulting to text/null", () => {
    const cites = extractCitations(
      step({
        citations: [
          { ...raw, chunk_id: "a1", deep_link: "/files?...&tab=payloads", kind: "table", marker: 2 },
          raw, // legacy shape: no kind/marker
        ],
      }),
    );
    expect(cites[0].kind).toBe("table");
    expect(cites[0].marker).toBe(2);
    expect(cites[1].kind).toBe("text");
    expect(cites[1].marker).toBeNull();
  });
});

describe("collectCitationsByMessage", () => {
  const node = (id: string, metadata: unknown, steps?: IStep[]): IStep =>
    ({ id, type: "assistant_message", output: "a", metadata, steps } as IStep);

  it("maps assistant_message id → citations, walking nested run steps", () => {
    // Ответ приходит вложенным в run-обёртку on_message (steps), как в реальном дереве.
    const run = { id: "run1", type: "run", steps: [node("m1", { citations: [raw] })] } as IStep;
    const map = collectCitationsByMessage([run]);
    expect([...map.keys()]).toEqual(["m1"]);
    expect(map.get("m1")?.[0].chunkId).toBe("c1");
  });

  it("omits messages without citations", () => {
    const map = collectCitationsByMessage([node("m1", {}), node("m2", { citations: [raw] })]);
    expect([...map.keys()]).toEqual(["m2"]);
  });
});
