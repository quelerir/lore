import { describe, expect, it } from "vitest";
import type { IStep } from "@chainlit/react-client";
import { collectTraceByMessage } from "./executionSteps";

const step = (over: Partial<IStep>): IStep =>
  ({
    id: "s1",
    name: "step",
    type: "run",
    output: "",
    createdAt: "2026-07-16T09:00:00Z",
    ...over,
  }) as IStep;

describe("collectTraceByMessage", () => {
  it("пустая Map, если хода нет", () => {
    const tree: IStep[] = [
      step({ id: "u1", type: "user_message", output: "привет" }),
    ];
    expect(collectTraceByMessage(tree).size).toBe(0);
  });

  it("отдаёт всё поддерево run'а: контейнеры и вложенные шаги", () => {
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
                  step({ id: "t1", name: "calculator", type: "tool" }),
                ],
              }),
            ],
          }),
        ],
      }),
    ];

    const map = collectTraceByMessage(tree);
    expect([...map.keys()]).toEqual(["a1"]);
    expect(map.get("a1")!.map((s) => s.id)).toEqual(["lg"]);
    expect(map.get("a1")![0].steps!.map((s) => s.id)).toEqual(["t1"]);
  });

  it("llm-шаги входят в трейс", () => {
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
    expect(collectTraceByMessage(tree).get("a1")!.map((s) => s.id)).toEqual([
      "llm1",
    ]);
  });

  it("*_message-шаги в трейс не попадают", () => {
    const tree: IStep[] = [
      step({
        id: "run1",
        type: "run",
        steps: [
          step({ id: "u1", type: "user_message", output: "вопрос" }),
          step({ id: "a1", type: "assistant_message", output: "ответ" }),
          step({ id: "t1", type: "tool", name: "calculator" }),
        ],
      }),
    ];
    expect(collectTraceByMessage(tree).get("a1")!.map((s) => s.id)).toEqual([
      "t1",
    ]);
  });

  it("не смешивает трейсы двух ходов", () => {
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
              step({ id: tid, type: "tool", name: "calculator" }),
            ],
          }),
        ],
      });
    const tree: IStep[] = [turn("u1", "a1", "t1"), turn("u2", "a2", "t2")];

    const map = collectTraceByMessage(tree);
    expect(map.get("a1")!.map((s) => s.id)).toEqual(["t1"]);
    expect(map.get("a2")!.map((s) => s.id)).toEqual(["t2"]);
  });

  it("вложенные tool-шаги остаются детьми и не дублируются на верхнем уровне", () => {
    const tree: IStep[] = [
      step({
        id: "run1",
        type: "run",
        steps: [
          step({ id: "a1", type: "assistant_message", output: "ответ" }),
          step({
            id: "stage1",
            name: "Выполнение SQL — раунд 1",
            type: "tool",
            steps: [
              step({ id: "att1", name: "Попытка 1", type: "tool" }),
              step({ id: "att2", name: "Попытка 2", type: "tool" }),
            ],
          }),
        ],
      }),
    ];
    const map = collectTraceByMessage(tree);
    expect(map.get("a1")!.map((s) => s.id)).toEqual(["stage1"]);
    expect(map.get("a1")![0].steps!.map((s) => s.id)).toEqual(["att1", "att2"]);
  });
});
