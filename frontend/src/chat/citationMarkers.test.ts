import { describe, expect, it } from "vitest";
import type { Element, Root } from "hast";
import { rehypeCitationMarkers } from "./citationMarkers";

const paragraph = (text: string): Root => ({
  type: "root",
  children: [
    { type: "element", tagName: "p", properties: {}, children: [{ type: "text", value: text }] },
  ],
});

const run = (tree: Root, markers: number[]): Root => {
  rehypeCitationMarkers(new Set(markers))(tree);
  return tree;
};

const sups = (tree: Root): Element[] => {
  const out: Element[] = [];
  const walk = (node: { type: string; tagName?: string; children?: unknown[] }) => {
    if (node.type === "element" && node.tagName === "sup") out.push(node as unknown as Element);
    (node.children ?? []).forEach((c) => walk(c as { type: string; children?: unknown[] }));
  };
  walk(tree as unknown as { type: string; children?: unknown[] });
  return out;
};

describe("rehypeCitationMarkers", () => {
  it("wraps a known [n] in a sup carrying dataMarker", () => {
    const s = sups(run(paragraph("Итог [2] верный."), [2]));
    expect(s).toHaveLength(1);
    expect(s[0].properties?.dataMarker).toBe(2);
    expect((s[0].children[0] as { value: string }).value).toBe("2");
  });

  it("leaves unknown markers as plain text", () => {
    expect(sups(run(paragraph("Ссылка [9]."), [2]))).toHaveLength(0);
  });

  it("does not touch markers inside code", () => {
    const tree: Root = {
      type: "root",
      children: [
        { type: "element", tagName: "code", properties: {}, children: [{ type: "text", value: "arr[2]" }] },
      ],
    };
    rehypeCitationMarkers(new Set([2]))(tree);
    expect(sups(tree)).toHaveLength(0);
  });
});
