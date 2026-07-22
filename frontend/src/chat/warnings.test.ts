import { describe, expect, it } from "vitest";
import type { IStep } from "@chainlit/react-client";
import { collectWarningsByMessage, extractWarnings } from "./warnings";

const step = (metadata: unknown): IStep =>
  ({ id: "s1", type: "assistant_message", output: "ответ", metadata } as IStep);

describe("extractWarnings", () => {
  it("returns [] when metadata has no degradations/error", () => {
    expect(extractWarnings(step(undefined))).toEqual([]);
    expect(extractWarnings(step({}))).toEqual([]);
    expect(extractWarnings(step({ degradations: "nope" }))).toEqual([]);
  });

  it("maps known degradation codes to human labels, deduped", () => {
    const w = extractWarnings(
      step({ degradations: ["table_lane_unavailable", "table_lane_unavailable", "vector_search_failed"] }),
    );
    expect(w).toHaveLength(2); // deduped
    expect(w.every((x) => x.level === "warning")).toBe(true);
    expect(w[0].text).toContain("Таблицы недоступны");
  });

  it("falls back to a generic label for unknown codes", () => {
    const w = extractWarnings(step({ degradations: ["weird_new_code"] }));
    expect(w[0].text).toContain("weird_new_code");
  });

  // Guard: every degradation code the backend can emit must have a human label,
  // never the raw-code fallback. Keep this list in sync with the backend —
  // grep `degradations`/`degraded.append` in lore-retrieval + lore-chat.
  it("has a human label for every known backend degradation code", () => {
    const BACKEND_CODES = [
      "answer_generation_failed",
      "auto_merging_failed",
      "context_load_failed",
      "fulltext_search_failed",
      "reranker_failed",
      "structural_expansion_failed",
      "table_lane_unavailable",
      "vector_search_failed",
    ];
    for (const code of BACKEND_CODES) {
      const [w] = extractWarnings(step({ degradations: [code] }));
      expect(w, code).toBeDefined();
      expect(w.text, code).not.toContain(code); // not the `Ограничение: <code>` fallback
      expect(w.text, code).not.toContain("Ограничение:");
    }
  });

  it("surfaces a hard error as an error-level warning", () => {
    const w = extractWarnings(step({ error: "HTTPStatusError" }));
    expect(w).toEqual([{ level: "error", text: "Ошибка при обработке запроса" }]);
  });
});

describe("collectWarningsByMessage", () => {
  const node = (id: string, metadata: unknown, steps?: IStep[]): IStep =>
    ({ id, type: "assistant_message", output: "a", metadata, steps } as IStep);

  it("maps assistant_message id → warnings, walking nested run steps", () => {
    const run = {
      id: "run1",
      type: "run",
      steps: [node("m1", { degradations: ["vector_search_failed"] })],
    } as IStep;
    const map = collectWarningsByMessage([run]);
    expect([...map.keys()]).toEqual(["m1"]);
    expect(map.get("m1")?.[0].level).toBe("warning");
  });

  it("omits messages without warnings", () => {
    const map = collectWarningsByMessage([node("m1", {}), node("m2", { error: "x" })]);
    expect([...map.keys()]).toEqual(["m2"]);
  });
});
