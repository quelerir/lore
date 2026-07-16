import { describe, expect, it } from "vitest";
import type { IStep } from "@chainlit/react-client";
import { collectToolStepsByMessage } from "./executionSteps";

const step = (over: Partial<IStep>): IStep =>
  ({
    id: "s1",
    name: "step",
    type: "run",
    output: "",
    createdAt: "2026-07-16T09:00:00Z",
    ...over,
  }) as IStep;

describe("collectToolStepsByMessage", () => {
  it("пустая Map, если инструментов нет", () => {
    const tree: IStep[] = [
      step({ id: "u1", type: "user_message", output: "привет" }),
    ];
    expect(collectToolStepsByMessage(tree).size).toBe(0);
  });

  it("группирует tool-шаги по ответу того же on_message-run", () => {
    const tree: IStep[] = [
      step({
        id: "u1",
        type: "user_message",
        output: "грейды",
        steps: [
          step({
            id: "run1",
            name: "on_message",
            type: "run",
            steps: [
              step({ id: "a1", type: "assistant_message", output: "ответ" }),
              step({
                id: "lg",
                name: "LangGraph",
                type: "run",
                steps: [
                  step({
                    id: "t1",
                    name: "query_document_tables",
                    type: "tool",
                    input: "грейды",
                    output: "{...}",
                    createdAt: "2026-07-16T09:00:01Z",
                  }),
                ],
              }),
            ],
          }),
        ],
      }),
    ];

    const map = collectToolStepsByMessage(tree);
    expect([...map.keys()]).toEqual(["a1"]);
    expect(map.get("a1")!.map((s) => s.id)).toEqual(["t1"]);
  });

  it("не смешивает инструменты между двумя ходами", () => {
    const turn = (uid: string, aid: string, tid: string): IStep =>
      step({
        id: uid,
        type: "user_message",
        steps: [
          step({
            id: `run-${uid}`,
            type: "run",
            steps: [
              step({ id: aid, type: "assistant_message", output: "ok" }),
              step({
                id: `lg-${uid}`,
                type: "run",
                steps: [step({ id: tid, type: "tool", name: "calculator" })],
              }),
            ],
          }),
        ],
      });
    const tree: IStep[] = [turn("u1", "a1", "t1"), turn("u2", "a2", "t2")];

    const map = collectToolStepsByMessage(tree);
    expect(map.get("a1")!.map((s) => s.id)).toEqual(["t1"]);
    expect(map.get("a2")!.map((s) => s.id)).toEqual(["t2"]);
  });

  it("игнорирует llm-шаги (внутренний SQL)", () => {
    const tree: IStep[] = [
      step({
        id: "run1",
        type: "run",
        steps: [
          step({ id: "a1", type: "assistant_message", output: "ответ" }),
          step({ id: "llm1", type: "llm", name: "sql-plan" }),
        ],
      }),
    ];
    expect(collectToolStepsByMessage(tree).size).toBe(0);
  });
});
