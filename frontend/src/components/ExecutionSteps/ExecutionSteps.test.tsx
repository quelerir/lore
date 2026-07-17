/** @vitest-environment happy-dom */
import { describe, expect, it } from "vitest";
import { act } from "react";
import { createRoot } from "react-dom/client";
import type { IStep } from "@chainlit/react-client";
import ExecutionSteps from "./ExecutionSteps";

const step = (over: Partial<IStep>): IStep =>
  ({
    id: "s",
    name: "step",
    type: "tool",
    output: "",
    createdAt: "2026-07-17T09:00:00Z",
    end: "2026-07-17T09:00:01Z",
    ...over,
  }) as IStep;

describe("ExecutionSteps", () => {
  it("рендерит двухуровневое дерево сворачиваемых стадий", async () => {
    const stage = step({
      id: "stage1",
      name: "Выполнение SQL — раунд 1",
      steps: [
        step({ id: "att1", name: "Попытка 1", input: "SELECT 1", output: "[]" }),
        step({ id: "att2", name: "Попытка 2", isError: true, output: "Ошибка" }),
      ],
    });
    const host = document.createElement("div");
    document.body.appendChild(host);
    const root = createRoot(host);
    await act(async () => {
      root.render(<ExecutionSteps steps={[stage]} running={false} />);
    });
    expect(host.textContent).toContain("Выполнение SQL — раунд 1");
    expect(host.textContent).toContain("Попытка 1");
    expect(host.textContent).toContain("Попытка 2");
    // details: панель + стадия + 2 попытки
    expect(host.querySelectorAll("details").length).toBe(4);
  });
});
