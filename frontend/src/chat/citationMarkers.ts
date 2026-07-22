import { visit } from "unist-util-visit";
import type { Element, Root, Text } from "hast";

const MARKER = /\[(\d+)\]/g;

/**
 * Rehype transform: turn `[n]` text into a clickable <sup> when n is a known
 * citation marker, skipping code/pre so `arr[2]` stays literal. A `[n]` with no
 * matching citation is left as plain text (never a dead link). The marker rides
 * on the canonical hast property `dataMarker` (rendered as `data-marker`).
 */
export function rehypeCitationMarkers(validMarkers: Set<number>) {
  return (tree: Root) => {
    visit(tree, "text", (node: Text, index, parent) => {
      if (
        index === null ||
        index === undefined ||
        !parent ||
        (parent.type === "element" &&
          ((parent as Element).tagName === "code" || (parent as Element).tagName === "pre"))
      ) {
        return;
      }
      const value = node.value;
      MARKER.lastIndex = 0;
      if (!MARKER.test(value)) return;
      MARKER.lastIndex = 0;

      const children: Array<Text | Element> = [];
      let last = 0;
      for (let m = MARKER.exec(value); m !== null; m = MARKER.exec(value)) {
        const n = Number(m[1]);
        if (!validMarkers.has(n)) continue;
        if (m.index > last) children.push({ type: "text", value: value.slice(last, m.index) });
        children.push({
          type: "element",
          tagName: "sup",
          properties: { className: ["citationMarker"], dataMarker: n },
          children: [{ type: "text", value: String(n) }],
        });
        last = m.index + m[0].length;
      }
      if (!children.length) return;
      if (last < value.length) children.push({ type: "text", value: value.slice(last) });
      (parent.children as Array<Text | Element>).splice(index, 1, ...children);
      return index + children.length;
    });
  };
}
