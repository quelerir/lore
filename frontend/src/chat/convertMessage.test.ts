import { describe, expect, it } from "vitest";
import type { IStep } from "@chainlit/react-client";
import { collectChatMessages, convertMessage, isChatMessage } from "./convertMessage";

const step = (over: Partial<IStep>): IStep =>
  ({
    id: "s1",
    name: "user",
    type: "user_message",
    output: "привет",
    createdAt: "2026-07-15T12:00:00Z",
    ...over,
  }) as IStep;

describe("isChatMessage", () => {
  it("пропускает только сообщения", () => {
    expect(isChatMessage(step({ type: "user_message" }))).toBe(true);
    expect(isChatMessage(step({ type: "assistant_message" }))).toBe(true);
    expect(isChatMessage(step({ type: "run" }))).toBe(false);
    expect(isChatMessage(step({ type: "tool" }))).toBe(false);
  });
});

describe("convertMessage", () => {
  it("маппит user_message", () => {
    const m = convertMessage(step({}));
    expect(m.role).toBe("user");
    expect(m.content).toEqual([{ type: "text", text: "привет" }]);
    expect(m.id).toBe("s1");
  });

  it("маппит стримящийся assistant_message в running", () => {
    const m = convertMessage(
      step({ type: "assistant_message", output: "отв", streaming: true }),
    );
    expect(m.role).toBe("assistant");
    expect(m.status?.type).toBe("running");
  });

  it("завершённый assistant_message — complete", () => {
    const m = convertMessage(step({ type: "assistant_message", streaming: false }));
    expect(m.status?.type).toBe("complete");
  });

  it("пустой output не ломает", () => {
    const m = convertMessage(step({ output: undefined as unknown as string }));
    expect(m.content).toEqual([{ type: "text", text: "" }]);
  });
});

describe("collectChatMessages", () => {
  // Chainlit оборачивает on_message в run-шаг, а ответ ассистента создаётся
  // внутри → assistant_message приходит вложенным (parentId = on_message).
  // react-client кладёт такие шаги в .steps родителя, а не в верхний уровень.
  it("собирает сообщения из вложенных run-обёрток", () => {
    const tree: IStep[] = [
      step({ id: "start", name: "on_chat_start", type: "run", output: "" }),
      step({
        id: "u1",
        type: "user_message",
        output: "Привет!",
        createdAt: "2026-07-16T09:01:46.920Z",
        steps: [
          step({
            id: "run1",
            name: "on_message",
            type: "run",
            output: "",
            createdAt: "2026-07-16T09:01:46.925Z",
            steps: [
              step({
                id: "a1",
                name: "datacraft",
                type: "assistant_message",
                output: "Здравствуйте!",
                createdAt: "2026-07-16T09:01:46.928Z",
              }),
              step({ id: "lg", name: "LangGraph", type: "run", output: "{}" }),
            ],
          }),
        ],
      }),
    ];

    const msgs = collectChatMessages(tree);

    expect(msgs.map((m) => m.id)).toEqual(["u1", "a1"]);
  });

  it("сохраняет хронологический порядок независимо от вложенности", () => {
    const tree: IStep[] = [
      step({ id: "u2", type: "user_message", createdAt: "2026-07-16T09:05:00Z" }),
      step({
        id: "u1",
        type: "user_message",
        createdAt: "2026-07-16T09:01:00Z",
        steps: [
          step({
            id: "a1",
            type: "assistant_message",
            createdAt: "2026-07-16T09:01:05Z",
          }),
        ],
      }),
    ];

    expect(collectChatMessages(tree).map((m) => m.id)).toEqual(["u1", "a1", "u2"]);
  });
});
