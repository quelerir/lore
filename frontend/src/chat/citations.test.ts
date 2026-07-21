import { describe, expect, it } from "vitest";
import type { IStep } from "@chainlit/react-client";
import { extractCitations } from "./citations";

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
});
