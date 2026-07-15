import { describe, expect, it } from "vitest";
import type { IStep } from "@chainlit/react-client";
import { convertMessage, isChatMessage } from "./convertMessage";

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
