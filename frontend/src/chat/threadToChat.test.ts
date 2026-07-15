import { describe, expect, it } from "vitest";
import type { IThread } from "@chainlit/react-client";
import { threadToChat } from "./threadToChat";

const thread = (over: Partial<IThread>): IThread =>
  ({ id: "t1", createdAt: "2026-07-15T12:00:00Z", steps: [], ...over }) as IThread;

describe("threadToChat", () => {
  it("маппит имя и id", () => {
    const c = threadToChat(thread({ name: "Мой чат" }));
    expect(c).toMatchObject({ id: "t1", title: "Мой чат" });
    expect(c.time.length).toBeGreaterThan(0);
  });

  it("подставляет заглушку при отсутствии имени", () => {
    expect(threadToChat(thread({})).title).toBe("Без названия");
  });
});
